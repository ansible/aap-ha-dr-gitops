"""Strict, offline contract for one customer HA/DR deployment directory."""
from pathlib import Path
import re
from urllib.parse import urlparse
import os

import yaml

ROOT = Path(os.environ.get("HADR_REPO_ROOT", Path(__file__).resolve().parents[2]))
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]|[a-z0-9]")
HOST = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
SECRET_KEYS = {"password", "private_key", "access_key", "secret_access_key", "token"}


class InventoryError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise InventoryError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_yaml(path):
    try:
        return yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise InventoryError(f"cannot read {path}: {exc}") from exc


def check(condition, message):
    if not condition:
        raise InventoryError(message)


def fields(value, required, where, optional=()):
    check(isinstance(value, dict), f"{where}: expected mapping")
    check(set(required) <= value.keys(), f"{where}: missing {set(required) - value.keys()}")
    check(value.keys() <= set(required) | set(optional), f"{where}: unknown fields {value.keys() - set(required) - set(optional)}")


def string(value, where):
    check(isinstance(value, str) and bool(value.strip()), f"{where}: expected nonempty string")
    check("MUST_BE_SET" not in value and "{{" not in value, f"{where}: unresolved placeholder")


def identifier(value, where):
    string(value, where)
    check(ID.fullmatch(value) is not None, f"{where}: invalid identifier")


def url(value, where):
    string(value, where)
    parsed = urlparse(value)
    check(parsed.scheme == "https" and bool(parsed.hostname), f"{where}: expected HTTPS URL")
    check(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
          f"{where}: URL must not contain authentication, query, or fragment")


def scan_values(value, where="inventory", deploy=False):
    if isinstance(value, dict):
        for key, child in value.items():
            check(isinstance(key, str), f"{where}: keys must be strings")
            check(key.lower() not in SECRET_KEYS, f"{where}: secret-bearing field {key} is not allowed")
            scan_values(child, f"{where}.{key}", deploy)
    elif isinstance(value, list):
        for child in value:
            scan_values(child, where, deploy)
    elif isinstance(value, str):
        check("MUST_BE_SET" not in value, f"{where}: unresolved sentinel")
        if deploy:
            check(not any(s in value for s in ("example.com", "example.invalid", "000000000000")),
                  f"{where}: synthetic value must be replaced before deployment")


