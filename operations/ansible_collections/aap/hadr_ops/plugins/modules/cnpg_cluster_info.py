#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the aap.hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: cnpg_cluster_info
short_description: Query CloudNativePG cluster topology and status
version_added: "1.0.0"
description:
  - Retrieves CNPG cluster topology information including primary designation and replication status.
  - Optionally includes AAP (Ansible Automation Platform) replica counts from the AnsibleAutomationPlatform CR.
  - Read-only module used for detecting current primary and gathering pre-switchover state.
  - This module does not make any changes; it always reports C(changed=false).
options:
  namespace:
    description: Kubernetes namespace containing the CNPG cluster.
    type: str
    required: true
  cluster_name:
    description: Name of the CloudNativePG Cluster custom resource.
    type: str
    required: true
  kubeconfig:
    description: Path to kubeconfig file. If empty, uses default context.
    type: str
    default: ""
  context:
    description: Kubernetes context name to use. If empty, uses current context.
    type: str
    default: ""
  include_aap_replicas:
    description: Whether to query AAP CR for replica counts.
    type: bool
    default: false
  aap_name:
    description: Name of the AnsibleAutomationPlatform CR (required if I(include_aap_replicas) is true).
    type: str
    default: "aap"
author:
  - AAP HA/DR Testing Team
requirements:
  - kubernetes Python client (C(pip install kubernetes>=12.0))
"""

EXAMPLES = r"""
- name: Get CNPG cluster topology for cluster-a
  aap.hadr_ops.cnpg_cluster_info:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
  register: cluster_a_info

- name: Get cluster info with AAP replicas
  aap.hadr_ops.cnpg_cluster_info:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-b
    include_aap_replicas: true
    aap_name: aap
  register: cluster_b_info

- name: Detect current primary cluster
  debug:
    msg: "Cluster {{ item.cluster_info.spec.self }} is primary"
  when: item.cluster_info.computed.is_primary
  loop:
    - "{{ cluster_a_info }}"
    - "{{ cluster_b_info }}"
"""

RETURN = r"""
cluster_info:
  description: CNPG cluster topology and status information.
  type: dict
  returned: always
  contains:
    spec:
      description: Cluster specification fields.
      type: dict
      contains:
        self:
          description: This cluster's identifier (e.g., "cluster-a").
          type: str
        primary:
          description: Which cluster is designated as primary.
          type: str
        source:
          description: Replication source cluster name (empty for primary).
          type: str
    status:
      description: Cluster status fields.
      type: dict
      contains:
        phase:
          description: Current cluster phase (e.g., "Cluster in healthy state").
          type: str
        currentPrimary:
          description: Current primary pod name (e.g., "aap-postgres-1").
          type: str
    computed:
      description: Computed values for convenience.
      type: dict
      contains:
        is_primary:
          description: True if this cluster is the primary (spec.replica.primary == spec.replica.self).
          type: bool
aap_replicas:
  description: AAP component replica counts (only if I(include_aap_replicas) is true).
  type: dict
  returned: when include_aap_replicas is true
  contains:
    gateway:
      description: Gateway replicas.
      type: int
    controller_web:
      description: Controller web replicas.
      type: int
    controller_task:
      description: Controller task replicas.
      type: int
    hub_api:
      description: Hub API replicas.
      type: int
    hub_content:
      description: Hub content replicas.
      type: int
    hub_web:
      description: Hub web replicas.
      type: int
    hub_worker:
      description: Hub worker replicas.
      type: int
    eda_api:
      description: EDA API replicas.
      type: int
    eda_worker:
      description: EDA worker replicas.
      type: int
    eda_default_worker:
      description: EDA default worker replicas.
      type: int
    eda_activation_worker:
      description: EDA activation worker replicas.
      type: int
    metrics_disabled:
      description: Whether metrics service is disabled.
      type: bool
    lightspeed_disabled:
      description: Whether lightspeed service is disabled.
      type: bool
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.aap.hadr_ops.plugins.module_utils.k8s_helper import (
    create_helper,
    extract_aap_replicas,
)
from ansible_collections.aap.hadr_ops.plugins.module_utils import constants as const


def get_cnpg_cluster_info(module, helper, namespace, cluster_name):
    """Query CNPG cluster CR and return parsed topology information."""
    try:
        cluster_data = helper.get_custom_resource(
            const.CNPG_GROUP, const.CNPG_VERSION, namespace, const.CNPG_PLURAL, cluster_name,
        )
    except Exception as exc:
        module.fail_json(
            msg="Failed to get CNPG cluster %s in namespace %s: %s"
                % (cluster_name, namespace, exc),
        )

    # Extract relevant fields from the CR
    spec_replica = cluster_data.get("spec", {}).get("replica", {})
    status = cluster_data.get("status", {})

    self_name = spec_replica.get("self", "")
    primary_name = spec_replica.get("primary", "")
    source_name = spec_replica.get("source", "")

    return {
        "spec": {
            "self": self_name,
            "primary": primary_name,
            "source": source_name,
        },
        "status": {
            "phase": status.get("phase", ""),
            "currentPrimary": status.get("currentPrimary", ""),
        },
        "computed": {
            "is_primary": (primary_name == self_name and self_name != "")
        },
    }


def get_aap_replicas(module, helper, namespace, aap_name):
    """Query AnsibleAutomationPlatform CR and return replica counts."""
    try:
        cr_data = helper.get_custom_resource(
            const.AAP_GROUP, const.AAP_VERSION, namespace, const.AAP_PLURAL, aap_name,
        )
    except Exception as exc:
        module.fail_json(
            msg="Failed to get AAP CR %s in namespace %s: %s"
                % (aap_name, namespace, exc),
        )

    return extract_aap_replicas(cr_data.get("spec", {}))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', required=True),
            cluster_name=dict(type='str', required=True),
            kubeconfig=dict(type='str', default=''),
            context=dict(type='str', default=''),
            include_aap_replicas=dict(type='bool', default=False),
            aap_name=dict(type='str', default='aap'),
        ),
        supports_check_mode=True,
    )

    helper = create_helper(module)

    # Get CNPG cluster info
    cluster_info = get_cnpg_cluster_info(
        module, helper, module.params['namespace'], module.params['cluster_name'],
    )

    result = {
        'changed': False,
        'cluster_info': cluster_info,
    }

    # Optionally get AAP replicas
    if module.params['include_aap_replicas']:
        result['aap_replicas'] = get_aap_replicas(
            module, helper, module.params['namespace'], module.params['aap_name'],
        )

    module.exit_json(**result)


if __name__ == '__main__':
    main()
