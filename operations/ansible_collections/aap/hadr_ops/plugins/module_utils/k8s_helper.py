# Copyright: Contributors to the aap.hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Kubernetes Python client helper for aap.hadr_ops custom modules.

Replaces the subprocess+oc pattern used previously.  Every public method
accepts explicit *namespace*, *name*, and optional *timeout* parameters so
callers stay transport-agnostic.

Typical usage inside an Ansible module::

    from ansible_collections.aap.hadr_ops.plugins.module_utils.k8s_helper import (
        create_helper,
    )

    helper = create_helper(module)
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import datetime
import time

from ansible_collections.aap.hadr_ops.plugins.module_utils import constants as const

missing_k8s_reason = None

try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
    from kubernetes.stream import stream as k8s_stream

    HAS_K8S = True
except ImportError:
    HAS_K8S = False
    missing_k8s_reason = (
        "The 'kubernetes' Python package is required by aap.hadr_ops modules. "
        "Install it with: pip install kubernetes>=12.0"
    )

_PATCH_CONTENT_TYPES = {
    "merge": "application/merge-patch+json",
    "json": "application/json-patch+json",
}


def create_helper(module):
    """Create a K8sHelper from an AnsibleModule's params.

    Handles the ``missing_k8s_reason`` check and client initialization,
    calling ``module.fail_json`` on error so individual modules don't
    need to repeat this boilerplate.
    """
    if missing_k8s_reason:
        module.fail_json(msg=missing_k8s_reason)
    try:
        return K8sHelper(
            kubeconfig=module.params.get("kubeconfig") or None,
            context=module.params.get("context") or None,
        )
    except Exception as exc:
        module.fail_json(msg="Failed to initialize Kubernetes client: %s" % exc)


