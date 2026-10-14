# Getting started

This guide covers the checked-in example. It does not claim live deployment or
recovery qualification.

Commands in **Check and render** are offline. Commands in **Bootstrap** and
**Operations** can change or inspect clusters; use the intended `DEPLOYMENT` and
`CLUSTER` values.

## Requirements

See [Infrastructure and Argo CD Requirements](infrastructure-requirements.md) for cluster capacity, node labels/taints, IAM/OIDC, storage, DNS, and Argo CD bootstrap requirements.

Local rendering requires Python 3.10+, Go 1.18+, Git, Make, and kubectl with
Kustomize component support. Live operations also require `oc`, Ansible, two
kubeconfig contexts, and access to both clusters.

The deployment requires two dedicated ROSA hosted clusters with:

- ODF-capable workers, an existing CSI storage class, and enough CPU, memory, and
  storage for the checked-in manifests;
- network access for database replication and RGW HTTPS routes;
- DNS and certificates for replication and application routes;
- access to the released AAP, CNPG, ESO, and ODF images/catalogs; and
- AWS IAM/OIDC trust for the ESO service account.

Keep credentials, private keys, kubeconfigs, and exported Kubernetes Secrets outside
Git. Before applying ESO or the root Argo Applications, create every AWS Secrets
Manager object listed in [secrets](secrets.md), using the exact prefix and JSON keys
shown there. The repository provides the ExternalSecret manifests and remote-key list; it does
not create the AWS values.

## Copy and configure

```sh
cp -R examples/aws-rosa-pair my-deployment
```

Rename each copied record file so its filename matches its ID. For example,
`deployment/argocd/environments/example-pair-a.yaml` becomes
`deployment/argocd/environments/<environment-id>.yaml`, and the same rule applies
to `deployment/argocd/pairs/`. Cluster facts remain in each environment's
`cluster:` block. The IDs referenced by `target_cluster_id`, `member_environments`,
and `peer` must match those filenames and each other.

Edit:

- `settings.yaml`: the HTTPS Git URL and revision that ArgoCD will read;
- `deployment/argocd/environments/*.yaml`: cluster facts, AAP URL, routes, sites, RGW endpoints, AWS region/role, and the existing secret prefix; the prefix comes from the secret-management owner; and
- `deployment/argocd/pairs/*.yaml`: members and the initial desired primary.

The fixed resource names are `aap`, `aap-postgres`, and the documented RGW objects.
The exported platform resources include the supported day-2 setup jobs and use
released images. Use the [configuration reference](configuration.md) for field
relationships.

## Check and render

```sh
python3 -m pip install -r requirements.txt
make validate configure render ops-inventory DEPLOYMENT=my-deployment
make deployment-inputs DEPLOYMENT=my-deployment
```

`validate` checks the inventory. `configure` writes the per-cluster bootstrap files
and removes obsolete generated cluster directories. `render` builds the resources.
`ops-inventory` creates the Ansible inventory. These commands are offline.

Review both generated clusters and both desired-primary states. `deployment-inputs`
rejects synthetic domains and the zero AWS account ID. Commit and push the inventory
and generated bootstrap files to the Git revision in `settings.yaml` before syncing
ArgoCD. For a private repository, configure its credentials in both ArgoCD instances.
ArgoCD cannot use unpushed local changes.

## Bootstrap

Set these from the inventory before running cluster commands:

```sh
DEPLOYMENT=my-deployment
CLUSTER_A=cluster-id-a
CLUSTER_B=cluster-id-b
RGW_PRIMARY=cluster-with-rgw-primary
RGW_REPLICA=cluster-with-rgw-replica
PRIMARY=cluster-with-initial-desired-primary
REPLICA=the-other-cluster
```

Install GitOps on both clusters:

```sh
for cluster in "$CLUSTER_A" "$CLUSTER_B"; do
  make gitops-install DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster"
  make gitops-rbac DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster"
done
```

The example bootstrap runs the Argo CD application controller as `cluster-admin` so it can reliably create namespaces, operator resources, CRDs, RBAC, storage, routes, and other cluster-scoped HADR resources. If a least-privilege policy is required, replace the example RBAC and pre-create any resources that Argo CD is not permitted to create.

Before applying ESO, confirm the required AWS Secrets Manager objects and ESO IAM/KMS permissions are present. Then wait on both clusters for the GitOps operator CSV to reach
`Succeeded`, the `applicationsets.argoproj.io` CRD to become `Established`, and the
default `openshift-gitops` ArgoCD instance and its controllers to become Ready.
`make gitops-install` only applies the Subscription; it does not wait for these
readiness conditions.

Apply ESO on both clusters. Wait for the ESO operator and service account after the
layer is applied, then annotate its IAM role and wait for the readiness gate:

```sh
for cluster in "$CLUSTER_A" "$CLUSTER_B"; do
  make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster" LAYER=eso
  # Wait for the external-secrets service account to exist.
  make eso-identity DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster"
  make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster" LAYER=eso
done
```

Install the operations collection before the RGW setup command:

```sh
python3 -m pip install -r operations/requirements.txt
make ops-install
```

Apply ODF to the RGW primary first, then the replica:

```sh
make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$RGW_PRIMARY" LAYER=odf
make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$RGW_PRIMARY" LAYER=odf
make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$RGW_REPLICA" LAYER=odf
make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$RGW_REPLICA" LAYER=odf
```

After both ODF layers are ready, run the RGW setup. This mutates the dedicated RGW
realm and zone configuration; do not run it against an existing shared realm:

```sh
make rgw-setup DEPLOYMENT="$DEPLOYMENT"
```

Apply CNPG to the initial primary first, then the replica:

```sh
make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$PRIMARY" LAYER=cnpg
make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$PRIMARY" LAYER=cnpg
make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$REPLICA" LAYER=cnpg
make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$REPLICA" LAYER=cnpg
```

After CNPG is Ready on each cluster, create the AAP metrics workaround Secret. CNPG creates the source credential; this target copies its password into the Secret name required by the AAP 2.7 MetricsService (AAP-70491):

```sh
for cluster in "$CLUSTER_A" "$CLUSTER_B"; do
  make postgres-admin-secret DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster"
done
```

The Secret is generated from the live CNPG credential and must not be committed to Git.

Apply the platform layer to both clusters and check readiness:

```sh
for cluster in "$CLUSTER_A" "$CLUSTER_B"; do
  make apply-layer DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster" LAYER=platform
  make ready DEPLOYMENT="$DEPLOYMENT" CLUSTER="$cluster" LAYER=platform
done
```

Configure traffic routing, license AAP, and verify the running pair before using it.

## Operations

```sh
make ops-check DEPLOYMENT="$DEPLOYMENT"
# only after both clusters and replication are ready
make preflight DEPLOYMENT="$DEPLOYMENT"
```

Preflight is read-only by default. Review [operations](operations.md) before any
switchover, recovery, RGW mutation, restore, or cleanup operation.
