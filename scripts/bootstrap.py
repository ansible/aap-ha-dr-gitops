#!/usr/bin/env python3
"""Explicit, inventory-targeted bootstrap; never switches current context."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import yaml

TOOLS_DIR = Path(__file__).resolve().parent.parent / 'tools' / 'hadr_inventory'
sys.path.insert(0, str(TOOLS_DIR))
from configure import application_sets, LAYERS
from inventory import ROOT, check, load_inventory


def run(command, **kwargs):
    return subprocess.run(command, text=True, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['gitops-install', 'gitops-rbac', 'apply-layer', 'eso-identity', 'status', 'ready'])
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--cluster', required=True, help='cluster_id from inventory')
    parser.add_argument('--layer', choices=LAYERS)
    args = parser.parse_args()
    inventory = load_inventory(args.deployment, deploy=True)
    check(args.cluster in inventory['clusters'], 'unknown cluster ID')
    cluster = inventory['clusters'][args.cluster]
    command = ['oc', '--context', cluster['context']]
    cfg = json.loads(run(command + ['config', 'view', '--minify', '-o', 'json'], capture_output=True).stdout)
    check(cfg['clusters'][0]['cluster']['server'].rstrip('/') == cluster['management_api_endpoint'].rstrip('/'),
          'context API endpoint does not match inventory')
    env = next(e for e in inventory['environments'].values() if e['target_cluster_id'] == args.cluster)
    if args.action in ('gitops-install', 'gitops-rbac'):
        filename = 'gitops-operator.yaml' if args.action == 'gitops-install' else 'gitops-rbac.yaml'
        run(command + ['apply', '-f', str(ROOT / 'bootstrap' / filename)])
    elif args.action == 'apply-layer':
        check(args.layer is not None, '--layer is required')
        expected = application_sets(args.deployment, inventory, args.cluster)[LAYERS.index(args.layer)]
        path = Path(args.deployment) / 'bootstrap' / args.cluster / f'aap-{args.layer}.yaml'
        check(path.exists() and yaml.safe_load(path.read_text()) == expected,
              'bootstrap files are stale; configure, review and publish before applying')
        run(command + ['apply', '-f', str(path)])
    elif args.action == 'eso-identity':
        run(command + ['-n', 'external-secrets', 'annotate', 'serviceaccount', 'external-secrets',
                       'eks.amazonaws.com/role-arn=' + env['workloads']['eso']['role_arn'], '--overwrite'])
    elif args.action == 'status':
        run(command + ['-n', 'openshift-gitops', 'get', 'applications'])
        run(command + ['-n', 'aap', 'get', 'externalsecrets,clusters.postgresql.cnpg.io,ansibleautomationplatforms'])
        run(command + ['-n', 'openshift-storage', 'get', 'storageclusters,cephobjectstores'])
    elif args.action == 'ready':
        check(args.layer is not None, '--layer is required')
        app = json.loads(run(command + ['-n', 'openshift-gitops', 'get', 'application', f'aap-{args.layer}', '-o', 'json'], capture_output=True).stdout)
        check(app.get('status', {}).get('sync', {}).get('status') == 'Synced', 'Application is not Synced')
        check(app.get('status', {}).get('health', {}).get('status') == 'Healthy', 'Application is not Healthy')
        if args.layer == 'eso':
            run(command + ['wait', 'clustersecretstore/cluster-cross-account-secret-store', '--for=condition=Ready', '--timeout=60s'])
            run(command + ['-n', 'aap', 'wait', 'externalsecret', '--all', '--for=condition=Ready', '--timeout=60s'])
        elif args.layer == 'cnpg':
            run(command + ['-n', 'aap', 'wait', 'cluster.postgresql.cnpg.io/aap-postgres', '--for=condition=Ready', '--timeout=60s'])
        elif args.layer == 'odf':
            store = json.loads(run(command + ['-n', 'openshift-storage', 'get', 'cephobjectstore/hub-objectstore', '-o', 'json'], capture_output=True).stdout)
            check(store.get('status', {}).get('phase') == 'Ready', 'RGW object store is not Ready')
        print(f'{args.cluster}/{args.layer}: readiness gate passed; verify cross-site behavior separately')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
