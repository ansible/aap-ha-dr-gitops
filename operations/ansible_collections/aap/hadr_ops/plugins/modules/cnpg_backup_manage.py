#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the hadr_ops Ansible collection
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: cnpg_backup_manage
short_description: Manage CloudNativePG backup and PITR restore operations
version_added: "1.0.0"
description:
  - Triggers on-demand CNPG backups by creating a Backup CR.
  - Lists existing backups from the cluster.
  - Initiates point-in-time recovery by patching the CNPG Cluster CR bootstrap config.
  - Performs full cluster restore by deleting and recreating from backup.
  - Polls backup status until completion or timeout.
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
  oc_binary:
    description: OpenShift/Kubernetes CLI executable (oc or kubectl).
    type: str
    default: "oc"
  operation:
    description: Backup operation to perform.
    type: str
    required: true
    choices: ['backup', 'list', 'status', 'restore_pitr', 'restore_full']
  backup_name:
    description:
      - Name for the Backup CR. Auto-generated if empty (for C(backup) operation).
      - Required for C(status) operation to check a specific backup.
      - Optional for C(restore_full) - if empty, uses latest backup.
    type: str
    default: ""
  target_time:
    description: >
      ISO 8601 timestamp for point-in-time recovery (required for C(restore_pitr)).
      Example: "2026-05-27T12:00:00Z"
    type: str
    default: ""
  recovery_source:
    description: >
      Override recovery source cluster for cross-cluster restore.
      If empty, uses the cluster's own replica.self value.
      Used with C(restore_pitr) and C(restore_full) operations.
    type: str
    default: ""
  s3_bucket:
    description: >
      S3 bucket name for cross-bucket restore (C(restore_full) only).
      Required when restoring from a bucket that is not in externalClusters.
      Example: "my-backup-bucket"
    type: str
    default: ""
  s3_path:
    description: >
      S3 path within bucket for cross-bucket restore (C(restore_full) only).
      Example: "cnpg/aap-postgres/v1"
    type: str
    default: ""
  s3_endpoint:
    description: >
      S3 endpoint URL for cross-bucket restore (C(restore_full) only).
      Example: "https://s3.amazonaws.com"
    type: str
    default: ""
  s3_credentials_secret:
    description: >
      Name of Kubernetes secret containing S3 credentials for cross-bucket restore.
      Secret must exist in the target namespace and contain ACCESS_KEY_ID and SECRET_ACCESS_KEY keys.
      Used with C(restore_full) when restoring from a new bucket.
    type: str
    default: ""
  wait:
    description: Whether to wait for backup completion (C(backup) operation only).
    type: bool
    default: true
  wait_timeout:
    description: Seconds to wait for backup completion.
    type: int
    default: 600
  poll_interval:
    description: Seconds between status polls when waiting.
    type: int
    default: 10
author:
  - AAP HA/DR Testing Team
requirements:
  - OpenShift CLI (C(oc)) or kubectl
"""

EXAMPLES = r"""
- name: Trigger on-demand backup and wait for completion
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: backup
    wait: true
    wait_timeout: 600
  register: backup_result

- name: Trigger backup without waiting
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: backup
    wait: false
  register: backup_result

- name: List all backups for the cluster
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: list
  register: backup_list

- name: Check status of a specific backup
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: status
    backup_name: aap-postgres-manual-20260527-120000
  register: backup_status

- name: Restore database to point-in-time
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: restore_pitr
    target_time: "2026-05-27T12:00:00Z"
  register: restore_result

- name: Full cluster restore from latest backup
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: restore_full
  register: restore_result

- name: Full cluster restore from specific backup
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-a
    operation: restore_full
    backup_name: aap-postgres-manual-20260527-120000
  register: restore_result

- name: Full cluster restore from another cluster's backup
  aap.hadr_ops.cnpg_backup_manage:
    namespace: aap
    cluster_name: aap-postgres
    context: prod-cluster-b
    operation: restore_full
    recovery_source: dc-east
  register: restore_result
"""

RETURN = r"""
operation:
  description: The operation that was performed.
  type: str
  returned: always
backup_name:
  description: Name of the Backup CR (for backup and status operations).
  type: str
  returned: when operation is backup or status
backup_phase:
  description: Current phase of the backup (e.g., "completed", "running", "failed").
  type: str
  returned: when operation is backup or status
