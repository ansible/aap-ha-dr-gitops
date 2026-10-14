# Copyright: Contributors to the aap.hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""CRD coordinate constants for Kubernetes custom resources used by aap.hadr_ops.

Import these instead of hardcoding API group/version/plural strings in
modules and roles.  Example::

    from ansible_collections.aap.hadr_ops.plugins.module_utils.constants import (
        CNPG_GROUP, CNPG_VERSION, CNPG_PLURAL,
    )
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

# CloudNativePG
CNPG_GROUP = "postgresql.cnpg.io"
CNPG_VERSION = "v1"
CNPG_PLURAL = "clusters"

# Ansible Automation Platform
AAP_GROUP = "aap.ansible.com"
AAP_VERSION = "v1alpha1"
AAP_PLURAL = "ansibleautomationplatforms"
AAP_CONTROLLER_PLURAL = "automationcontrollers"
AAP_HUB_PLURAL = "automationhubs"
AAP_EDA_PLURAL = "edas"

# ArgoCD
ARGOCD_GROUP = "argoproj.io"
ARGOCD_VERSION = "v1alpha1"
ARGOCD_PLURAL = "applications"

# OpenShift Routes
ROUTE_GROUP = "route.openshift.io"
ROUTE_VERSION = "v1"
ROUTE_PLURAL = "routes"
