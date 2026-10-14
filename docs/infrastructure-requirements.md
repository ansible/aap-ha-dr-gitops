# Infrastructure and Argo CD Requirements

This document describes prerequisites for deploying the two-cluster HADR example. The repository contains sanitized manifests and does not provision the underlying OpenShift infrastructure, identity, DNS, or secret values.

## Cluster requirements

Prepare two dedicated ROSA hosted OpenShift clusters represented by `example-a` and `example-b`.

Each cluster requires:

- OpenShift 4.x with cluster-admin access for the initial bootstrap.
- OpenShift GitOps operator availability from the default Red Hat catalog.
- AAP 2.7 operator availability from the default `redhat-operators` catalog, channel `stable-2.7`.
- CloudNativePG, External Secrets Operator, and ODF operator catalogs available.
- ODF-capable workers and sufficient CPU, memory, and local/network storage.
- The `gp3-csi` storage class, or the storage class named in the environment record.
- Network connectivity for RGW replication and application routes.
- DNS and certificates for the AAP, RGW, and CNPG replication endpoints.
- AWS IAM/OIDC trust for the ESO service account.
- Access to the Git repository configured in `settings.yaml` from both Argo CD instances.

## Required node labels and taints

The rendered manifests assume these scheduling contracts:

### CNPG nodes

Provide nodes suitable for PostgreSQL and, if tainted, use:

```text
taint: dedicated=postgres:NoSchedule
```

The CNPG resources tolerate this taint and spread across:

```text
topology.kubernetes.io/zone
```

### AAP execution nodes

AAP execution workloads use:

```text
label: dedicated=executionplane
taint: dedicated=executionplane:NoSchedule
```

The execution-plane configuration must tolerate the matching taint.

### ODF nodes

Provide the worker/storage layout required by ODF for the selected ROSA topology. ODF placement, AZ distribution, device classes, and failure-domain capacity must be validated against the cluster before sync.

Do not remove or rename these labels/taints without updating the corresponding AAP and CNPG scheduling configuration.

## AWS and external services

Provision before Argo sync:

- IAM/OIDC trust for ESO.
- Secrets Manager values under the configured sanitized/example prefix.
- Route53 permissions and hosted zone access if External DNS is enabled.
- DNS records or delegated zones for application and RGW endpoints.
- TLS certificates and private keys outside Git.
- Network routes/firewalls permitting cross-cluster PostgreSQL/RGW traffic.

## Argo CD bootstrap sequence

Run the bootstrap manifests against each cluster before applying the generated root Applications:

```bash
oc apply -f bootstrap/gitops-operator.yaml
# Wait for OpenShift GitOps and the openshift-gitops Argo CD instance.
oc apply -f bootstrap/gitops-rbac.yaml
oc apply -f bootstrap/gitops-rbac-policy.yaml
oc apply -f bootstrap/example-team-group.yaml
```

Set `DEPLOYMENT` to the configured pair directory, then apply the generated root
Applications for the target clusters:

```bash
DEPLOYMENT=examples/aws-rosa-pair
oc apply -f "$DEPLOYMENT/argocd/aap-example-a.yaml"
oc apply -f "$DEPLOYMENT/argocd/aap-example-b.yaml"
```

The root Applications point at the repository and revision in the generated manifest. Push the repository before applying them; Argo CD cannot sync unpushed local changes.

## Argo CD permissions

The example bootstrap grants the Argo CD application controller `cluster-admin`. This is intentional: the HADR deployment creates namespaces, operator subscriptions, cluster-scoped CRDs/resources, RBAC, storage resources, routes, and other cluster-scoped objects. Cluster-admin provides reliable access across the full ordered installation and failover workflow.

Organizations that require least-privilege Argo CD access must provide their own replacement RBAC policy. They may need to create namespaces, CRDs, operator prerequisites, and other cluster-scoped resources in advance, then grant Argo CD only the verbs and resources required by their approved deployment. Do not apply the example cluster-admin binding in that model.

## Post-sync actions

After CNPG is Ready on each cluster:

```bash
make postgres-admin-secret CLUSTER=<cluster-context>
```

After both ODF resources are Ready, run the documented RGW multisite setup. These operations use live credentials and are intentionally not represented as static secret manifests.
