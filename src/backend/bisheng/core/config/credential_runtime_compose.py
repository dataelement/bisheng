"""Pure native-service wiring for plaintext credential mounts (option C)."""

from __future__ import annotations

import copy
import re
import shlex

from bisheng.core.config.secret_crypto import CredentialConfigurationError

SECRET_ROOT = "/run/secrets"
KNOWN_TARGETS = {
    "/run/secrets/mysql.password",
    "/run/secrets/mysql-client.cnf",
    "/run/secrets/redis.password",
    "/run/secrets/redis-users.acl",
    "/run/secrets/minio.user",
    "/run/secrets/minio.password",
    "/run/secrets/elasticsearch.password",
    "/etc/openfga/config.yaml",
    "/etc/redis.conf",
    "/milvus/configs/user.yaml",
    "/application.yml",
    "/run/bisheng-keyring.json",
    "/run/bisheng-sealed.json",
    "/usr/local/bin/bisheng-credential-runtime",
    "/run/bisheng-secrets",
}
NATIVE_ROLES = {"mysql", "mysql-init", "openfga", "openfga-migrate", "redis", "minio", "elasticsearch", "milvus"}


def _fail():
    raise CredentialConfigurationError("runtime: unsupported native credential layout; no accounts changed")


def _target(volume):
    if isinstance(volume, dict):
        return volume.get("target")
    if isinstance(volume, str):
        # ${NAME:?message} contains a colon before interpolation. Parse from
        # the destination end rather than treating that colon as a separator.
        parts = volume.rsplit(":", 2)
        if len(parts) >= 2 and parts[-1].startswith("/"):
            return parts[-1]
        if len(parts) == 3 and parts[-2].startswith("/"):
            return parts[-2]
    _fail()