backups:
  description: List of backup objects (for list operation).
  type: list
  elements: dict
  returned: when operation is list
  contains:
    name:
      description: Backup CR name.
      type: str
    phase:
      description: Backup phase.
      type: str
    started_at:
      description: Backup start timestamp.
      type: str
    completed_at:
      description: Backup completion timestamp.
      type: str
    method:
      description: Backup method (barmanObjectStore, volumeSnapshot).
      type: str
    size:
      description: Backup size in human-readable format.
      type: str
target_time:
  description: Target recovery time (for restore_pitr operation).
  type: str
  returned: when operation is restore_pitr
recovery_source:
  description: Name of the source cluster used for recovery.
  type: str
  returned: when operation is restore_pitr or restore_full
server_name_old:
  description: Original serverName before restore_full.
  type: str
  returned: when operation is restore_full
server_name_new:
  description: New serverName after auto-bump (restore_full).
  type: str
  returned: when operation is restore_full
cluster_ready:
  description: Whether cluster became healthy after restore_full.
  type: bool
  returned: when operation is restore_full
duration_seconds:
  description: Elapsed time for the operation in seconds.
  type: float
  returned: always
message:
  description: Short status message.
  type: str
  returned: always
warnings:
  description: Warning messages.
  type: list
  elements: str
  returned: when applicable
"""

import copy
import json
import subprocess
import time
import re
from typing import Optional

from ansible.module_utils.basic import AnsibleModule


def _run_oc(module, args, timeout):
    """Execute oc/kubectl command with timeout handling."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"
    except Exception as e:
        return 1, "", str(e)


def _build_cmd(oc_binary, kubeconfig, context):
    """Build base oc command with auth flags."""
    cmd = [oc_binary]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])
    if context:
        cmd.extend(["--context", context])
    return cmd


def _generate_backup_name(cluster_name):
    """Generate a timestamped backup name."""
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return "{0}-manual-{1}".format(cluster_name, ts)


def trigger_backup(module, namespace, cluster_name, backup_name, kubeconfig, context, oc_binary, wait, wait_timeout, poll_interval):
    """Create a CNPG Backup CR and optionally wait for completion."""
    start_time = time.perf_counter()

    if not backup_name:
        backup_name = _generate_backup_name(cluster_name)

    backup_cr = {
        "apiVersion": "postgresql.cnpg.io/v1",
        "kind": "Backup",
        "metadata": {
            "name": backup_name,
            "namespace": namespace,
            "labels": {
                "cnpg.io/cluster": cluster_name
            }
        },
        "spec": {
            "cluster": {
                "name": cluster_name
            }
        }
    }

    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend(["create", "-f", "-"])

    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(backup_cr),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        module.fail_json(msg="Timeout creating Backup CR", backup_name=backup_name)
    except Exception as e:
        module.fail_json(msg="Failed to create Backup CR: {0}".format(str(e)), backup_name=backup_name)

    if proc.returncode != 0:
        module.fail_json(
            msg="Failed to create Backup CR",
            rc=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            backup_name=backup_name
        )

    if not wait:
        duration = time.perf_counter() - start_time
        return {
            'changed': True,
            'operation': 'backup',
            'backup_name': backup_name,
            'backup_phase': 'pending',
            'duration_seconds': duration,
            'message': 'Backup CR created (not waiting for completion)'
        }

    phase = _wait_for_backup(module, namespace, backup_name, kubeconfig, context, oc_binary, wait_timeout, poll_interval)

    duration = time.perf_counter() - start_time

    if phase != "completed":
        module.fail_json(
            msg="Backup did not complete within timeout",
            backup_name=backup_name,
            backup_phase=phase,
            duration_seconds=duration,
            wait_timeout=wait_timeout
        )

    return {
        'changed': True,
        'operation': 'backup',
        'backup_name': backup_name,
        'backup_phase': phase,
        'duration_seconds': duration,
        'message': 'Backup completed successfully'
    }


