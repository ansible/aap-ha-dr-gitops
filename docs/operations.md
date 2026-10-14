# Operations

Install the collection dependencies and generate an inventory from the same
configuration used by GitOps:

```sh
python3 -m pip install -r operations/requirements.txt
make ops-install
make ops-inventory DEPLOYMENT=my-deployment
make ops-check DEPLOYMENT=my-deployment
```

`ops-check` loads configuration without contacting a cluster. The generated inventory
maps pair members to contexts, environments, CNPG sites, and ApplicationSet labels.

## Preflight

After both clusters are deployed and replication is established:

```sh
make preflight DEPLOYMENT=my-deployment
```

Preflight is read-only by default and runs with automatic repair disabled. It checks
reachability, storage, CNPG state, replication, AAP state, and ArgoCD state. It does
not prove that recovery will succeed.

## Planned switchover

1. Run preflight and confirm the target by CNPG `site_name`.
2. Pause the relevant ArgoCD Applications and coordinate runtime promotion.
3. Fence or demote the old primary as required by the selected playbook.
4. Update only `desired_primary_environment_id` in Git and publish the revision.
5. Wait for ApplicationSet reconciliation and verify pair/environment/role labels.
6. Resume reconciliation, switch traffic, and run preflight again.

Do not reorder pair members or change RGW roles for a CNPG/AAP switchover.

## Disaster recovery and restore

Disaster recovery requires fencing the failed primary before force promotion. Restore
and replication-rebuild playbooks can delete or recreate data; read their confirmation
parameters and prerequisites before running them. Run mutating operations only under
an approved change procedure with a tested backup and recovery plan.

The collection does not publish Git changes or manage global traffic routing.