def _argv(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        value = shlex.split(value)
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        _fail()
    if any(re.search(r"(?i)(?:password|secret|token)(?:=|\s)", x) for x in value):
        _fail()
    return value


def apply_runtime(service, role, *, bundle, key_dir=None, binary=None, deployment=None, revision=None, secret_gid=None):
    """Wire a native service to host plaintext files under ``bundle``.

    ``key_dir`` / ``binary`` / ``deployment`` / ``revision`` remain accepted for
    call-site compatibility with sealed-era migration code, but are unused.
    """
    del key_dir, binary, deployment, revision
    if role not in NATIVE_ROLES:
        _fail()
    result = copy.deepcopy(service)
    environment = result.get("environment") or {}
    if isinstance(environment, list):
        environment = dict(v.split("=", 1) for v in environment if "=" in v)
    if not isinstance(environment, dict):
        _fail()
    known_secrets = {
        "MYSQL_ROOT_PASSWORD",
        "MYSQL_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "MINIO_SECRET_KEY",
        "MINIO_ACCESS_KEY",
        "MINIO_ROOT_USER",
        "ELASTICSEARCH_PASSWORD",
        "OPENFGA_DATASTORE_URI",
        "REDIS_PASSWORD",
    }
    for key in list(environment):
        if key in known_secrets:
            del environment[key]
        elif re.search(r"(?:_PASSWORD|_SECRET|_SECRET_KEY|_TOKEN)$", key) and environment[key]:
            _fail()
    result["environment"] = environment
    # Drop sealed-era tmpfs roots; plaintext mounts do not need them.
    memory = result.get("tmpfs") or []
    if isinstance(memory, dict):
        memory = [p + ":" + opts for p, opts in memory.items()]
    if not isinstance(memory, list):
        _fail()
    managed_roots = {
        "/run/bisheng-secrets",
        "/opt/bitnami/elasticsearch/config",
        "/milvus/configs",
        "/etc/openfga",
        "/tmp",
    }
    result["tmpfs"] = [x for x in memory if isinstance(x, str) and x.split(":", 1)[0] not in managed_roots]
    volumes = []
    for volume in result.get("volumes", []):
        target = _target(volume)
        if target in KNOWN_TARGETS or target in managed_roots or str(target).startswith("/run/bisheng"):
            continue
        volumes.append(volume)
    if secret_gid is not None:
        groups = result.setdefault("group_add", [])

        def group_key(value):
            match = re.match(r"^\$\{([^}:]+)", str(value))
            return match[1] if match else str(value)

        if group_key(secret_gid) not in {group_key(g) for g in groups}:
            groups.append(str(secret_gid))
    if role == "mysql":
        result["entrypoint"] = ["bash", "/credential-entrypoint.sh"]
        result["command"] = _argv(service.get("command"), ["mysqld"])
        environment["MYSQL_ROOT_PASSWORD_FILE"] = SECRET_ROOT + "/mysql.password"
        volumes += [
            f"{bundle}/mysql.password:{SECRET_ROOT}/mysql.password:ro",
            f"{bundle}/mysql-client.cnf:{SECRET_ROOT}/mysql-client.cnf:ro",
        ]
    elif role == "mysql-init":
        result["entrypoint"] = [
            "mysql",
            "--defaults-extra-file=" + SECRET_ROOT + "/mysql-client.cnf",
            "--host=mysql",
            "--execute=CREATE DATABASE IF NOT EXISTS openfga;",
        ]
        result["command"] = []
        volumes.append(f"{bundle}/mysql-client.cnf:{SECRET_ROOT}/mysql-client.cnf:ro")
    elif role.startswith("openfga"):
        result["entrypoint"] = ["/openfga"]
        # Locked openfga:v1.15.2-dm rejects --config; datastore comes from openfga.env.
        result["command"] = ["migrate" if role.endswith("migrate") else "run"]
        result["env_file"] = [f"{bundle}/openfga.env"]
        volumes.append(f"{bundle}/openfga.yaml:/etc/openfga/config.yaml:ro")
    elif role == "redis":
        result["entrypoint"] = ["sh", "/credential-entrypoint.sh"]
        original = _argv(service.get("command"), ["redis-server", "/etc/redis.conf"])
        if len(original) < 2 or original[0] != "redis-server":
            _fail()
        extra = []
        i = 2
        while i < len(original):
            arg = original[i]
            if arg in {"--requirepass", "--aclfile"}:
                if i + 1 >= len(original):
                    _fail()
                i += 2
                continue
            if arg.startswith(("--requirepass=", "--aclfile=", "--include", "--user", "--masterauth")):
                _fail()
            extra.append(arg)
            i += 1
        result["command"] = ["redis-server", "/etc/redis.conf", "--aclfile", SECRET_ROOT + "/redis-users.acl", *extra]
        volumes += [
            f"{bundle}/redis-users.acl:{SECRET_ROOT}/redis-users.acl:ro",
            f"{bundle}/redis.password:{SECRET_ROOT}/redis.password:ro",
        ]
    elif role == "minio":
        result["entrypoint"] = ["/usr/bin/docker-entrypoint.sh"]
        result["command"] = _argv(
            service.get("command"), ["minio", "server", "/minio_data", "--console-address", ":9001"]
        )
        environment.update(
            MINIO_ROOT_USER_FILE=SECRET_ROOT + "/minio.user",
            MINIO_ROOT_PASSWORD_FILE=SECRET_ROOT + "/minio.password",
        )
        volumes += [
            f"{bundle}/minio.user:{SECRET_ROOT}/minio.user:ro",
            f"{bundle}/minio.password:{SECRET_ROOT}/minio.password:ro",
        ]
    elif role == "elasticsearch":
        result.pop("entrypoint", None)
        result["command"] = _argv(service.get("command"), ["/opt/bitnami/scripts/elasticsearch/run.sh"])
        environment["ELASTICSEARCH_PASSWORD_FILE"] = SECRET_ROOT + "/elasticsearch.password"
        volumes.append(f"{bundle}/elasticsearch.password:{SECRET_ROOT}/elasticsearch.password:ro")
    elif role == "milvus":
        result["entrypoint"] = ["sh", "/credential-entrypoint.sh"]
        result["command"] = []
        volumes.append(f"{bundle}/milvus.yaml:/milvus/configs/user.yaml:ro")
    result["volumes"] = volumes
    return result


# Back-compat alias used by inventory discovery of old sealed charts.
TOOL = "/usr/local/bin/bisheng-credential-runtime"
