#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the aap.hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: aap_platform_scale
short_description: Scale AAP platform components to zero or target replica counts
version_added: "1.0.0"
description:
  - Scales Ansible Automation Platform components by patching CRs and deployments.
  - Supports scaling to zero, toggling C(idle_aap) (preferred for switchover), or restoring target replica counts (for new primary).
  - Can read target replica counts from an AAP CR YAML file or from provided spec dict.
  - Optionally scales deployments/statefulsets directly for faster startup (bypasses operator reconciliation delay).
  - This module makes changes; it always reports C(changed=true) on success.
options:
  namespace:
    description: Kubernetes namespace containing AAP resources.
    type: str
    required: true
  aap_name:
    description: Name of the AnsibleAutomationPlatform CR.
    type: str
    default: "aap"
  kubeconfig:
    description: Path to kubeconfig file. If empty, uses default context.
    type: str
    default: ""
  context:
    description: Kubernetes context name to use. If empty, uses current context.
    type: str
    default: ""
  scale_to:
    description: Scaling target mode.
    type: str
    required: true
    choices: ['zero', 'from_cr_file', 'from_spec', 'idle', 'active']
  aap_cr_file:
    description: |
      Path to AAP CR YAML file to read replica counts from.
      Required when I(scale_to) is C(from_cr_file).
    type: str
    default: ""
  target_replicas:
    description: |
      Dictionary of component replica counts.
      Required when I(scale_to) is C(from_spec).
    type: dict
    default: {}
  direct_deployment_scale:
    description: |
      Whether to scale deployments/statefulsets directly in addition to patching CRs.
      Enables faster startup by bypassing operator reconciliation delay.
    type: bool
    default: true
author:
  - AAP HA/DR Testing Team
requirements:
  - kubernetes Python client (C(pip install kubernetes>=12.0))
  - PyYAML (for reading CR file with C(scale_to=from_cr_file))
"""

EXAMPLES = r"""
- name: Scale AAP to zero on old primary
  aap.hadr_ops.aap_platform_scale:
    namespace: aap
    aap_name: aap
    context: prod-cluster-a
    scale_to: zero

- name: Scale AAP on new primary from CR file
  aap.hadr_ops.aap_platform_scale:
    namespace: aap
    aap_name: aap
    context: prod-cluster-b
    scale_to: from_cr_file
    aap_cr_file: /path/to/deployment/manifests/base/05-aap-cr.yaml
    direct_deployment_scale: true
  register: scale_result

- name: Set AAP idle on standby cluster (idle_aap=true)
  aap.hadr_ops.aap_platform_scale:
    namespace: aap
    aap_name: aap
    context: prod-cluster-a
    scale_to: idle

- name: Activate AAP on primary cluster (idle_aap=false)
  aap.hadr_ops.aap_platform_scale:
    namespace: aap
    aap_name: aap
    context: prod-cluster-b
    scale_to: active

- name: Scale AAP from explicit spec
  aap.hadr_ops.aap_platform_scale:
    namespace: aap
    aap_name: aap
    scale_to: from_spec
    target_replicas:
      gateway: 2
      controller_web: 2
      controller_task: 3
      hub_api: 1
      hub_content: 1
      hub_web: 1
      hub_worker: 2
      eda_api: 1
      eda_worker: 1
      eda_default_worker: 1
      eda_activation_worker: 1
"""

RETURN = r"""
components_scaled:
  description: List of components that were scaled.
  type: list
  elements: str
  returned: always
replicas_set:
  description: Replica counts that were applied.
  type: dict
  returned: always
scale_to:
  description: The scaling mode that was used.
  type: str
  returned: always
message:
  description: Short status message.
  type: str
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.aap.hadr_ops.plugins.module_utils.k8s_helper import (
    create_helper,
    extract_aap_replicas,
)
from ansible_collections.aap.hadr_ops.plugins.module_utils import constants as const

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Zero-replica template reused by scale_aap_to_zero and the zero-value branch
_ZERO_REPLICAS = {
    k: 0 for k in [
        'gateway', 'controller_web', 'controller_task',
        'hub_api', 'hub_content', 'hub_web', 'hub_worker',
        'eda_api', 'eda_worker', 'eda_default_worker', 'eda_activation_worker',
    ]
}