def load_inventory(directory, deploy=False, pair_id=None):
    directory = Path(directory).resolve()
    check(directory.is_relative_to(ROOT), "deployment must be inside this repository")
    settings_path = directory / "settings.yaml"
    if settings_path.exists():
        settings = read_yaml(settings_path)
    else:
        settings = {"schema_version": 1, "git": {
            "repo_url": os.environ.get("HADR_REPO_URL", "https://github.com/ansible-automation-platform/aap-hadr.git"),
            "revision": os.environ.get("HADR_REVISION", "devel"),
        }}
    fields(settings, {"schema_version", "git"}, "settings")
    check(type(settings["schema_version"]) is int and settings["schema_version"] == 1, "unsupported settings schema")
    fields(settings["git"], {"repo_url", "revision"}, "git")
    url(settings["git"]["repo_url"], "git.repo_url")
    string(settings["git"]["revision"], "git.revision")
    records = {}
    data_root = directory
    if not (data_root / "environments").exists() and (directory / "deployment" / "argocd").exists():
        data_root = directory / "deployment" / "argocd"
    for category, key in (("clusters", "cluster_id"), ("environments", "environment_id"), ("pairs", "pair_id")):
        records[category] = {}
        for file in sorted((data_root / category).glob("*.yaml")):
            record = read_yaml(file)
            if category == "clusters" and (not isinstance(record, dict) or key not in record):
                continue
            if category == "clusters":
                record.pop("schema_version", None)
            check(isinstance(record, dict) and key in record, f"{file}: missing {key}")
            identity = record[key]
            identifier(identity, key)
            check(identity == file.stem, f"{file}: filename must match {key}")
            check(identity not in records[category], f"duplicate {key}")
            if category != "clusters":
                check(type(record.get("schema_version")) is int and record["schema_version"] == 1, f"{file}: unsupported schema")
            records[category][identity] = record
    clusters, envs, pairs = (records[x] for x in ("clusters", "environments", "pairs"))
    if pair_id:
        pairs = {pair_id: pairs[pair_id]}
        members = set(pairs[pair_id]["member_environments"])
        envs = {key: value for key, value in envs.items() if key in members}
        clusters = {key: value for key, value in clusters.items() if key in {e["target_cluster_id"] for e in envs.values()}}
        records.update(pairs=pairs, environments=envs, clusters=clusters)
    if not envs:
        env_dir = data_root / "environments"
        for file in sorted(env_dir.glob("*.yaml")):
            record = read_yaml(file)
            records["environments"][record["environment_id"]] = record
        envs = records["environments"]
    if not pairs:
        pair_dir = data_root / "pairs"
        for file in sorted(pair_dir.glob("*.yaml")):
            record = read_yaml(file)
            records["pairs"][record["pair_id"]] = record
        pairs = records["pairs"]
    if not clusters:
        for env in envs.values():
            cluster = dict(env.get("cluster", {}))
            cluster.setdefault("cluster_id", env["target_cluster_id"])
            clusters[cluster["cluster_id"]] = cluster
    vars_path = Path(os.environ.get("HADR_CLUSTERS_FILE", ROOT / "vars" / "clusters.yml"))
    if not clusters or any("provider" not in c or "context" not in c for c in clusters.values()):
        if vars_path.exists():
            topology = yaml.safe_load(vars_path.read_text()).get("cluster_sets", {})
            for env in envs.values():
                cluster_id = env["target_cluster_id"]
                set_id = "02" if "02" in cluster_id else "01"
                key = "a" if cluster_id.endswith("-a") else "b"
                source = topology.get(set_id, {}).get("clusters", {}).get(key, {})
                clusters[cluster_id] = {
                    "cluster_id": cluster_id,
                    "provider": "rosa",
                    "control_plane_model": "hosted",
                    "context": source.get("context", cluster_id),
                    "management_api_endpoint": "https://api.example.invalid",
                    "apps_domain": topology.get(set_id, {}).get("slo_apps_domain", "example.invalid"),
                    "storage_class": env["workloads"]["cnpg"]["storage_class"],
                    **clusters.get(cluster_id, {}),
                }
    check(len(clusters) == 2 and len(envs) == 2 and len(pairs) == 1, "one deployment must contain two clusters, two environments, and one pair")
    for c in clusters.values():
        fields(c, {"cluster_id", "provider", "control_plane_model", "management_api_endpoint", "apps_domain", "storage_class", "context"}, "cluster")
        check(c["provider"] == "rosa" and c["control_plane_model"] == "hosted", "first example supports ROSA hosted control planes")
        url(c["management_api_endpoint"], "management_api_endpoint")
        check(isinstance(c["apps_domain"], str) and HOST.fullmatch(c["apps_domain"]), "invalid apps_domain")
        string(c["context"], "context")
        identifier(c["storage_class"], "storage_class")
    for key in ("context", "management_api_endpoint", "apps_domain"):
        check(len({c[key] for c in clusters.values()}) == 2, f"clusters must have distinct {key}")
    for e in envs.values():
        fields(e, {"schema_version", "environment_id", "target_cluster_id", "namespace", "installation_name", "installation_type", "rgw_zone_name", "rgw_role", "workloads"}, "environment", {"rgw_realm_source_environment_id", "cluster", "certificates", "infrastructure", "retention"})
        if "cluster" in e:
            fields(e["cluster"], {"cluster_id", "provider", "control_plane_model", "management_api_endpoint", "apps_domain", "storage_class", "context"}, "environment.cluster")
            e["cluster"]["cluster_id"] = e["target_cluster_id"]
        if "certificates" in e:
            fields(e["certificates"], {"server", "server_key", "replication", "replication_key"}, "certificates")
        if "retention" in e:
            fields(e["retention"], {"days", "interval_hours"}, "retention")
        if "infrastructure" in e:
            fields(e["infrastructure"], {"aws_account_id", "aws_region", "secrets_manager_region", "terraform_workspace", "external_dns"}, "infrastructure")
            fields(e["infrastructure"]["external_dns"], {"enabled", "name", "role_arn"}, "infrastructure.external_dns")
        check(e["target_cluster_id"] in clusters, "unknown target cluster")
        check(e["namespace"] == e["installation_name"] == "aap" and e["installation_type"] == "aap_hadr", "resource names are fixed to aap")
        identifier(e["rgw_zone_name"], "rgw_zone_name")
        check(e["rgw_role"] in ("primary", "replica"), "invalid RGW role")
        w = e["workloads"]
        fields(w, {"cnpg", "platform", "odf", "eso"}, "workloads", {"logging", "observability"})
        fields(w["platform"], {"public_base_url", "route_url"}, "platform", {"hop_node_ips", "receptor_hosts"})
        for k in ("public_base_url", "route_url"):
            url(w["platform"][k], k)
        fields(w["cnpg"], {"site_name", "wal_path", "replication_host", "storage_class", "peer"}, "cnpg", {"data_size", "wal_size", "instances"})
        n = w["cnpg"]
        identifier(n["site_name"], "site_name")
        check(isinstance(n["replication_host"], str) and HOST.fullmatch(n["replication_host"]), "invalid replication_host")
        check(n["wal_path"] == f"s3://cnpg-wal/{n['site_name']}/", "WAL path must use the cnpg-wal bucket and a unique site prefix")
        if "instances" in n:
            check(type(n["instances"]) is int and n["instances"] >= 2, "CNPG requires at least two instances for site HA")
        for k in ("data_size", "wal_size"):
            if k in n:
                check(isinstance(n[k], str) and re.fullmatch(r"[1-9][0-9]*(Gi|Ti)", n[k]), f"invalid {k}")
        fields(n["peer"], {"site_name", "wal_path", "replication_host"}, "peer")
        fields(w["odf"], {"endpoint", "partner_endpoint", "storage_class"}, "odf")
        for k in ("endpoint", "partner_endpoint"):
            url(w["odf"][k], k)
        fields(w["eso"], {"role_arn"}, "eso", {"region", "secret_prefix"})
        if "region" in w["eso"]:
            check(isinstance(w["eso"]["region"], str) and re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]", w["eso"]["region"]), "invalid AWS region")
        check(isinstance(w["eso"]["role_arn"], str) and re.fullmatch(r"arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+", w["eso"]["role_arn"]), "invalid IAM role ARN")
        if "secret_prefix" in w["eso"]:
            check(isinstance(w["eso"]["secret_prefix"], str) and re.fullmatch(r"[a-zA-Z0-9_/-]+", w["eso"]["secret_prefix"]) and not w["eso"]["secret_prefix"].endswith("/"), "invalid secret prefix")
        c = clusters[e["target_cluster_id"]]
        check(n["storage_class"] == w["odf"]["storage_class"] == c["storage_class"], "storage classes must match cluster selection")
        check(w["platform"]["route_url"] == f"https://aap-aap.apps.{c['apps_domain']}", "route_url must match the cluster apps domain")
    check(len({e["target_cluster_id"] for e in envs.values()}) == 2, "environments must target distinct clusters")
    pair = next(iter(pairs.values()))
    fields(pair, {"schema_version", "pair_id", "member_environments", "desired_primary_environment_id"}, "pair")
    members = pair["member_environments"]
    check(isinstance(members, list) and len(members) == 2 and all(isinstance(m, str) for m in members) and set(members) == set(envs), "pair must name both distinct environments")
    check(pair["desired_primary_environment_id"] in members, "desired primary must belong to pair")
    a, b = (envs[m] for m in members)
    check({a["rgw_role"], b["rgw_role"]} == {"primary", "replica"}, "exactly one RGW primary is required")
    for e, peer in ((a, b), (b, a)):
        n, pn = e["workloads"]["cnpg"], peer["workloads"]["cnpg"]
        check(n["site_name"] != pn["site_name"], "site IDs must differ")
        check(n["replication_host"] != pn["replication_host"], "replication hosts must differ")
        check(e["workloads"]["odf"]["endpoint"] != peer["workloads"]["odf"]["endpoint"], "RGW endpoints must differ")
        check(n["peer"] == {k: pn[k] for k in ("site_name", "wal_path", "replication_host")}, "CNPG peer must match partner")
        check(e["rgw_zone_name"] != peer["rgw_zone_name"], "RGW zones must differ")
        check(e["workloads"]["odf"]["partner_endpoint"] == peer["workloads"]["odf"]["endpoint"], "RGW partner endpoint mismatch")
        check(e["workloads"]["platform"]["public_base_url"] == peer["workloads"]["platform"]["public_base_url"], "pair must share public URL")
        if "secret_prefix" in e["workloads"]["eso"] and "secret_prefix" in peer["workloads"]["eso"]:
            check(e["workloads"]["eso"]["secret_prefix"] == peer["workloads"]["eso"]["secret_prefix"], "pair must share secret prefix")
        if e["rgw_role"] == "replica":
            check(e.get("rgw_realm_source_environment_id") == peer["environment_id"], "RGW realm source must be partner")
        else:
            check("rgw_realm_source_environment_id" not in e, "RGW primary must not pull a realm")
    result = dict(settings=settings, **records)
    scan_values(result, deploy=deploy)
    return result
