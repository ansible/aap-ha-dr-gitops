# AAP HA/DR example

This repository is a GitOps reference for Ansible Automation Platform on two
OpenShift clusters.

The example uses AWS/ROSA, AAP 2.7, CloudNativePG, External Secrets Operator with
AWS Secrets Manager, and ODF Ceph RGW. It contains reusable manifests, ApplicationSets,
a synthetic two-cluster inventory, bootstrap helpers, and an Ansible operations
collection.

**Live deployment qualification is pending.** Local rendering is not proof of HA/DR
behavior.

## Topology

```mermaid
flowchart LR
    G[Git inventory and ApplicationSets] --> A[ArgoCD on cluster A]
    G --> B[ArgoCD on cluster B]
    S[AWS Secrets Manager] --> E[ESO on both clusters]
    A --> AP[AAP active]
    B --> AS[AAP standby]
    AP --> P[CNPG primary]
    AS --> R[CNPG replica]
    P --> R
    AP --> RGW1[Local Ceph RGW]
    AS --> RGW2[Local Ceph RGW]
    RGW1 <-->|RGW multisite| RGW2
```

The desired primary is stored in the pair inventory. RGW roles are fixed and do
not change with CNPG/AAP promotion. A switchover requires the operations workflow;
changing the desired-primary field alone is not sufficient.

## Quick start

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp -R examples/aws-rosa-pair my-deployment
# edit my-deployment/settings.yaml,
# my-deployment/deployment/argocd/environments/*.yaml, and
# my-deployment/deployment/argocd/pairs/*.yaml
make validate configure render ops-inventory DEPLOYMENT=my-deployment
```

Publish the configured Git revision before asking ArgoCD to sync it. See
[getting started](docs/getting-started.md) for the deployment order.

## Deployment flow

1. Prepare two dedicated ROSA clusters and their AWS, network, storage, DNS, and
   certificate prerequisites. See [infrastructure requirements](docs/infrastructure-requirements.md).
2. Copy the sample pair, configure the Git revision and both cluster and pair
   records, then run `make validate configure render ops-inventory DEPLOYMENT=my-deployment`
   and `make deployment-inputs DEPLOYMENT=my-deployment`. Review and publish
   the generated files.
3. Bootstrap OpenShift GitOps on both clusters. Apply ESO on both clusters and
   configure its AWS identity.
4. Apply ODF on the fixed RGW primary, then the replica, and configure RGW
   multisite. Apply CNPG on the initial database primary, then its replica, and
   create the AAP metrics Secret on both clusters after CNPG is ready.
5. Apply the AAP platform layer on both clusters. Configure external traffic
   routing, license AAP, and run the operations checks and read-only preflight.

The [getting started guide](docs/getting-started.md) has the commands and
readiness gates for each step. Use the [operations guide](docs/operations.md)
for planned switchover and disaster recovery.

## Documentation

- [Getting started](docs/getting-started.md): prerequisites, local commands, and bootstrap order.
- [Configuration](docs/configuration.md): inventory fields and fixed names.
- [Secrets](docs/secrets.md): secret backend objects and required keys.
- [Operations](docs/operations.md): preflight, switchover, and recovery guidance.
- [Validation](docs/validation.md): local checks and known limits.

The example keeps the namespace and resource names `aap` and `aap-postgres`. Other
names, storage backends, secret backends, providers, and additional workloads are
not covered by the current validation.
