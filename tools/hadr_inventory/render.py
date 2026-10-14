#!/usr/bin/env python3
"""Evaluate local ApplicationSet inventory/templates and render Kustomize resources."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import os
import yaml
from configure import application_sets
from inventory import ROOT, check, load_inventory

EXTERNAL_SECRET_EXCEPTIONS = {
    'aap-admin-password', 'aap-controller-postgres-configuration',
    'aap-eda-event-stream-postgres-configuration', 'aap-eda-postgres-configuration',
    'aap-gateway-postgres-configuration', 'aap-hub-postgres-configuration',
    'aap-metrics-controller-postgres-configuration', 'aap-metrics-postgres-configuration',
    'hub-rgw-s3-credentials', 'postgres-admin-credentials',
}


def evaluate(value, params):
    template = Path(os.environ.get("HADR_TEMPLATE_BINARY", ROOT / "build/template"))
    result = subprocess.run([str(template)], input=json.dumps({'Value': value, 'Params': params}),
                            text=True, capture_output=True)
    check(result.returncode == 0, result.stderr)
    return json.loads(result.stdout)


def merge(target, patch):
    # JSON merge patch semantics used by ApplicationSet templatePatch.
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            merge(target[key], value)
        else:
            target[key] = value


def generated_apps(directory, inventory, cluster_id):
    for appset in application_sets(directory, inventory, cluster_id):
        stored = Path(directory) / 'bootstrap' / cluster_id / (appset['metadata']['name'] + '.yaml')
        check(stored.exists() and yaml.safe_load(stored.read_text()) == appset,
              f'{stored}: missing or stale; run configure first')
        generator = appset['spec']['generators'][0]
        inner, environment_generator = generator['matrix']['generators']
        pair_generator, members_generator = inner['matrix']['generators']
        pattern = pair_generator['git']['files'][0]['path']
        for pair_path in sorted(ROOT.glob(pattern)):
            pair = yaml.safe_load(pair_path.read_text())
            members = yaml.safe_load(evaluate(members_generator['list']['elementsYaml'], pair))
            for member in members:
                params = {**pair, **member}
                path = evaluate(environment_generator['git']['files'][0]['path'], params)
                env = yaml.safe_load((ROOT / path).read_text())
                if env['target_cluster_id'] != generator['selector']['matchLabels']['target_cluster_id']:
                    continue
                params.update(env)
                params['cluster_id'] = cluster_id
                template = evaluate(appset['spec']['template'], params)
                app = dict(apiVersion='argoproj.io/v1alpha1', kind='Application', **template)
                if 'templatePatch' in appset['spec']:
                    merge(app, yaml.safe_load(evaluate(appset['spec']['templatePatch'], params)))
                yield app


def resources(app):
    if 'sources' in app['spec']:
        return ''
    source = app['spec']['source']
    # Keep the temporary overlay inside the repo; no relaxed Kustomize load restriction.
    with tempfile.TemporaryDirectory(prefix='.render-', dir=ROOT / 'build') as temporary:
        k = {'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization',
             'resources': ['../../' + source['path']], **source.get('kustomize', {})}
        Path(temporary, 'kustomization.yaml').write_text(yaml.safe_dump(k, sort_keys=False))
        result = subprocess.run(['kubectl', 'kustomize', temporary], text=True, capture_output=True)
        check(result.returncode == 0, result.stderr)
        output = result.stdout
    check('MUST_BE_SET' not in output and 'zone-template' not in output, f'{app["metadata"]["name"]}: unresolved placeholder')
    return output


def validate_application_labels(app, pair_id, environment_id, role):
    labels = app['metadata'].get('labels', {})
    if app['metadata']['name'] == 'aap-dns':
        return
    check(labels, f"{app['metadata']['name']}: missing operations identity labels")
    check(labels['aap.hadr.redhat.com/pair'] == pair_id and
          labels['aap.hadr.redhat.com/environment'] == environment_id,
          'operations identity mismatch')
    if app['metadata']['name'] in ('aap-cnpg', 'aap-platform'):
        check(labels['aap.hadr.redhat.com/desired-role'] == role, 'operations role mismatch')


def audit(documents, applications, inventory, cluster_id):
    env = next(e for e in inventory['environments'].values() if e['target_cluster_id'] == cluster_id)
    pair = next(iter(inventory['pairs'].values()))
    primary = env['environment_id'] == pair['desired_primary_environment_id']
    role = 'primary' if primary else 'replica'
    cnpg = next(d for d in documents if d['kind'] == 'Cluster')['spec']
    n = env['workloads']['cnpg']
    check(cnpg['replica'] == {'self': n['site_name'], 'source': n['peer']['site_name'],
                             'primary': n['site_name'] if primary else n['peer']['site_name']},
          'CNPG distributed topology mismatch')
    check(cnpg['instances'] == n['instances'] and cnpg['storage']['size'] == n['data_size']
          and cnpg['walStorage']['size'] == n['wal_size'], 'CNPG capacity mismatch')
    if primary:
        check('initdb' in cnpg['bootstrap'], 'primary must initialize')
    else:
        check(cnpg['bootstrap'] == {'pg_basebackup': {'source': n['peer']['site_name']}}, 'replica must clone peer')
    platform = next(d for d in documents if d['kind'] == 'AnsibleAutomationPlatform')['spec']
    check(platform['idle_aap'] is (not primary), 'AAP idle state mismatch')
    check(platform['public_base_url'] == env['workloads']['platform']['public_base_url'], 'AAP URL mismatch')
    realm = next(d for d in documents if d['kind'] == 'CephObjectRealm')
    check(('pull' in realm['spec']) == (env['rgw_role'] == 'replica'), 'RGW realm role mismatch')
    claims = [d for d in documents if d['kind'] == 'ObjectBucketClaim']
    check(len(claims) == (2 if env['rgw_role'] == 'primary' else 0), 'RGW bucket ownership mismatch')
    zone = next(d for d in documents if d['kind'] == 'CephObjectZone')
    check(zone['metadata']['name'] == env['rgw_zone_name'], 'RGW zone mismatch')
    check(zone['spec']['customEndpoints'] == [env['workloads']['odf']['endpoint']], 'RGW endpoint mismatch')
    for app in applications:
        validate_application_labels(app, pair['pair_id'], env['environment_id'], role)
        if 'sources' in app['spec']:
            continue
        source = app['spec']['source']
        check(source['repoURL'] == inventory['settings']['git']['repo_url'] and
              source['targetRevision'] == inventory['settings']['git']['revision'], 'Git source mismatch')
    subscriptions = [d for d in documents if d['kind'] == 'Subscription']
    aap_operator = next(d for d in subscriptions if d['spec']['name'] == 'ansible-automation-platform-operator')
    check(aap_operator['spec']['source'] == 'redhat-operators' and
          aap_operator['spec']['channel'] == 'stable-2.7', 'AAP must use released catalog')
    check(not any(d['kind'] == 'CatalogSource' for d in documents), 'unexpected catalog source')
    external = [d for d in documents if d['kind'] == 'ExternalSecret']
    secrets = {d['spec']['target']['name'] for d in external}
    def references(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith('_secret') and isinstance(child, str):
                    check(child in secrets or child in EXTERNAL_SECRET_EXCEPTIONS, f'platform secret has no producer: {child}')
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)
    references(platform)
    prefix = env['workloads']['eso']['secret_prefix'] + '/'
    for es in external:
        refs = [d['extract']['key'] for d in es['spec'].get('dataFrom', [])]
        refs += [d['remoteRef']['key'] for d in es['spec'].get('data', [])]
        external_keys = {'ec2_execution_nodes_ssh_keys', 'HADR_RED_HAT_ORGANIZATION'}
        check(all(key.startswith(prefix) or key in external_keys for key in refs), 'secret backend prefix mismatch')
    serialized = yaml.safe_dump_all(documents)
    check(not any(value in serialized for value in ('quay.io/aap/', 'hadr-controller-private',
              'deployment/manifests/', 'hadr-rosa-', 'MUST_BE_SET')), 'internal dependency in rendered resources')


def render(directory, output):
    inventory = load_inventory(directory)
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    subprocess.run(['go', 'build', '-o', str(build / 'template'), str(ROOT / 'scripts/template.go')], check=True)
    for cluster_id in inventory['clusters']:
        target = Path(output) / cluster_id
        target.mkdir(parents=True, exist_ok=True)
        applications = list(generated_apps(directory, inventory, cluster_id))
        expected = 5
        check(len(applications) == expected, f'{cluster_id}: expected {expected} Applications')
        (target / 'applications.yaml').write_text(yaml.safe_dump_all(applications, sort_keys=False))
        owned = set()
        documents = []
        for app in applications:
            rendered = resources(app)
            for doc in yaml.safe_load_all(rendered):
                documents.append(doc)
                identity = (doc['apiVersion'], doc['kind'], doc.get('metadata', {}).get('namespace', ''), doc['metadata']['name'])
                check(identity not in owned, f'duplicate resource ownership: {identity}')
                owned.add(identity)
            (target / f'{app["metadata"]["name"]}.yaml').write_text(rendered)
        audit(documents, applications, inventory, cluster_id)
        print(f'{cluster_id}: {expected} Applications, {len(owned)} resources, no unresolved sentinels or duplicate owners')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deployment', nargs='?', default='examples/aws-rosa-pair')
    parser.add_argument('--output', default='build/rendered')
    args = parser.parse_args()
    render(args.deployment, args.output)
