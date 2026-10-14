#!/usr/bin/env python3
"""Derive operations identities from deployment records; never reads cluster Secrets."""
import argparse
from pathlib import Path
import yaml
from inventory import load_inventory


def write_inventory(directory):
    inventory = load_inventory(directory)
    pair = next(iter(inventory['pairs'].values()))
    members = [inventory['environments'][name] for name in pair['member_environments']]
    clusters = {}
    master_site = None
    for key, env in zip(('a', 'b'), members):
        clusters[key] = {'context': inventory['clusters'][env['target_cluster_id']]['context'],
                         'site_id': env['workloads']['cnpg']['site_name']}
        if env['rgw_role'] == 'primary':
            master_site = key
    data = {'ansible_python_interpreter': '{{ ansible_playbook_python }}', 'cluster_set': '01', 'master_site': master_site, 'autofix': False,
            'cluster_sets': {'01': {'overlay_prefix': pair['pair_id'], 'clusters': clusters,
                                   'application_set': {'pair_id': pair['pair_id'],
                                                       'environment_id_a': members[0]['environment_id'],
                                                       'environment_id_b': members[1]['environment_id']}}}}
    target = Path(directory) / 'operations' / 'clusters.yml'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# Generated from deployment records; edit inventory and regenerate.\n' + yaml.safe_dump(data, sort_keys=False))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('deployment', nargs='?', default='examples/aws-rosa-pair')
    args = parser.parse_args()
    print(f'Wrote {write_inventory(args.deployment)}')