def _wait_for_backup(module, namespace, backup_name, kubeconfig, context, oc_binary, timeout, poll_interval):
    """Poll backup status until completed, failed, or timeout."""
    deadline = time.time() + timeout
    phase = "unknown"

    while time.time() < deadline:
        cmd = _build_cmd(oc_binary, kubeconfig, context)
        cmd.extend([
            "get", "backup", backup_name,
            "-n", namespace,
            "-o", "jsonpath={.status.phase}"
        ])

        rc, stdout, stderr = _run_oc(module, cmd, timeout=30)

        if rc == 0 and stdout.strip():
            phase = stdout.strip().lower()
            if phase in ("completed", "failed"):
                return phase

        time.sleep(poll_interval)

    return phase


def list_backups(module, namespace, cluster_name, kubeconfig, context, oc_binary):
    """List all Backup CRs for the given cluster."""
    start_time = time.perf_counter()

    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "get", "backup",
        "-n", namespace,
        "-l", "cnpg.io/cluster={0}".format(cluster_name),
        "-o", "json"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)

    # Fall through if label query failed OR returned an empty list
    # (CNPG 1.29+ doesn't label Backup CRs with cnpg.io/cluster)
    items_found = False
    if rc == 0 and stdout.strip():
        try:
            items_found = len(json.loads(stdout).get("items", [])) > 0
        except (json.JSONDecodeError, TypeError):
            pass

    if rc != 0 or not items_found:
        cmd = _build_cmd(oc_binary, kubeconfig, context)
        cmd.extend([
            "get", "backup",
            "-n", namespace,
            "-o", "json"
        ])
        rc, stdout, stderr = _run_oc(module, cmd, timeout=30)

    if rc != 0:
        module.fail_json(
            msg="Failed to list backups",
            rc=rc,
            stdout=stdout,
            stderr=stderr
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        module.fail_json(msg="Failed to parse backup list JSON", stdout=stdout[:1000])

    backups = []
    for item in data.get("items", []):
        spec_cluster = item.get("spec", {}).get("cluster", {}).get("name", "")
        if spec_cluster and spec_cluster != cluster_name:
            continue

        status = item.get("status", {})
        backups.append({
            "name": item.get("metadata", {}).get("name", ""),
            "phase": status.get("phase", "unknown"),
            "started_at": status.get("startedAt", ""),
            "completed_at": status.get("stoppedAt", ""),
            "method": item.get("spec", {}).get("method", "barmanObjectStore"),
            "size": _format_backup_size(status),
        })

    backups.sort(key=lambda b: b.get("started_at", ""), reverse=True)

    duration = time.perf_counter() - start_time

    return {
        'changed': False,
        'operation': 'list',
        'backups': backups,
        'duration_seconds': duration,
        'message': 'Found {0} backup(s)'.format(len(backups))
    }


def _format_backup_size(status):
    """Extract human-readable backup size from status."""
    size_bytes = status.get("size", 0)
    if not size_bytes:
        return "unknown"
    try:
        size_bytes = int(size_bytes)
    except (ValueError, TypeError):
        return str(size_bytes)

    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size_bytes) < 1024.0:
            return "{0:.1f} {1}".format(size_bytes, unit)
        size_bytes /= 1024.0
    return "{0:.1f} PiB".format(size_bytes)


