# Validation

The checks below are offline. No live HA/DR qualification is claimed.

## Local checks

```sh
python3 -m pip install -r requirements.txt
make validate configure render ops-inventory DEPLOYMENT=examples/aws-rosa-pair
```

The example currently passes checks for:

- required and unknown inventory fields, duplicate YAML keys, and pair/peer identity;
- ApplicationSet generation for both clusters and desired-primary states;
- target rendering without unresolved sentinels or duplicate owners; and
- operations inventory identities.

With `operations/requirements.txt` installed, `make ops-check` and Ansible syntax
checks can also be run locally.

These checks do not prove ArgoCD reconciliation, operator compatibility, IAM/OIDC,
secret contents, DNS, capacity, database streaming, RGW replication, traffic
switching, or recovery.

## Before deployment or publication

1. Scan the complete Git history and working tree with an approved secret scanner.
2. Review repository licensing, dependencies, and provenance.
3. Re-run the checks from a clean checkout with the customer inventory.
4. Qualify GitOps bootstrap, readiness, database/WAL replication, RGW replication,
   AAP behavior, traffic switching, and recovery on a dedicated test pair.

Keep credentials, private keys, kubeconfigs, exported Kubernetes Secrets, and customer
endpoints out of Git and its history.