def _build_aap_patch(target):
    """Build a merge-patch dict for the AnsibleAutomationPlatform CR."""
    return {
        "spec": {
            "idle_aap": False,
            "api": {"replicas": target['gateway']},
            "controller": {
                "web_replicas": target['controller_web'],
                "task_replicas": target['controller_task'],
            },
            "hub": {
                "api": {"replicas": target['hub_api']},
                "content": {"replicas": target['hub_content']},
                "web": {"replicas": target['hub_web']},
                "worker": {"replicas": target['hub_worker']},
            },
            "eda": {
                "api": {"replicas": target['eda_api']},
                "worker": {"replicas": target['eda_worker']},
                "default_worker": {"replicas": target['eda_default_worker']},
                "activation_worker": {"replicas": target['eda_activation_worker']},
            },
            "lightspeed": {"disabled": target.get('lightspeed_disabled', False)},
            "metrics": {"disabled": target.get('metrics_disabled', False)},
        }
    }


def _build_child_patches(target, aap_name):
    """Build a list of (plural, name, patch) tuples for AAP child CRs."""
    return [
        (const.AAP_CONTROLLER_PLURAL, f"{aap_name}-controller", {
            "spec": {
                "web_replicas": target['controller_web'],
                "task_replicas": target['controller_task'],
            }
        }),
        (const.AAP_HUB_PLURAL, f"{aap_name}-hub", {
            "spec": {
                "api": {"replicas": target['hub_api']},
                "content": {"replicas": target['hub_content']},
                "web": {"replicas": target['hub_web']},
                "worker": {"replicas": target['hub_worker']},
            }
        }),
        (const.AAP_EDA_PLURAL, f"{aap_name}-eda", {
            "spec": {
                "api": {"replicas": target['eda_api']},
                "worker": {"replicas": target['eda_worker']},
                "default_worker": {"replicas": target['eda_default_worker']},
                "activation_worker": {"replicas": target['eda_activation_worker']},
            }
        }),
    ]


def _build_deployment_replicas(target, aap_name):
    """Map deployment names to their target replica counts.

    Sidecar services (hub-redis, eda-event-stream, metrics) are set to 1
    when scaling up, or 0 when all component replicas are zero.
    """
    is_zero = all(target.get(k, 0) == 0 for k in _ZERO_REPLICAS)
    sidecar = 0 if is_zero else 1

    return {
        f"{aap_name}-gateway": target['gateway'],
        f"{aap_name}-controller-task": target['controller_task'],
        f"{aap_name}-controller-web": target['controller_web'],
        f"{aap_name}-hub-api": target['hub_api'],
        f"{aap_name}-hub-content": target['hub_content'],
        f"{aap_name}-hub-web": target['hub_web'],
        f"{aap_name}-hub-worker": target['hub_worker'],
        f"{aap_name}-hub-redis": sidecar,
        f"{aap_name}-eda-api": target['eda_api'],
        f"{aap_name}-eda-default-worker": target['eda_default_worker'],
        f"{aap_name}-eda-activation-worker": target['eda_activation_worker'],
        f"{aap_name}-eda-event-stream": sidecar,
        f"{aap_name}-metrics-web": sidecar,
        f"{aap_name}-metrics-tasks": sidecar,
        f"{aap_name}-metrics-scheduler": sidecar,
    }


def _patch_cr_and_children(helper, namespace, aap_name, aap_patch, child_patches):
    """Patch the AAP CR and its child CRs.  Returns list of patched component names."""
    components = []

    # Patch parent AnsibleAutomationPlatform CR (must exist — no 404 tolerance)
    helper.patch_custom_resource(
        const.AAP_GROUP, const.AAP_VERSION, namespace, const.AAP_PLURAL, aap_name,
        body=aap_patch, patch_type="merge",
    )
    components.append("ansibleautomationplatform/%s" % aap_name)

    # Patch child CRs (may not exist yet — tolerate 404)
    for plural, name, patch in child_patches:
        result = helper.safe_call(
            lambda p=plural, n=name, b=patch: helper.patch_custom_resource(
                const.AAP_GROUP, const.AAP_VERSION, namespace, p, n,
                body=b, patch_type="merge",
            ),
        )
        if result is not None:
            components.append("%s/%s" % (plural, name))

    return components