def get_backup_status(module, namespace, backup_name, kubeconfig, context, oc_binary):
    """Get detailed status of a specific backup."""
    start_time = time.perf_counter()

    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "get", "backup", backup_name,
        "-n", namespace,
        "-o", "json"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)

    if rc != 0:
        module.fail_json(
            msg="Failed to get backup {0}".format(backup_name),
            rc=rc,
            stderr=stderr
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        module.fail_json(msg="Failed to parse backup JSON", stdout=stdout[:1000])

    status = data.get("status", {})
    duration = time.perf_counter() - start_time

    return {
        'changed': False,
        'operation': 'status',
        'backup_name': backup_name,
        'backup_phase': status.get("phase", "unknown"),
        'backup_details': {
            'started_at': status.get("startedAt", ""),
            'completed_at': status.get("stoppedAt", ""),
            'size': _format_backup_size(status),
            'begin_wal': status.get("beginWal", ""),
            'end_wal': status.get("endWal", ""),
            'begin_lsn': status.get("beginLSN", ""),
            'end_lsn': status.get("endLSN", ""),
            'server_name': status.get("serverName", ""),
            'timeline_id': status.get("instanceID", {}).get("ContainerID", ""),
        },
        'duration_seconds': duration,
        'message': 'Backup {0} is {1}'.format(backup_name, status.get("phase", "unknown"))
    }


def restore_pitr(module, namespace, cluster_name, target_time, kubeconfig, context, oc_binary, recovery_source_override=''):
    """
    Initiate PITR by patching the CNPG Cluster to use recovery bootstrap.

    This fences (shuts down) the current cluster and bootstraps a new one
    from the Barman object store with a recovery target time.
    """
    start_time = time.perf_counter()

    # Step 1: Get current cluster spec to extract barmanObjectStore config
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "get", "cluster", cluster_name,
        "-n", namespace,
        "-o", "json"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)
    if rc != 0:
        module.fail_json(
            msg="Failed to get cluster {0}".format(cluster_name),
            rc=rc,
            stderr=stderr
        )

    try:
        cluster_data = json.loads(stdout)
    except json.JSONDecodeError:
        module.fail_json(msg="Failed to parse cluster JSON")

    spec = cluster_data.get("spec", {})
    backup_config = spec.get("backup", {}).get("barmanObjectStore", {})
    replica_self = spec.get("replica", {}).get("self", "")

    if not backup_config:
        module.fail_json(msg="No barmanObjectStore backup configuration found on cluster {0}".format(cluster_name))

    # Step 2: Find the matching externalCluster for recovery source
    lookup_name = recovery_source_override if recovery_source_override else replica_self
    external_clusters = spec.get("externalClusters", [])
    recovery_source = None
    for ext in external_clusters:
        if ext.get("name") == lookup_name:
            recovery_source = ext
            break

    if not recovery_source:
        lookup_reason = "override" if recovery_source_override else "replica.self"
        module.fail_json(
            msg="No externalCluster entry found for {0}={1}".format(lookup_reason, lookup_name),
            external_clusters=[e.get("name") for e in external_clusters]
        )

    source_name = recovery_source.get("name", "")

    # Step 3: Fence the cluster (set instances to 0 via annotation)
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "annotate", "cluster", cluster_name,
        "-n", namespace,
        "cnpg.io/hibernation=on",
        "--overwrite"
    ])
    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)
    if rc != 0:
        module.fail_json(
            msg="Failed to hibernate cluster for PITR",
            rc=rc,
            stderr=stderr
        )

    # Step 4: Replace bootstrap with recovery mode (removes initdb)
    recovery_patch = [
        {
            "op": "replace",
            "path": "/spec/bootstrap",
            "value": {
                "recovery": {
                    "database": "postgres",
                    "owner": "postgres",
                    "source": source_name,
                    "recoveryTarget": {
                        "targetTime": target_time
                    }
                }
            }
        }
    ]

    for attempt in range(3):
        cmd = _build_cmd(oc_binary, kubeconfig, context)
        cmd.extend([
            "patch", "cluster", cluster_name,
            "-n", namespace,
            "--type=json",
            "-p", json.dumps(recovery_patch)
        ])

        rc, stdout, stderr = _run_oc(module, cmd, timeout=60)
        if rc == 0:
            break
        if attempt < 2:
            time.sleep(5)

    if rc != 0:
        module.fail_json(
            msg="Failed to patch cluster for PITR recovery",
            rc=rc,
            stdout=stdout,
            stderr=stderr
        )

    duration = time.perf_counter() - start_time

    return {
        'changed': True,
        'operation': 'restore_pitr',
        'target_time': target_time,
        'recovery_source': source_name,
        'duration_seconds': duration,
        'warnings': [
            "Cluster has been hibernated and patched for PITR to {0}".format(target_time),
            "Remove the cnpg.io/hibernation annotation and delete pods to start recovery",
            "After recovery completes, restore the original bootstrap configuration",
            "Verify data integrity before re-enabling replication"
        ],
        'message': 'PITR recovery initiated to {0} from source {1}'.format(target_time, source_name)
    }


def _get_bumped_server_name(
        current_server_name: str,
        pattern: Optional[str]=None,
    ) -> str:
    """
    Uses the current server name to parse a version number to bump.

    Expects a pattern like `aap-postgres` or `aap-postgres-v1`.
    The `pattern` parameter should be used to pass different patterns,
    but it is not implemented yet.
    Returns the new full server"""

    match = re.search(r'-v(\d+)$', current_server_name)
    if match:
        new_version = int(match.group(1)) + 1
        new_server_name = re.sub(r'-v\d+$', '-v{0}'.format(new_version), current_server_name)
    else:
        # No version suffix, add -v2
        new_server_name = "{0}-v2".format(current_server_name)

    return new_server_name


