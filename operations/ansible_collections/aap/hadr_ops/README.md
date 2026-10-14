# aap.hadr_ops

Operational Ansible collection for AAP HA/DR with distributed CloudNativePG.
Runtime behavior is preserved; five check-label lines have scanner annotations and usage text points to generated inventory.
License declaration: GPL-3.0-or-later (see `galaxy.yml`).

Use the example repository's `docs/operations.md` for installation, generated
inventory and preflight instructions. `make ops-inventory DEPLOYMENT=my-deployment`
provides the pair/environment identities required by `config_loader`. Older
examples that supply only contexts and site IDs are insufficient.

Entry points under `playbooks/`:

- `aap_preflight.yml`: assess health; keep `autofix: false` for observation.
- `aap_graceful_switchover.yml`: planned role transition.
- `aap_disaster_recovery.yml`: promote surviving site after fencing failed primary.
- `aap_restore_replication.yml`: rebuild/rejoin after recovery.
- `aap_backup_restore.yml`: explicit backup/restore operations.
- `rgw_multisite_setup.yml`: initialize dedicated RGW topology.
- `ceph_recovery.yml`: explicit storage recovery.

Mutating playbooks require review of their parameters and operational prerequisites.
The collection does not publish Git changes or manage the customer's global traffic
entry point. Reconcile pair state in Git during the documented operations handoff.
