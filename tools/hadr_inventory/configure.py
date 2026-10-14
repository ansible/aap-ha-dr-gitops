#!/usr/bin/env python3
"""Write per-cluster ApplicationSets from validated inventory (local files only)."""
import argparse
import os
import re
from pathlib import Path
import shutil
import yaml
from inventory import ROOT, load_inventory

def represent_string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|' if '\n' in value else None)


yaml.SafeDumper.add_representer(str, represent_string)

LAYERS = ('eso', 'odf', 'cnpg', 'platform', 'dns')
EXAMPLE_SECRET_PREFIX = 'example/aap/shared'


def rewrite_deployment_content(content, deployment_prefix, secret_prefix):
    content = re.sub(
        r'(?:(?<![A-Za-z0-9_/-])|(?<=\$values/))examples/[A-Za-z0-9_.-]+/(?=(?:bootstrap|overlays|applicationsets)/)',
        deployment_prefix,
        content,
    )
    rewritten = []
    for line in content.splitlines(keepends=True):
        if 'secret_prefix:' in line:
            line = re.sub(r'(?<=secret_prefix:)\s*\S+', f' {secret_prefix}', line)
        elif re.search(r'\b(?:key|secret):', line):
            line = re.sub(
                r'(\b(?:key|secret):\s)(?:[A-Za-z0-9_.-]+/)+(?=[A-Za-z0-9_.-]+\s*$)',
                r'\1' + secret_prefix + '/', line,
            )
        line = line.replace(EXAMPLE_SECRET_PREFIX, secret_prefix)
        rewritten.append(line)
    return ''.join(rewritten)


def configure_dns_replica_counts(directory, inventory):
    values_root = Path(directory) / 'overlays' / 'external-dns' / 'overlays'
    for environment in inventory['environments'].values():
        cluster_id = environment['target_cluster_id']
        values_path = values_root / cluster_id / 'values.yaml'
        if not values_path.exists():
            continue
        enabled = environment.get('infrastructure', {}).get('external_dns', {}).get('enabled', False)
        content = values_path.read_text()
        content, count = re.subn(r'(?m)^replicaCount:\s*\d+\s*$',
                                  f'replicaCount: {1 if enabled else 0}', content)
        if count != 1:
            raise ValueError(f'missing External DNS replicaCount in {values_path}')
        values_path.write_text(content)


def application_sets(directory, inventory, cluster_id):
    data_root = Path(directory) / "deployment" / "argocd" if (Path(directory) / "deployment" / "argocd").exists() else Path(directory)
    relative = data_root.resolve().relative_to(ROOT).as_posix()
    applicationset_root = Path(directory) / "applicationsets"
    git = inventory['settings']['git']
    result = []
    cluster_envs = [e for e in inventory['environments'].values() if e['target_cluster_id'] == cluster_id]
    layers = LAYERS
    for layer in layers:
        appset_file = applicationset_root / f'aap-{layer}.yaml'
        if not appset_file.exists():
            appset_file = applicationset_root / f'aap-{layer}' / 'application-set.yaml'
        doc = yaml.safe_load(appset_file.read_text())
        spec = doc['spec']['template']['spec']
        if 'source' in spec and 'chart' not in spec['source']:
            spec['source'].update(repoURL=git['repo_url'], targetRevision=git['revision'])
        for source in spec.get('sources', []):
            if source.get('ref') == 'values' or source.get('path'):
                source.update(repoURL=git['repo_url'], targetRevision=git['revision'])
        pair_generator = {'git': {'repoURL': git['repo_url'], 'revision': git['revision'],
                                 'pathParamPrefix': 'pair', 'files': [{'path': f'{relative}/pairs/*.yaml'}]}}
        members = {'list': {'elementsYaml': '[{{ range $i, $id := .member_environments }}{{ if $i }},{{ end }}{"environment_id":{{ $id | toJson }}}{{ end }}]'}}
        env_generator = {'git': {'repoURL': git['repo_url'], 'revision': git['revision'],
                                'pathParamPrefix': 'environment',
                                'files': [{'path': relative + '/environments/{{ .environment_id }}.yaml'}]}}
        doc['spec']['generators'] = [{'matrix': {'generators': [
            {'matrix': {'generators': [pair_generator, members]}}, env_generator]},
            'selector': {'matchLabels': {'target_cluster_id': cluster_id}}}]
        result.append(doc)
    return result


def update_git_sources(path, git):
    doc = yaml.safe_load(path.read_text())

    def update(value):
        if isinstance(value, dict):
            # Helm sources keep their public repository and chart version.
            # Only rewrite Git-backed source/generator mappings.
            if 'chart' not in value:
                if 'repoURL' in value:
                    value['repoURL'] = git['repo_url']
                if 'targetRevision' in value:
                    value['targetRevision'] = git['revision']
                if 'revision' in value:
                    value['revision'] = git['revision']
            for child in value.values():
                update(child)
        elif isinstance(value, list):
            for child in value:
                update(child)

    update(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, width=110))


def configure(directory, pair_id=None):
    inventory = load_inventory(directory, pair_id=pair_id)
    configure_dns_replica_counts(directory, inventory)
    git = inventory['settings']['git']
    secret_prefix = next(iter(inventory['environments'].values()))['workloads']['eso']['secret_prefix']
    deployment_prefix = Path(directory).resolve().relative_to(ROOT).as_posix() + "/"
    for path in (*Path(directory).rglob('*.yaml'), *Path(directory).rglob('*.yml')):
        if 'build' in path.parts:
            continue
        content = path.read_text()
        # Rebase paths when a consumer copies the exported pair to a new name.
        # Replace the currently embedded prefix, not only the original example
        # value, so repeated configure runs remain reversible.
        path.write_text(rewrite_deployment_content(content, deployment_prefix, secret_prefix))

    config_roots = {Path(directory) / 'applicationsets', Path(directory) / 'argocd'}
    for root in config_roots:
        if root.exists():
            for path in root.glob('*.yaml'):
                update_git_sources(path, git)
    bootstrap = Path(directory) / 'bootstrap'
    bootstrap.mkdir(parents=True, exist_ok=True)
    for child in bootstrap.iterdir():
        if child.is_dir() and child.name not in inventory['clusters']:
            shutil.rmtree(child)
    for cluster_id in inventory['clusters']:
        target = bootstrap / cluster_id
        target.mkdir(parents=True, exist_ok=True)
        generated_layers = LAYERS
        for layer, doc in zip(generated_layers, application_sets(directory, inventory, cluster_id)):
            (target / f'aap-{layer}.yaml').write_text(yaml.safe_dump(doc, sort_keys=False, width=110))
        (target / 'kustomization.yaml').write_text(yaml.safe_dump({
            'apiVersion': 'kustomize.config.k8s.io/v1beta1', 'kind': 'Kustomization',
            'resources': [f'aap-{layer}.yaml' for layer in generated_layers]}, sort_keys=False))
    return inventory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deployment', nargs='?', default='examples/aws-rosa-pair')
    parser.add_argument('--pair-id', default='')
    args = parser.parse_args()
    configure(args.deployment, args.pair_id or None)
    print(f'Wrote bootstrap files in {args.deployment}/bootstrap; review and commit them before bootstrap.')