def restore_full(module, namespace, cluster_name, backup_name, kubeconfig, context, oc_binary,
                 recovery_source_override='',
                 s3_bucket='', s3_path='', s3_endpoint='', s3_credentials_secret='',
                 auto_bump_servername=False):
    """
    Full cluster restore from backup by deleting and recreating the CNPG cluster.

    Steps:
    1. Get current cluster spec
    2. Delete the CNPG Cluster CR
    3. Delete all PVCs in the namespace
    4. Delete orphaned Released PVs (Ceph RBD)
    5. Recreate the cluster with recovery bootstrap (handles cross-bucket credentials)
    6. Auto-bump serverName to avoid barman conflicts (if restoring from same bucket)

    This is DESTRUCTIVE - it completely rebuilds the cluster from backup.

    Supports three restore scenarios:
    - Same-cluster restore: uses existing barmanObjectStore config
    - Cross-cluster restore (pre-configured): uses existing externalCluster entry
    - Cross-bucket restore (new): injects externalCluster with provided S3 credentials
    """
    start_time = time.perf_counter()
    warnings = []

    # ────────────────────────────────────────────────────────────────
    # STEP 1: Get current cluster spec to preserve configuration
    # ────────────────────────────────────────────────────────────────
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "get", "cluster", cluster_name,
        "-n", namespace,
        "-o", "json"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)
    if rc != 0:
        module.fail_json(
            msg="Failed to get cluster {0}".format(cluster_name),
            rc=rc,
            stderr=stderr
        )

    try:
        cluster_data = json.loads(stdout)
    except json.JSONDecodeError:
        module.fail_json(msg="Failed to parse cluster JSON")

    spec = cluster_data.get("spec", {})
    backup_config = spec.get("backup", {}).get("barmanObjectStore", {})
    replica_self = spec.get("replica", {}).get("self", "")

    if not backup_config:
        module.fail_json(msg="No barmanObjectStore backup configuration found on cluster {0}".format(cluster_name))

    # ────────────────────────────────────────────────────────────────
    # Determine recovery source and handle credentials
    # ────────────────────────────────────────────────────────────────
    lookup_name = recovery_source_override if recovery_source_override else replica_self
    external_clusters = spec.get("externalClusters", [])
    recovery_source = None
    needs_credential_injection = False

    # Try to find existing externalCluster entry
    for ext in external_clusters:
        if ext.get("name") == lookup_name:
            recovery_source = ext
            break

    # If not found, check if we can inject credentials
    if not recovery_source and recovery_source_override:
        # Cross-bucket restore scenario - check if S3 params provided
        if s3_bucket and s3_credentials_secret:
            needs_credential_injection = True
            warnings.append("externalCluster '{0}' not found - will inject dynamically with provided S3 credentials".format(lookup_name))
        else:
            # Neither pre-configured nor have params to inject
            lookup_reason = "override" if recovery_source_override else "replica.self"
            module.fail_json(
                msg="No externalCluster entry found for {0}={1}, and S3 credentials not provided. ".format(lookup_reason, lookup_name) +
                    "Either add the externalCluster to the CNPG cluster spec, or provide s3_bucket, s3_path, s3_endpoint, and s3_credentials_secret parameters.",
                external_clusters=[e.get("name") for e in external_clusters],
                hint="For cross-bucket restore, pass: s3_bucket=<bucket> s3_path=<path> s3_endpoint=<url> s3_credentials_secret=<secret-name>"
            )
    elif not recovery_source:
        # Restoring from self, but replica.self not in externalClusters (unexpected)
        module.fail_json(
            msg="No externalCluster entry found for replica.self={0}".format(replica_self),
            external_clusters=[e.get("name") for e in external_clusters]
        )

    source_name = lookup_name  # Use the lookup name as source_name

    # ────────────────────────────────────────────────────────────────
    # Determine if serverName bump is needed
    # ────────────────────────────────────────────────────────────────
    # serverName must be bumped when the destination bucket is "dirty"
    # (contains WAL files for current serverName from previous cluster).
    #
    # restore_full typically means:
    #  - We had a cluster before (we're restoring it)
    #  - Our destination bucket has old WAL files (dirty)
    #  - New timeline won't match old WAL → "Expected empty archive" error
    #
    # Only skip bump when:
    #  - User explicitly disables (auto_bump_servername=false)
    #  - Example: fresh install being initialized from backup (rare)

    current_server_name = backup_config.get("serverName", cluster_name)
    new_server_name = current_server_name

    # Always bump by default - restore_full implies dirty bucket
    should_bump = auto_bump_servername

    if should_bump:
        new_server_name = _get_bumped_server_name(current_server_name)

        warnings.append("serverName bumped {0} → {1} to avoid WAL conflicts with existing archives (dirty bucket)".format(
            current_server_name, new_server_name))

    # ────────────────────────────────────────────────────────────────
    # STEP 2: Delete the CNPG Cluster CR
    # ────────────────────────────────────────────────────────────────
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "delete", "cluster", cluster_name,
        "-n", namespace,
        "--wait=true",
        "--timeout=120s"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=150)
    if rc != 0:
        warnings.append("Failed to delete cluster CR (may not exist): {0}".format(stderr))

    # ────────────────────────────────────────────────────────────────
    # STEP 3: Delete all PVCs with cnpg.io/cluster label
    # ────────────────────────────────────────────────────────────────
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "delete", "pvc",
        "-n", namespace,
        "-l", "cnpg.io/cluster={0}".format(cluster_name),
        "--wait=true",
        "--timeout=120s"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=150)
    if rc != 0:
        warnings.append("Failed to delete PVCs (may not exist): {0}".format(stderr))

    # ────────────────────────────────────────────────────────────────
    # STEP 4: Delete orphaned Released PVs
    # ────────────────────────────────────────────────────────────────
    # Get all PVs in Released state that were bound to our cluster's PVCs
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "get", "pv",
        "-o", "json"
    ])

    rc, stdout, stderr = _run_oc(module, cmd, timeout=30)
    if rc == 0:
        try:
            pv_data = json.loads(stdout)
            orphaned_pvs = []

            for pv in pv_data.get("items", []):
                status = pv.get("status", {})
                claim_ref = pv.get("spec", {}).get("claimRef", {})

                # Check if PV is Released and was bound to a PVC in our namespace with cnpg label
                if (status.get("phase") == "Released" and
                    claim_ref.get("namespace") == namespace and
                    "cnpg" in claim_ref.get("name", "").lower()):
                    orphaned_pvs.append(pv.get("metadata", {}).get("name"))

            # Delete each orphaned PV
            for pv_name in orphaned_pvs:
                cmd = _build_cmd(oc_binary, kubeconfig, context)
                cmd.extend(["delete", "pv", pv_name, "--wait=false"])
                rc, _, stderr = _run_oc(module, cmd, timeout=30)
                if rc != 0:
                    warnings.append("Failed to delete orphaned PV {0}: {1}".format(pv_name, stderr))

            if orphaned_pvs:
                warnings.append("Deleted {0} orphaned PV(s): {1}".format(
                    len(orphaned_pvs), ", ".join(orphaned_pvs)))

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            warnings.append("Failed to parse PV list for cleanup: {0}".format(str(e)))

    # ────────────────────────────────────────────────────────────────
    # STEP 5: Recreate the cluster with recovery bootstrap
    # ────────────────────────────────────────────────────────────────
    # Build the new cluster spec with recovery bootstrap
    new_spec = copy.deepcopy(spec)

    # Update serverName in backup config if bumped
    if new_server_name != current_server_name:
        if "backup" not in new_spec:
            new_spec["backup"] = {}
        if "barmanObjectStore" not in new_spec["backup"]:
            new_spec["backup"]["barmanObjectStore"] = {}
        new_spec["backup"]["barmanObjectStore"]["serverName"] = new_server_name

    # ────────────────────────────────────────────────────────────────
    # Inject externalCluster credentials if needed (cross-bucket restore)
    # ────────────────────────────────────────────────────────────────
    if needs_credential_injection:
        # Build the externalCluster entry with provided S3 credentials
        # This enables restore from buckets not pre-configured in the cluster spec
        # (e.g., upgrade rollback from AAP 2.4 backup when running AAP 2.6)

        # Construct the destination path
        destination_path = "s3://{0}".format(s3_bucket)
        if s3_path:
            destination_path = "{0}/{1}".format(destination_path, s3_path.strip('/'))

        ext_cluster_entry = {
            "name": source_name,
            "barmanObjectStore": {
                "destinationPath": destination_path,
                "s3Credentials": {
                    "accessKeyId": {
                        "name": s3_credentials_secret,
                        "key": "ACCESS_KEY_ID"
                    },
                    "secretAccessKey": {
                        "name": s3_credentials_secret,
                        "key": "SECRET_ACCESS_KEY"
                    }
                }
            }
        }

        # Add endpoint URL if provided
        if s3_endpoint:
            ext_cluster_entry["barmanObjectStore"]["endpointURL"] = s3_endpoint

        # Ensure externalClusters list exists
        if "externalClusters" not in new_spec:
            new_spec["externalClusters"] = []

        # Remove any existing entry with the same name (shouldn't exist, but be safe)
        new_spec["externalClusters"] = [
            e for e in new_spec["externalClusters"]
            if e.get("name") != source_name
        ]

        # Add the new entry
        new_spec["externalClusters"].append(ext_cluster_entry)

        warnings.append("Injected externalCluster '{0}' with S3 credentials from secret '{1}' (bucket: {2})".format(
            source_name, s3_credentials_secret, destination_path))

    # ────────────────────────────────────────────────────────────────
    # Fix externalCluster serverName when bumping
    # ────────────────────────────────────────────────────────────────
    # When serverName is bumped (aap-postgres → aap-postgres-v2):
    #  - New cluster writes WALs to: s3://path/aap-postgres-v2/
    #  - But backups are still at: s3://path/aap-postgres/
    # We must tell the externalCluster to look in the OLD path.
    if new_server_name != current_server_name:
        # Find the externalCluster entry we're recovering from
        if "externalClusters" in new_spec:
            for ext in new_spec["externalClusters"]:
                if ext.get("name") == source_name:
                    # Set serverName to the OLD value so recovery finds backups
                    if "barmanObjectStore" in ext:
                        ext["barmanObjectStore"]["serverName"] = current_server_name
                        warnings.append("Set externalCluster '{0}' serverName to '{1}' (backups location)".format(
                            source_name, current_server_name))
                    break

    # Replace bootstrap with recovery mode
    recovery_bootstrap = {
        "recovery": {
            "database": "postgres",
            "owner": "postgres",
            "source": source_name
        }
    }

    # If specific backup requested, use it; otherwise use latest
    if backup_name:
        recovery_bootstrap["recovery"]["backup"] = {
            "name": backup_name
        }

    new_spec["bootstrap"] = recovery_bootstrap

    # Build the full cluster CR — strip server-managed fields from the old metadata
    old_metadata = cluster_data.get("metadata", {})
    new_metadata = {
        "name": cluster_name,
        "namespace": namespace,
    }
    for key in ("labels", "annotations"):
        if key in old_metadata:
            new_metadata[key] = copy.deepcopy(old_metadata[key])

    # Remove operator-managed annotations that would conflict on re-create
    managed_annotation_prefixes = ("kubectl.kubernetes.io/", "cnpg.io/")
    if "annotations" in new_metadata:
        new_metadata["annotations"] = {
            k: v for k, v in new_metadata["annotations"].items()
            if not k.startswith(managed_annotation_prefixes)
        }

    cluster_cr = {
        "apiVersion": "postgresql.cnpg.io/v1",
        "kind": "Cluster",
        "metadata": new_metadata,
        "spec": new_spec,
    }

    # Create the cluster via stdin (avoids shell escaping issues)
    cmd = _build_cmd(oc_binary, kubeconfig, context)
    cmd.extend([
        "apply", "-f", "-"
    ])

    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(cluster_cr),
            capture_output=True,
            text=True,
            timeout=60,
            check=False
        )

        if proc.returncode != 0:
            module.fail_json(
                msg="Failed to recreate cluster with recovery bootstrap",
                rc=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr
            )

    except subprocess.TimeoutExpired:
        module.fail_json(msg="Timed out recreating cluster")
    except Exception as e:
        module.fail_json(msg="Failed to recreate cluster: {0}".format(str(e)))

    # ────────────────────────────────────────────────────────────────
    # STEP 6: Wait for cluster to become healthy
    # ────────────────────────────────────────────────────────────────
    # Note: This is a basic wait for cluster creation. The calling playbook
    # should use cnpg_health_check role for comprehensive health validation.

    max_wait = 300  # 5 minutes
    poll_interval = 10
    deadline = time.time() + max_wait
    cluster_ready = False

    while time.time() < deadline:
        cmd = _build_cmd(oc_binary, kubeconfig, context)
        cmd.extend([
            "get", "cluster", cluster_name,
            "-n", namespace,
            "-o", "jsonpath={.status.phase}"
        ])

        rc, stdout, stderr = _run_oc(module, cmd, timeout=30)

        if rc == 0 and stdout.strip():
            phase = stdout.strip().lower()
            if "healthy" in phase or "cluster in healthy state" in phase:
                cluster_ready = True
                break

        time.sleep(poll_interval)

    if not cluster_ready:
        warnings.append("Cluster recreation initiated but not fully healthy within {0}s. Phase: {1}".format(
            max_wait, stdout.strip() if rc == 0 else "unknown"))

    duration = time.perf_counter() - start_time

    return {
        'changed': True,
        'operation': 'restore_full',
        'cluster_name': cluster_name,
        'backup_name': backup_name if backup_name else 'latest',
        'recovery_source': source_name,
        'server_name_old': current_server_name,
        'server_name_new': new_server_name,
        'cluster_ready': cluster_ready,
        'duration_seconds': duration,
        'warnings': warnings,
        'message': 'Full restore initiated from {0} (serverName: {1})'.format(
            backup_name if backup_name else 'latest backup',
            new_server_name
        )
    }