def to_int(val):
    """Convert a CR field value to int, treating None/null as 0."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def to_bool(val):
    """Convert a CR field value to bool."""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1")


def extract_aap_replicas(spec):
    """Extract AAP component replica counts from an AAP CR spec dict.

    Works with both live CR data (from K8s API) and parsed YAML files.
    Returns a flat dict suitable for ``aap_platform_scale`` and
    ``cnpg_cluster_info`` return values.
    """
    return {
        "gateway": to_int(spec.get("api", {}).get("replicas")),
        "controller_web": to_int(spec.get("controller", {}).get("web_replicas")),
        "controller_task": to_int(spec.get("controller", {}).get("task_replicas")),
        "hub_api": to_int(spec.get("hub", {}).get("api", {}).get("replicas")),
        "hub_content": to_int(spec.get("hub", {}).get("content", {}).get("replicas")),
        "hub_web": to_int(spec.get("hub", {}).get("web", {}).get("replicas")),
        "hub_worker": to_int(spec.get("hub", {}).get("worker", {}).get("replicas")),
        "eda_api": to_int(spec.get("eda", {}).get("api", {}).get("replicas")),
        "eda_worker": to_int(spec.get("eda", {}).get("worker", {}).get("replicas")),
        "eda_default_worker": to_int(spec.get("eda", {}).get("default_worker", {}).get("replicas")),
        "eda_activation_worker": to_int(spec.get("eda", {}).get("activation_worker", {}).get("replicas")),
        "metrics_disabled": to_bool(spec.get("metrics", {}).get("disabled")),
        "lightspeed_disabled": to_bool(spec.get("lightspeed", {}).get("disabled")),
    }


class K8sHelper:
    """Thin wrapper around the Kubernetes Python client.

    Each instance is bound to a single kubeconfig/context pair.  Modules
    that operate on two clusters (e.g. switchover) should create two
    helper instances.
    """

    def __init__(self, kubeconfig=None, context=None):
        if not HAS_K8S:
            raise RuntimeError(missing_k8s_reason)

        api_client = self._build_client(kubeconfig, context)
        self._custom = k8s_client.CustomObjectsApi(api_client)
        self._core = k8s_client.CoreV1Api(api_client)
        self._apps = k8s_client.AppsV1Api(api_client)

    @staticmethod
    def _build_client(kubeconfig, context):
        """Load kubeconfig and return an ApiClient."""
        kwargs = {}
        if kubeconfig:
            kwargs["config_file"] = kubeconfig
        if context:
            kwargs["context"] = context
        return k8s_config.new_client_from_config(**kwargs)

    # ------------------------------------------------------------------
    # Private helpers — reduce repeated 404-handling boilerplate
    # ------------------------------------------------------------------

    @staticmethod
    def safe_call(func, not_found_result=None, tolerate_statuses=(404,)):
        """Call *func* and return its result.

        If the API returns an HTTP status listed in *tolerate_statuses*,
        return *not_found_result* instead of raising.  All other
        ``ApiException`` errors are re-raised.

        Default tolerates 404 (Not Found).  Pass ``(404, 422)`` to also
        tolerate Unprocessable Entity (e.g. JSON Patch remove on a
        missing path).
        """
        try:
            return func()
        except ApiException as exc:
            if exc.status in tolerate_statuses:
                return not_found_result
            raise

    def _delete_by_label(self, list_func, delete_func, namespace, label_selector,
                         delete_options=None):
        """List resources via *list_func*, delete each via *delete_func*.

        Ignores 404 on individual deletes (resource may have been cleaned
        up between list and delete).  Returns count of resources targeted.
        """
        items = list_func(namespace, label_selector=label_selector)
        for item in items:
            self.safe_call(
                lambda i=item: delete_func(i.metadata.name, namespace,
                                           **({"body": delete_options} if delete_options else {})),
                not_found_result=None,
            )
        return len(items)

    # ------------------------------------------------------------------
    # Custom resource operations
    # ------------------------------------------------------------------

    def get_custom_resource(self, group, version, namespace, plural, name):
        """Return a single namespaced custom resource as a dict.

        Raises ``ApiException`` on failure (404 if not found, etc.).
        """
        return self._custom.get_namespaced_custom_object(
            group=group, version=version, namespace=namespace,
            plural=plural, name=name,
        )

    def patch_custom_resource(self, group, version, namespace, plural, name,
                              body, patch_type="merge"):
        """Patch a namespaced custom resource.

        *patch_type* must be ``"merge"`` (JSON Merge Patch, RFC 7386) or
        ``"json"`` (JSON Patch, RFC 6902).

        Never use strategic-merge for CRDs (CNPG, AAP, ArgoCD) — it is
        only valid for native Kubernetes resources.
        """
        content_type = _PATCH_CONTENT_TYPES.get(patch_type)
        if content_type is None:
            raise ValueError(
                "patch_type must be 'merge' or 'json', got %r" % patch_type
            )

        # Set content type via header — compatible with all kubernetes client versions
        # (older versions don't support the _content_type kwarg)
        old_default = self._custom.api_client.default_headers.get('Content-Type')
        self._custom.api_client.default_headers['Content-Type'] = content_type
        try:
            return self._custom.patch_namespaced_custom_object(
                group=group, version=version, namespace=namespace,
                plural=plural, name=name, body=body,
            )
        finally:
            if old_default is not None:
                self._custom.api_client.default_headers['Content-Type'] = old_default
            else:
                self._custom.api_client.default_headers.pop('Content-Type', None)

    def delete_custom_resource(self, group, version, namespace, plural, name,
                               wait=False, timeout=120):
        """Delete a namespaced custom resource.

        When *wait* is True, polls until the resource is gone or *timeout*
        seconds elapse.  Returns True if deleted (or already absent),
        False if still present after timeout.
        """
        result = self.safe_call(
            lambda: self._custom.delete_namespaced_custom_object(
                group=group, version=version, namespace=namespace,
                plural=plural, name=name,
            ),
            not_found_result=True,
        )
        if result is True:
            return True

        if not wait:
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.custom_resource_exists(group, version, namespace, plural, name):
                return True
            time.sleep(5)
        return False

    def custom_resource_exists(self, group, version, namespace, plural, name):
        """Return True if the custom resource exists, False otherwise."""
        result = self.safe_call(
            lambda: self.get_custom_resource(group, version, namespace, plural, name),
            not_found_result=False,
        )
        return result is not False

    # ------------------------------------------------------------------
    # Core resource operations
    # ------------------------------------------------------------------

    def get_secret(self, namespace, name):
        """Return a Secret object, or None if not found."""
        return self.safe_call(
            lambda: self._core.read_namespaced_secret(name, namespace),
        )

    def delete_secret(self, namespace, name):
        """Delete a Secret.  Returns True if deleted, False if not found."""
        result = self.safe_call(
            lambda: self._core.delete_namespaced_secret(name, namespace),
            not_found_result=False,
        )
        return result is not False

    def list_pods(self, namespace, label_selector=None, field_selector=None):
        """List pods matching the given selectors.  Returns a list of V1Pod."""
        kwargs = {"namespace": namespace}
        if label_selector:
            kwargs["label_selector"] = label_selector
        if field_selector:
            kwargs["field_selector"] = field_selector
        return self._core.list_namespaced_pod(**kwargs).items

    def delete_pods(self, namespace, label_selector, force=False):
        """Delete pods matching *label_selector*.

        When *force* is True, uses grace_period_seconds=0.
        Returns the count of pods targeted for deletion.
        """
        opts = k8s_client.V1DeleteOptions(grace_period_seconds=0) if force else None
        return self._delete_by_label(
            self.list_pods, self._core.delete_namespaced_pod,
            namespace, label_selector, delete_options=opts,
        )

    def list_pvcs(self, namespace, label_selector=None):
        """List PVCs matching the given label selector."""
        kwargs = {"namespace": namespace}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return self._core.list_namespaced_persistent_volume_claim(**kwargs).items

    def delete_pvcs(self, namespace, label_selector):
        """Delete PVCs matching *label_selector*.  Returns count deleted."""
        return self._delete_by_label(
            self.list_pvcs,
            self._core.delete_namespaced_persistent_volume_claim,
            namespace, label_selector,
        )

    # ------------------------------------------------------------------
    # Apps / workload operations
    # ------------------------------------------------------------------

    def get_deployment(self, namespace, name):
        """Return a Deployment object, or None if not found."""
        return self.safe_call(
            lambda: self._apps.read_namespaced_deployment(name, namespace),
        )

    def _scale_resource(self, patch_func, namespace, name, replicas):
        """Scale a Deployment or StatefulSet via its /scale subresource."""
        return patch_func(name, namespace, {"spec": {"replicas": replicas}})

    def scale_deployment(self, namespace, name, replicas):
        """Scale a Deployment to *replicas*."""
        return self._scale_resource(
            self._apps.patch_namespaced_deployment_scale,
            namespace, name, replicas,
        )

    def scale_statefulset(self, namespace, name, replicas):
        """Scale a StatefulSet to *replicas*."""
        return self._scale_resource(
            self._apps.patch_namespaced_stateful_set_scale,
            namespace, name, replicas,
        )

    def restart_deployment(self, namespace, name):
        """Restart a Deployment by patching the pod template annotation.

        Equivalent to ``kubectl rollout restart deployment/<name>``.
        """
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now,
                        }
                    }
                }
            }
        }
        return self._apps.patch_namespaced_deployment(name, namespace, body)

    def list_deployments(self, namespace, label_selector=None):
        """List Deployments matching the given label selector."""
        kwargs = {"namespace": namespace}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return self._apps.list_namespaced_deployment(**kwargs).items

    def is_deployment_ready(self, namespace, name):
        """Check if a Deployment has all replicas ready."""
        deploy = self.get_deployment(namespace, name)
        if deploy is None:
            return False
        desired = deploy.spec.replicas or 0
        ready = deploy.status.ready_replicas or 0
        return ready >= desired and desired > 0

    # ------------------------------------------------------------------
    # Pod exec
    # ------------------------------------------------------------------

    def exec_in_pod(self, namespace, pod_name, command, container=None):
        """Execute a command in a running pod.

        Returns a dict with ``stdout``, ``stderr``, and ``returncode``.
        *command* should be a list of strings.
        """
        kwargs = {
            "name": pod_name,
            "namespace": namespace,
            "command": command,
            "stderr": True,
            "stdout": True,
            "stdin": False,
            "tty": False,
        }
        if container:
            kwargs["container"] = container

        resp = k8s_stream(
            self._core.connect_get_namespaced_pod_exec,
            **kwargs,
        )

        return {
            "stdout": resp if isinstance(resp, str) else str(resp),
            "stderr": "",
            "returncode": 0,
        }

    def find_pod(self, namespace, label_selector, field_selector=None):
        """Find the first pod matching selectors.

        Returns the pod name as a string, or None if no pod matches.
        """
        pods = self.list_pods(namespace, label_selector=label_selector,
                              field_selector=field_selector)
        if pods:
            return pods[0].metadata.name
        return None

    # ------------------------------------------------------------------
    # Route (OpenShift)
    # ------------------------------------------------------------------

    def get_route_host(self, namespace, name):
        """Return the spec.host of an OpenShift Route, or None if not found."""
        route = self.safe_call(
            lambda: self._custom.get_namespaced_custom_object(
                group=const.ROUTE_GROUP, version=const.ROUTE_VERSION,
                namespace=namespace, plural=const.ROUTE_PLURAL, name=name,
            ),
        )
        if route is None:
            return None
        return route.get("spec", {}).get("host")
