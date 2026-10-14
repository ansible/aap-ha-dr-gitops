# Configuration

The checked-in inventory describes one pair of two dedicated ROSA hosted clusters.
Copy `examples/aws-rosa-pair/` and keep each filename equal to its record ID.
Unknown fields are rejected.

## Required relationships

| Record | Fields | Rule |
|---|---|---|
| `settings.yaml` | `git.repo_url`, `git.revision` | Git source used by ApplicationSets and generated Applications. |
| `deployment/argocd/environments/*.yaml` (`cluster:`) | `cluster_id`, `provider`, `control_plane_model`, `context`, `management_api_endpoint`, `apps_domain`, `storage_class` | Cluster facts are embedded in each environment; the example uses `rosa` and `hosted`. |
| `deployment/argocd/environments/*.yaml` | `environment_id`, `target_cluster_id`, `namespace`, `installation_name`, `installation_type` | Current values are `aap`, `aap`, and `aap_hadr`. |
| Environment CNPG | `site_name`, `wal_path`, `replication_host`, `peer` | The peer block must match the partner environment. |
| Environment platform | `public_base_url`, `route_url` | The public URL is shared; the route URL is local. |
| Environment ODF | `endpoint`, `partner_endpoint`, `storage_class`, `rgw_zone_name`, `rgw_role` | Endpoints must match the partner records; RGW roles are one primary and one replica. |
| Environment ESO | `role_arn`, `secret_prefix` | IAM trust and secret objects are provisioned outside Git. AWS Secrets Manager region is configured from the infrastructure settings. |
| Environment capacity | `instances`, `data_size`, `wal_size` | Current example uses at least two instances and positive Gi/Ti quantities. |
| `deployment/argocd/pairs/*.yaml` | `pair_id`, `member_environments`, `desired_primary_environment_id` | Both members are included; the desired primary is a member. |

The replica also sets `rgw_realm_source_environment_id` to its partner. `wal_path`
is `s3://cnpg-wal/<site_name>/`. Pair member order maps to operations sites `a` and
`b`; do not reorder it during failover.

## Fixed names and ownership

The example uses namespace `aap`, platform name `aap`, and CNPG name `aap-postgres`.
The repository manages operator subscriptions, platform/database/storage resources,
and ExternalSecret definitions, including the supported day-2 setup jobs. Customers
provide clusters, workers, storage classes, IAM/OIDC trust, secret data, Git access,
DNS, certificates, networking, and traffic routing.

Compute and scheduling defaults are in the reusable manifests, not the inventory.
Review them against cluster capacity before deployment. Monitoring and logging are not included. The exported platform resources include the
supported day-2 setup jobs and their released-image references.

## Local validation

```sh
python3 scripts/validate.py examples/aws-rosa-pair
python3 scripts/validate.py my-deployment --deploy
```

Validation cannot check IAM permissions, secret contents, certificate chains, DNS,
capacity, or running-cluster behavior.