def _scale_deployments(helper, namespace, deployment_replicas):
    """Scale deployments and the aap-redis statefulset.  Returns list of scaled names."""
    components = []

    for deploy_name, replicas in deployment_replicas.items():
        result = helper.safe_call(
            lambda dn=deploy_name, r=replicas: helper.scale_deployment(namespace, dn, r),
        )
        if result is not None:
            components.append("deployment/%s" % deploy_name)

    # Scale aap-redis statefulset (always 0 when scaling down, 1 when scaling up)
    redis_replicas = 0 if all(v == 0 for v in deployment_replicas.values()) else 1
    result = helper.safe_call(
        lambda: helper.scale_statefulset(namespace, "aap-redis", redis_replicas),
    )
    if result is not None:
        components.append("statefulset/aap-redis")

    return components


def read_aap_cr_file(module, cr_file_path):
    """Read AAP CR YAML file and extract replica counts."""
    if not HAS_YAML:
        module.fail_json(
            msg="PyYAML is required for scale_to=from_cr_file. "
                "Install it with: pip install PyYAML",
        )

    try:
        with open(cr_file_path, 'r') as f:
            cr_data = yaml.safe_load(f)
    except Exception as exc:
        module.fail_json(
            msg="Failed to read AAP CR file: %s" % exc,
            file=cr_file_path,
        )

    return extract_aap_replicas(cr_data.get('spec', {}))


def scale_aap(helper, namespace, aap_name, target, direct_scale):
    """Scale AAP to the given target replica counts.

    Shared by scale_to=zero, from_cr_file, and from_spec modes.
    """
    aap_patch = _build_aap_patch(target)

    # For zero-scale, also disable lightspeed and metrics
    if all(target.get(k, 0) == 0 for k in _ZERO_REPLICAS):
        aap_patch["spec"]["lightspeed"] = {"disabled": True}
        aap_patch["spec"]["metrics"] = {"disabled": True}

    components = _patch_cr_and_children(
        helper, namespace, aap_name, aap_patch, _build_child_patches(target, aap_name),
    )

    if direct_scale:
        components.extend(
            _scale_deployments(helper, namespace, _build_deployment_replicas(target, aap_name))
        )

    return components, target


def patch_idle_aap(helper, namespace, aap_name, idle):
    """Set spec.idle_aap on the AnsibleAutomationPlatform CR."""
    helper.patch_custom_resource(
        const.AAP_GROUP, const.AAP_VERSION, namespace, const.AAP_PLURAL, aap_name,
        body={"spec": {"idle_aap": idle}}, patch_type="merge",
    )
    return ["ansibleautomationplatform/%s" % aap_name], {"idle_aap": idle}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', required=True),
            aap_name=dict(type='str', default='aap'),
            kubeconfig=dict(type='str', default=''),
            context=dict(type='str', default=''),
            scale_to=dict(
                type='str',
                required=True,
                choices=['zero', 'from_cr_file', 'from_spec', 'idle', 'active'],
            ),
            aap_cr_file=dict(type='str', default=''),
            target_replicas=dict(type='dict', default={}),
            direct_deployment_scale=dict(type='bool', default=True),
        ),
        required_if=[
            ('scale_to', 'from_cr_file', ['aap_cr_file']),
            ('scale_to', 'from_spec', ['target_replicas']),
        ],
        supports_check_mode=False,
    )

    helper = create_helper(module)

    namespace = module.params['namespace']
    aap_name = module.params['aap_name']
    scale_to = module.params['scale_to']
    direct_scale = module.params['direct_deployment_scale']

    try:
        if scale_to == 'zero':
            components, replicas = scale_aap(
                helper, namespace, aap_name, dict(_ZERO_REPLICAS), direct_scale,
            )
            message = "AAP components scaled to zero"

        elif scale_to == 'idle':
            components, replicas = patch_idle_aap(helper, namespace, aap_name, True)
            message = "AAP set to idle (idle_aap=true)"

        elif scale_to == 'active':
            components, replicas = patch_idle_aap(helper, namespace, aap_name, False)
            message = "AAP activated (idle_aap=false)"

        elif scale_to == 'from_cr_file':
            target = read_aap_cr_file(module, module.params['aap_cr_file'])
            components, replicas = scale_aap(
                helper, namespace, aap_name, target, direct_scale,
            )
            message = "AAP components scaled from CR file"

        elif scale_to == 'from_spec':
            components, replicas = scale_aap(
                helper, namespace, aap_name,
                module.params['target_replicas'], direct_scale,
            )
            message = "AAP components scaled from spec"

    except Exception as exc:
        module.fail_json(msg="Failed to scale AAP: %s" % exc)

    module.exit_json(
        changed=True,
        components_scaled=components,
        replicas_set=replicas,
        scale_to=scale_to,
        message=message,
    )


if __name__ == '__main__':
    main()
