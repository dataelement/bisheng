"""Compile scoped native recreation from captured Compose, without Docker access."""

from __future__ import annotations

import copy
import json
import re
import shlex
from pathlib import Path

from bisheng.core.config.secret_crypto import CredentialConfigurationError


def _fail():
    raise CredentialConfigurationError("rotation: unsupported native deployment layout; no accounts changed")


def _literal(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, dict):
        return {k: _literal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_literal(v) for v in value]
    return value


def compile_native(inventory, *, component, bundle, installer_root, secret_gid, run_id):
    if component not in {"mysql", "redis", "elasticsearch", "minio", "milvus"} or not re.fullmatch(
        r"[0-9a-f]{32}", run_id
    ):
        _fail()
    result = copy.deepcopy(inventory.get("compose", {}))
    services = result.get("services", {})
    if component == "minio" and "milvus" not in services:
        _fail()
    affected = [component]
    for dependency in {"mysql": ["openfga"], "minio": ["milvus"]}.get(component, []):
        if dependency in services:
            affected.append(dependency)
    images = {}
    for name in affected:
        service = services.get(name)
        if not isinstance(service, dict) or service.get("network_mode"):
            _fail()
        matches = [
            c
            for c in inventory.get("containers", [])
            if c.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == name
        ]
        if len(matches) != 1:
            _fail()
        container = matches[0]
        labels = container["Config"]["Labels"]
        if labels.get("com.docker.compose.project") != inventory.get("project") or container.get("Name", "").lstrip(
            "/"
        ) != service.get("container_name"):
            _fail()
        # Runtime mounts and environment are authoritative. Unselected native
        # daemons can still mount an older (equivalent) bundle after a previous
        # scoped rotation; using the newly rendered source would lose that fact.
        if "Mounts" in container:
            actual_volumes = []
            for index, volume in enumerate(container["Mounts"]):
                kind = volume.get("Type")
                if kind == "tmpfs":
                    continue  # Reconstructed from HostConfig, never converted to a persistent volume.
                if kind not in {"bind", "volume"}:
                    _fail()
                item = {"type": kind, "target": volume["Destination"], "read_only": not volume.get("RW", True)}
                if kind == "bind":
                    item["source"] = volume["Source"]
                    item["bind"] = {"create_host_path": False}
                    if volume.get("Propagation"):
                        item["bind"]["propagation"] = volume["Propagation"]
                else:
                    key = "rotation-" + name + "-" + str(index)
                    item["source"] = key
                    result.setdefault("volumes", {})[key] = {"external": True, "name": volume["Name"]}
                actual_volumes.append(item)
            service["volumes"] = actual_volumes
            service["environment"] = dict(v.split("=", 1) for v in container["Config"].get("Env", []) if "=" in v)
            service["command"] = container["Config"].get("Cmd")
            service["entrypoint"] = container["Config"].get("Entrypoint")
            host = container.get("HostConfig", {})
            resource_fields = {
                "Memory": "mem_limit",
                "MemoryReservation": "mem_reservation",
                "MemorySwap": "memswap_limit",
                "CpuShares": "cpu_shares",
                "CpuPeriod": "cpu_period",
                "CpuQuota": "cpu_quota",
                "CpusetCpus": "cpuset",
                "PidsLimit": "pids_limit",
                "ShmSize": "shm_size",
            }
            for source, target in resource_fields.items():
                if host.get(source):
                    service[target] = host[source]
                else:
                    service.pop(target, None)
            if host.get("NanoCpus"):
                service["cpus"] = host["NanoCpus"] / 1_000_000_000
            else:
                service.pop("cpus", None)
            for source, target in {
                "ReadonlyRootfs": "read_only",
                "Privileged": "privileged",
                "CapAdd": "cap_add",
                "CapDrop": "cap_drop",
                "SecurityOpt": "security_opt",
                "ExtraHosts": "extra_hosts",
                "Dns": "dns",
                "Sysctls": "sysctls",
                "Tmpfs": "tmpfs",
            }.items():
                if host.get(source):
                    service[target] = host[source]
                else:
                    service.pop(target, None)
            # HostConfig may retain HostPort="" for an ephemeral published port.
            # Runtime Ports contains the allocation that must survive recreation.
            bindings = container.get("NetworkSettings", {}).get("Ports") or host.get("PortBindings", {}) or {}
            service["ports"] = [
                {
                    "target": int(port.split("/")[0]),
                    "protocol": port.partition("/")[2] or "tcp",
                    "published": item["HostPort"],
                    "host_ip": item.get("HostIp") or "0.0.0.0",
                }
                for port, items in bindings.items()
                for item in (items or [])
            ]
            if container["Config"].get("User"):
                service["user"] = container["Config"]["User"]
            else:
                service.pop("user", None)
            actual_networks = container.get("NetworkSettings", {}).get("Networks", {})
            for network in service.get("networks", {}):
                declaration = result.get("networks", {}).get(network) or {}
                if declaration.get("name") not in actual_networks:
                    _fail()

        image_id = container.get("Image", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            _fail()
        alias = "bisheng-credential-native:" + run_id + "-" + name
        images[alias] = image_id
        service["image"] = alias
        service.pop("build", None)
        service.pop("pull_policy", None)
        service.pop("profiles", None)
        service.pop("depends_on", None)
        groups = service.setdefault("group_add", [])
        if str(secret_gid) not in groups:
            groups.append(str(secret_gid))
        if not isinstance(service.get("environment", {}), dict) or not isinstance(service.get("volumes", []), list):
            _fail()

    manifest_path = Path(bundle) / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("version") != 2:
            _fail()
        # Option C plaintext bundles mount host files directly and never ship the
        # sealed-era credential-runtime binary. Keep the sealed compile path only
        # when inventory still carries that layout; otherwise fall through to the
        # plaintext helper path below (same as charts without a stage manifest).
        if manifest.get("native_storage") != "plaintext":
            from bisheng.core.config.credential_runtime_compose import apply_runtime

            runtime = inventory.get("sealed_runtime", {})
            if set(runtime) != {"binary", "key_dir"} or any(not str(v).startswith("/") for v in runtime.values()):
                _fail()
            protected = {}
            for name in affected:
                protected[name] = _literal(
                    apply_runtime(
                        services[name],
                        name,
                        bundle=bundle,
                        key_dir=runtime["key_dir"],
                        binary=runtime["binary"],
                        deployment=manifest["deployment_id"],
                        revision=manifest["revision"],
                        secret_gid=secret_gid,
                    )
                )
            # The exported recreation file must not repeat unselected services'
            # legacy passwords merely because their Compose definitions exist.
            result = {k: v for k, v in result.items() if k in {"name", "networks", "volumes"}}
            result["services"] = protected
            networks = result.setdefault("networks", {})
            for name, value in list(networks.items()):
                if not isinstance(value, dict) or not value.get("name"):
                    _fail()
                networks[name] = {"external": True, "name": value["name"]}
            return {"compose": result, "services": affected, "images": images, "redis_conf": None}

    def mount(name, source, target):
        service = services[name]
        volumes = service.setdefault("volumes", [])
        if any(not isinstance(v, dict) for v in volumes):
            _fail()
        service["volumes"] = [v for v in volumes if v.get("target") != target]
        service["volumes"].append(
            {
                "type": "bind",
                "source": str(source),
                "target": target,
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )

    def secret(name, file):
        mount(name, Path(bundle) / file, "/run/secrets/" + file)

    def env(name, remove, **values):
        target = services[name].setdefault("environment", {})
        for key in remove:
            target.pop(key, None)
        target.update(values)

    def health(name, folder):
        mount(name, Path(installer_root) / folder / "credential-health.sh", "/credential-health.sh")
        services[name]["healthcheck"] = {
            "test": ["CMD", "sh", "/credential-health.sh"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 12,
            "start_period": "20s",
        }

    if component in {"minio", "milvus"}:
        milvus_env = services.get("milvus", {}).get("environment", {})
        if any(
            k.startswith(("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "COMMON_SECURITY", "MILVUSCONFIG"))
            for k in milvus_env
        ):
            _fail()
    redis_conf = None
    if component == "mysql":
        env(
            "mysql",
            ["MYSQL_ROOT_PASSWORD", "MYSQL_ALLOW_EMPTY_PASSWORD", "MYSQL_RANDOM_ROOT_PASSWORD"],
            MYSQL_ROOT_PASSWORD_FILE="/run/secrets/mysql.password",
        )
        secret("mysql", "mysql.password")
        secret("mysql", "mysql-client.cnf")
        mount("mysql", Path(installer_root) / "mysql/credential-entrypoint.sh", "/credential-entrypoint.sh")
        services["mysql"]["entrypoint"] = ["bash", "/credential-entrypoint.sh"]
        health("mysql", "mysql")
        if "openfga" in affected:
            env("openfga", ["OPENFGA_DATASTORE_URI"])
            mount("openfga", Path(bundle) / "openfga.yaml", "/etc/openfga/config.yaml")
            services["openfga"]["env_file"] = [str(Path(bundle) / "openfga.env")]
            services["openfga"]["command"] = ["run"]
            if "openfga-migrate" in services:
                services["openfga-migrate"]["env_file"] = [str(Path(bundle) / "openfga.env")]
                services["openfga-migrate"]["command"] = ["migrate"]
                mount("openfga-migrate", Path(bundle) / "openfga.yaml", "/etc/openfga/config.yaml")
    elif component == "redis":
        command = services["redis"].get("command")
        if isinstance(command, str):
            command = shlex.split(command)
        if (
            not isinstance(command, list)
            or len(command) < 2
            or Path(command[0]).name != "redis-server"
            or command[1] != "/etc/redis.conf"
        ):
            _fail()
        content = inventory.get("files", {}).get("redis.conf")
        if not isinstance(content, str):
            _fail()
        kept = []
        for line in content.splitlines(keepends=True):
            parts = shlex.split(line, comments=True)
            if parts and parts[0].lower() in {"include", "user"}:
                _fail()
            if not parts or parts[0].lower() not in {"requirepass", "aclfile"}:
                kept.append(line)
        redis_conf = "".join(kept)
        cleaned = [*command[:2], "--aclfile", "/run/secrets/redis-users.acl"]
        i = 2
        while i < len(command):
            if command[i] in {"--requirepass", "--aclfile"}:
                if i + 1 >= len(command):
                    _fail()
                i += 2
            else:
                if command[i].startswith(("--requirepass=", "--aclfile=", "--include", "--user")):
                    _fail()
                cleaned.append(command[i])
                i += 1
        services["redis"]["command"] = cleaned
        services["redis"]["entrypoint"] = ["sh", "/credential-entrypoint.sh"]
        mount("redis", Path(installer_root) / "redis/credential-entrypoint.sh", "/credential-entrypoint.sh")
        mount("redis", Path(bundle).parent.parent / "native/redis.conf", command[1])
        secret("redis", "redis-users.acl")
        secret("redis", "redis.password")
        health("redis", "redis")
    elif component == "elasticsearch":
        env(
            "elasticsearch",
            ["ELASTICSEARCH_PASSWORD"],
            ELASTICSEARCH_PASSWORD_FILE="/run/secrets/elasticsearch.password",
        )
        secret("elasticsearch", "elasticsearch.password")
    elif component == "minio":
        env(
            "minio",
            [
                "MINIO_ACCESS_KEY",
                "MINIO_SECRET_KEY",
                "MINIO_ROOT_USER",
                "MINIO_ROOT_PASSWORD",
                "MINIO_ACCESS_KEY_FILE",
                "MINIO_SECRET_KEY_FILE",
            ],
            MINIO_ROOT_USER_FILE="/run/secrets/minio.user",
            MINIO_ROOT_PASSWORD_FILE="/run/secrets/minio.password",
        )
        secret("minio", "minio.user")
        secret("minio", "minio.password")
        if "milvus" in affected:
            mount("milvus", Path(bundle) / "milvus.yaml", "/milvus/configs/user.yaml")
    elif component == "milvus":
        mount("milvus", Path(bundle) / "milvus.yaml", "/milvus/configs/user.yaml")
    for name in affected:
        services[name] = _literal(services[name])
    # Do not serialize unselected services: their Compose env may still carry
    # legacy password material from the captured chart.
    result = {k: v for k, v in result.items() if k in {"name", "networks", "volumes"}}
    result["services"] = {name: services[name] for name in affected}
    networks = result.setdefault("networks", {})
    for name, value in list(networks.items()):
        if not isinstance(value, dict) or not value.get("name"):
            _fail()
        networks[name] = {"external": True, "name": value["name"]}
    return {"compose": result, "services": affected, "images": images, "redis_conf": redis_conf}
