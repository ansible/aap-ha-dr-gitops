#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the aap.hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: argocd_application_update
short_description: Manage fixed ApplicationSet-generated ArgoCD Applications
version_added: "1.0.0"
description:
  - Manages ArgoCD Application custom resource operations during switchover.
  - Can pause/resume automated synchronization to prevent conflicts during manual operations.
  - Triggers hard refresh and sync operations to force reconciliation.
  - Optional module used in normal operations; skipped in disaster recovery mode when ArgoCD is unavailable.
options:
  application_name:
    description: Name of the ArgoCD Application CR.
    type: str
    required: true
  namespace:
    description: Kubernetes namespace containing the Application CR (typically openshift-gitops).
    type: str
    default: "openshift-gitops"
  kubeconfig:
    description: Path to kubeconfig file. If empty, uses default context.
    type: str
    default: ""
  context:
    description: Kubernetes context name to use. If empty, uses current context.
    type: str
    default: ""
  pause_automation:
    description: Set to true to disable automated sync (removes spec.syncPolicy.automated via JSON Patch when possible).
    type: bool
    default: false
  resume_automation:
    description: Set to true to enable automated sync with prune and selfHeal.
    type: bool
    default: false
  trigger_sync:
    description: Whether to trigger a hard refresh and sync operation.
    type: bool
    default: false
  sync_initiator_username:
    description: Username to record in operation.initiatedBy field when triggering sync.
    type: str
    default: "switchover-automation"
author:
  - AAP HA/DR Testing Team
requirements:
  - kubernetes Python client (C(pip install kubernetes>=12.0))
"""

EXAMPLES = r"""
- name: Pause ArgoCD automation during switchover
  aap.hadr_ops.argocd_application_update:
    application_name: aap-cnpg
    namespace: openshift-gitops
    context: prod-cluster-a
    pause_automation: true

- name: Resume ArgoCD Application after pair-state reconciliation
  aap.hadr_ops.argocd_application_update:
    application_name: aap-cnpg
    namespace: openshift-gitops
    context: prod-cluster-b
    resume_automation: true
    trigger_sync: true

- name: Trigger sync only (no path change)
  aap.hadr_ops.argocd_application_update:
    application_name: aap-cnpg
    trigger_sync: true
    sync_initiator_username: manual-operator
"""

RETURN = r"""
automation_paused:
  description: True if automation was paused during this operation.
  type: bool
  returned: when pause_automation was requested
automation_resumed:
  description: True if automation was resumed during this operation.
  type: bool
  returned: when resume_automation was requested
sync_triggered:
  description: True if sync was triggered.
  type: bool
  returned: when trigger_sync was requested
message:
  description: Short status message.
  type: str
  returned: always
"""

import time

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.aap.hadr_ops.plugins.module_utils.k8s_helper import (
    create_helper,
)
from ansible_collections.aap.hadr_ops.plugins.module_utils import constants as const


def _patch(helper, namespace, app_name, body, patch_type="merge"):
    """Shorthand for patching the ArgoCD Application CR."""
    return helper.patch_custom_resource(
        const.ARGOCD_GROUP, const.ARGOCD_VERSION, namespace, const.ARGOCD_PLURAL, app_name,
        body=body, patch_type=patch_type,
    )


def pause_application_automation(module, helper, namespace, app_name):
    """Disable automated sync by removing spec.syncPolicy.automated.

    Uses JSON Patch (remove) first to preserve syncOptions, retry, and
    other syncPolicy siblings.  Falls back to merge-patch null if
    automated was never set (remove would return 422).
    """
    # Try JSON Patch remove first — cleanest approach
    result = helper.safe_call(
        lambda: _patch(helper, namespace, app_name,
                       [{"op": "remove", "path": "/spec/syncPolicy/automated"}],
                       patch_type="json"),
        tolerate_statuses=(404, 422),
    )

    if result is None:
        # automated was never set — disable via merge-patch null
        try:
            _patch(helper, namespace, app_name,
                   {"spec": {"syncPolicy": {"automated": None}}})
        except Exception as exc:
            module.fail_json(msg="Failed to pause Application automation: %s" % exc)

    return True


def resume_application_automation(module, helper, namespace, app_name):
    """Enable automated sync without mutating ApplicationSet-owned source fields."""
    try:
        _patch(helper, namespace, app_name, {
            "spec": {
                "syncPolicy": {
                    "automated": {"prune": True, "selfHeal": True}
                }
            }
        })
    except Exception as exc:
        module.fail_json(msg="Failed to resume Application automation: %s" % exc)

    return True


def trigger_application_sync(module, helper, namespace, app_name, username):
    """Trigger a hard refresh and sync operation."""

    # Step 1: Annotate for hard refresh
    try:
        _patch(helper, namespace, app_name, {
            "metadata": {
                "annotations": {
                    "argocd.argoproj.io/refresh": "hard",
                }
            }
        })
    except Exception as exc:
        module.fail_json(msg="Failed to annotate Application for refresh: %s" % exc)

    # Step 2: Wait for refresh to process
    time.sleep(5)

    # Step 3: Clear stale operation (ignore errors — may not exist)
    helper.safe_call(
        lambda: _patch(helper, namespace, app_name,
                       [{"op": "remove", "path": "/operation"}],
                       patch_type="json"),
        tolerate_statuses=(404, 422),
    )

    # Step 4: Initiate sync
    try:
        _patch(helper, namespace, app_name, {
            "operation": {
                "initiatedBy": {"username": username},
                "sync": {"revision": "HEAD", "prune": True},
            }
        })
    except Exception as exc:
        module.fail_json(msg="Failed to trigger Application sync: %s" % exc)

    return True


def main():
    module = AnsibleModule(
        argument_spec=dict(
            application_name=dict(type='str', required=True),
            namespace=dict(type='str', default='openshift-gitops'),
            kubeconfig=dict(type='str', default=''),
            context=dict(type='str', default=''),
            pause_automation=dict(type='bool', default=False),
            resume_automation=dict(type='bool', default=False),
            trigger_sync=dict(type='bool', default=False),
            sync_initiator_username=dict(type='str', default='switchover-automation'),
        ),
        mutually_exclusive=[
            ('pause_automation', 'resume_automation'),
        ],
        supports_check_mode=False,
    )

    helper = create_helper(module)

    namespace = module.params['namespace']
    app_name = module.params['application_name']

    result = {
        'changed': False,
        'message': 'No operations performed',
    }

    if module.params['pause_automation']:
        pause_application_automation(module, helper, namespace, app_name)
        result['changed'] = True
        result['automation_paused'] = True
        result['message'] = 'ArgoCD automation paused'

    if module.params['resume_automation']:
        resume_application_automation(
            module, helper, namespace, app_name,
        )
        result['changed'] = True
        result['automation_resumed'] = True
        result['message'] = 'ArgoCD automation resumed'

    if module.params['trigger_sync']:
        trigger_application_sync(
            module, helper, namespace, app_name,
            module.params['sync_initiator_username'],
        )
        result['changed'] = True
        result['sync_triggered'] = True
        if not (module.params['pause_automation'] or module.params['resume_automation']):
            result['message'] = 'ArgoCD sync triggered'

    module.exit_json(**result)


if __name__ == '__main__':
    main()