def main():
    module = AnsibleModule(
        argument_spec=dict(
            namespace=dict(type='str', required=True),
            cluster_name=dict(type='str', required=True),
            kubeconfig=dict(type='str', default=''),
            context=dict(type='str', default=''),
            oc_binary=dict(type='str', default='oc'),
            operation=dict(
                type='str',
                required=True,
                choices=['backup', 'list', 'status', 'restore_pitr', 'restore_full']
            ),
            backup_name=dict(type='str', default=''),
            target_time=dict(type='str', default=''),
            recovery_source=dict(type='str', default=''),
            s3_bucket=dict(type='str', default=''),
            s3_path=dict(type='str', default=''),
            s3_endpoint=dict(type='str', default=''),
            s3_credentials_secret=dict(type='str', default=''),
            auto_bump_servername=dict(type='bool', default=False),
            wait=dict(type='bool', default=True),
            wait_timeout=dict(type='int', default=600),
            poll_interval=dict(type='int', default=10),
        ),
        required_if=[
            ('operation', 'status', ['backup_name']),
            ('operation', 'restore_pitr', ['target_time']),
        ],
        supports_check_mode=False,
    )

    namespace = module.params['namespace']
    cluster_name = module.params['cluster_name']
    kubeconfig = module.params['kubeconfig']
    context = module.params['context']
    oc_binary = module.params['oc_binary']
    operation = module.params['operation']

    if operation == 'backup':
        result = trigger_backup(
            module, namespace, cluster_name,
            module.params['backup_name'],
            kubeconfig, context, oc_binary,
            module.params['wait'],
            module.params['wait_timeout'],
            module.params['poll_interval']
        )
    elif operation == 'list':
        result = list_backups(
            module, namespace, cluster_name,
            kubeconfig, context, oc_binary
        )
    elif operation == 'status':
        result = get_backup_status(
            module, namespace,
            module.params['backup_name'],
            kubeconfig, context, oc_binary
        )
    elif operation == 'restore_pitr':
        result = restore_pitr(
            module, namespace, cluster_name,
            module.params['target_time'],
            kubeconfig, context, oc_binary,
            recovery_source_override=module.params['recovery_source']
        )
    elif operation == 'restore_full':
        result = restore_full(
            module, namespace, cluster_name,
            module.params['backup_name'],
            kubeconfig, context, oc_binary,
            recovery_source_override=module.params['recovery_source'],
            s3_bucket=module.params['s3_bucket'],
            s3_path=module.params['s3_path'],
            s3_endpoint=module.params['s3_endpoint'],
            s3_credentials_secret=module.params['s3_credentials_secret'],
            auto_bump_servername=module.params['auto_bump_servername']
        )

    module.exit_json(**result)


if __name__ == '__main__':
    main()
