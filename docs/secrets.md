# Secrets

Inventory contains secret references, not values. Create JSON objects in AWS Secrets
Manager under:

```text
<workloads.eso.secret_prefix>/<object-name>
```

Create the shared objects in both configured regions. Use the same shared encryption
keys and grant the ESO IAM role read and KMS decrypt access. Do not commit secret
values, private keys, exported Kubernetes Secrets, or kubeconfigs.

## Platform and database objects

The exact secret names, Kubernetes target keys, AWS JSON properties, and target Secret
types are defined in the ExternalSecret manifest. Inspect it when preparing the AWS
Secrets Manager objects:

```text
$DEPLOYMENT/overlays/components/secrets-aws/eso-externalsecrets-aap.yaml
```

In that file, each `data[].secretKey` is the Kubernetes Secret key and each
`data[].remoteRef.property` is the required AWS JSON property. `target.template.type`
identifies the resulting Kubernetes Secret type.

The AAP PostgreSQL connection objects use the in-cluster service
`aap-postgres-rw.aap.svc`, port `5432`, and `type: unmanaged`. This hostname is derived
from the CNPG cluster name `aap-postgres` and namespace `aap` defined by this example;
it resolves through the Kubernetes service DNS in the same OpenShift cluster. If you
change the CNPG cluster name or namespace, update the connection objects accordingly.
The passwords must match the roles created by `cnpg-init-sql`.
Keep persistent encryption keys identical across sites.

## CNPG TLS

`cnpg-tls` contains the shared CA and per-site server and replication certificates:

- `ca.crt` and `ca.key` for the shared CA;
- `<site>-server.crt` and `<site>-server.key`; and
- `<site>-replication.crt` and `<site>-replication.key`.

Certificates need the local service names and replication hostname as SANs. The
replication client certificate needs client authentication for `streaming_replica`.
The configured streaming connection uses `sslmode=verify-ca`.

## RGW objects

| Object | Required keys |
|---|---|
| `hub-realm-keys` | `access-key`, `secret-key` |
| `hub-rgw-s3-credentials` | `s3-access-key-id`, `s3-secret-access-key`, `s3-bucket-name`, `s3-endpoint` |

In `hub-rgw-s3-credentials`, set `s3-access-key-id` and `s3-secret-access-key` to
the same values as `access-key` and `secret-key` in `hub-realm-keys`, respectively.

Use bucket `automation-hub-content` and endpoint
`http://rook-ceph-rgw-hub-objectstore.openshift-storage.svc:80`. ESO maps these
credentials to the Barman secret.

The storage administrator must grant the realm user access to the Hub bucket and the
site-specific `cnpg-wal/<site>/*` prefixes. No public-read policy is required.

## ExternalSecret inventory

The exported manifest above is the authoritative inventory of AWS Secrets Manager
objects. Create the object named by each `remoteRef.key` before Argo sync;
create shared objects in every configured region. Do not put secret values in this
repository.

Useful inspection commands:

```bash
# List AWS object keys and required JSON properties
yq '.spec.data[] | {secretKey, key: .remoteRef.key, property: .remoteRef.property}' \
  "$DEPLOYMENT/overlays/components/secrets-aws/eso-externalsecrets-aap.yaml"

# List target Kubernetes Secret names and types
yq '.metadata.name + " -> " + .spec.target.name + " (" + (.spec.target.template.type // "Opaque") + ")"' \
  "$DEPLOYMENT/overlays/components/secrets-aws/eso-externalsecrets-aap.yaml"
```

`postgres-admin-credentials` is created after CNPG becomes ready by the documented
post-CNPG command; it is not supplied by ESO.

## Ownership

- `aap-eso` owns platform, database, and CA ExternalSecrets.
- `aap-cnpg` owns CNPG TLS ExternalSecrets.
- `aap-odf` owns RGW and Barman ExternalSecrets.
- Rook creates Ceph and bucket-claim outputs.
- AAP creates its runtime configuration.

Check every ExternalSecret is Ready before starting its consumer.
