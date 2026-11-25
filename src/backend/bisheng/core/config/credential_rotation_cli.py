"""Internal command surface for the host installer; never exposes secret values."""

from __future__ import annotations

import json
from pathlib import Path

from bisheng.core.config import credential_rotation as state
from bisheng.core.config.credential_inputs import read_inputs, write_private
from bisheng.core.config.credential_tool import check_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError


def parser(sub):
    p = sub.add_parser("rotation")
    p.add_argument(
        "action",
        choices=[
            "inventory",
            "capabilities",
            "capture",
            "preflight",
            "prepare",
            "rollback",
            "info",
            "mark",
            "step",
            "verify",
            "persist",
            "policy",
            "validate-policy",
            "export",
            "request-id",
            "request-components",
        ],
    )
    for name in (
        "session-dir",
        "bundle",
        "inputs",
        "key-file",
        "env-file",
        "inventory-file",
        "out",
        "out-dir",
        "deployment-root",
        "policy-root",
    ):
        p.add_argument("--" + name, type=Path)
    p.add_argument("--installer-root")
    p.add_argument("--secret-gid", default="0")
    p.add_argument("--component")
    p.add_argument("--phase")
    p.add_argument("--field")
    p.add_argument("--socket-old", choices=["OK", "DENIED", "UNKNOWN"], default="UNKNOWN")
    p.add_argument("--socket-new", choices=["OK", "DENIED", "UNKNOWN"], default="UNKNOWN")
    p.add_argument("--apply", action="store_true")
    return p


def execute(args):
    from bisheng.core.config import credential_rotation_native as native

    action = args.action
    if action == "capabilities":
        print("rotation-v1")
        return 0
    if action in {"request-id", "request-components"}:
        supplied = read_inputs(args.inputs)
        if action == "request-components":
            print("\n".join(n for n in state.ORDER if n in supplied))
            return 0
        if not args.key_file:
            raise CredentialConfigurationError("rotation: key required for private request identity")
        print(state._policy_mac({"kind": "rotation-request-v2", "inputs": supplied}, args.key_file))
        return 0
    if action == "validate-policy":
        payload = state.validate_deployment_policy(args.bundle, key_file=args.key_file, env_file=args.env_file)
        print("preserve-native" if payload["preserve_native"] else "managed")
        return 0
    if action == "inventory":
        import yaml

        folder = args.inventory_file
        compose = yaml.safe_load(state._read(folder / "compose.yaml"))
        containers = state._json(folder / "containers.json")
        projects = {c.get("Config", {}).get("Labels", {}).get("com.docker.compose.project") for c in containers}
        if len(projects) != 1 or None in projects:
            raise CredentialConfigurationError("rotation: deployment project identity is ambiguous")
        project = projects.pop()
        applications = yaml.safe_load(state._read(folder / "application.yaml"))
        consumers = []
        for c in containers:
            service = c["Config"]["Labels"].get("com.docker.compose.service")
            if c.get("State", {}).get("Running") and service in {
                "frontend",
                "backend",
                "backend_worker",
                "gateway",
                "linsight_worker",
                "celery",
                "worker",
            }:
                expected = applications.get("services", {}).get(service, {}).get("container_name")
                if expected != c["Name"].lstrip("/"):
                    raise CredentialConfigurationError(
                        "rotation: target application identity differs from the running consumer"
                    )
                consumers.append(c["Name"].lstrip("/"))
        value = {
            "version": 1,
            "project": project,
            "compose": compose,
            "containers": containers,
            "consumers": consumers,
            "files": {},
        }
        from bisheng.core.config.credential_runtime_compose import TOOL, _target

        native_target = applications.get("services", {}).get("mysql", {})
        runtime = {}
        for volume in native_target.get("volumes", []):
            target = _target(volume)
            source = volume.get("source") if isinstance(volume, dict) else volume.rsplit(":", 2)[0]
            if target == TOOL:
                runtime["binary"] = source
            elif target == "/run/bisheng-keyring.json":
                runtime["key_dir"] = str(Path(source).parent)
        if runtime:
            value["sealed_runtime"] = runtime
        redis_conf = folder / "redis.conf"
        if redis_conf.exists():
            value["files"]["redis.conf"] = state._read(redis_conf).decode()
        minio = next((c for c in containers if c["Config"]["Labels"].get("com.docker.compose.service") == "minio"), {})
        minio_env = dict(e.split("=", 1) for e in minio.get("Config", {}).get("Env", []) if "=" in e)
        if (folder / "minio-version").exists():
            value["minio_version"] = state._read(folder / "minio-version").decode()
        value["minio_root_user"] = minio_env.get("MINIO_ROOT_USER") or minio_env.get("MINIO_ACCESS_KEY")
        if not value["minio_root_user"] and (folder / "minio.user").exists():
            value["minio_root_user"] = state._read(folder / "minio.user").decode().strip()
        native = {}
        milvus = {}

        def merge(target, source):
            for k, v in source.items():
                if isinstance(v, dict) and isinstance(target.get(k), dict):
                    merge(target[k], v)
                else:
                    target[k] = v

        for filename in ("milvus.yaml", "user.yaml"):
            if (folder / filename).exists():
                data = yaml.safe_load(state._read(folder / filename)) or {}
                merge(milvus, data)
        if milvus:
            value["milvus_auth_enabled"] = (
                milvus.get("common", {}).get("security", {}).get("authorizationEnabled", False) is True
            )
            native["milvus.yaml"] = yaml.safe_dump(milvus)
        value["native_files"] = native
        value["redis_group_drop_supported"] = (folder / "redis-groups").exists() and state._read(
            folder / "redis-groups"
        ).decode().strip() == "supported"
        value["mysql_socket_old"] = args.socket_old
        state.atomic_json(args.out, value)
        return 0
    if action == "capture":
        inventory = state._json(args.inventory_file)
        settings = check_bundle(args.bundle, env_file=args.env_file)[0]
        selected = [n for n in state.ORDER if n in read_inputs(args.inputs)]
        validate_owned_endpoints(settings, selected, inventory)
        evidence = native.capture_runtime(settings, selected, inventory)
        # Files captured by the host are private, not command-line values.
        evidence["native_files"].update(inventory.pop("native_files", {}))
        inventory.update(evidence)
        state.atomic_json(args.out, inventory)
        return 0
    if action == "prepare":
        state.prepare_rotation(
            base_bundle=args.bundle,
            key_file=args.key_file,
            inputs=args.inputs,
            out_dir=args.out_dir,
            env_file=args.env_file,
            deployment_root=args.deployment_root,
            inventory_file=args.inventory_file,
            installer_root=args.installer_root,
            secret_gid=args.secret_gid,
        )
        return 0
    if action == "rollback":
        if not args.apply:
            raise CredentialConfigurationError("rotation: explicit rollback confirmation required")
        state.prepare_rollback(
            args.session_dir,
            out_dir=args.out_dir,
            key_file=args.key_file,
            installer_root=args.installer_root,
            secret_gid=args.secret_gid,
        )
        return 0
    plan = state.read_plan(args.session_dir, key_file=args.key_file)
    if action == "preflight":
        native.preflight_identities(args.session_dir, key_file=args.key_file)
        print("preflight: all selected identities verified")
        return 0
    if action == "info":
        field = args.field
        if field == "selected":
            print("\n".join(plan["selected"]))
        elif field == "stage":
            print(plan["stages"][args.component])
        elif field == "source":
            print(plan["source"])
        elif field == "final":
            print(plan["stages"][plan["selected"][-1]])
        elif field == "paused":
            print("true" if state.read_journal(args.session_dir)["consumers_stopped"] else "false")
        elif field == "phase":
            print(state.read_journal(args.session_dir)["phase"])
        elif field == "component-phase":
            print(state.read_journal(args.session_dir)["components"][args.component]["phase"])
        elif field == "request-id":
            print(plan["request_digest"])
        elif field == "project":
            print(state._json(args.session_dir / "inventory.json")["project"])
        elif field == "consumers":
            print("\n".join(state._json(args.session_dir / "inventory.json").get("consumers", [])))
        elif field in {"images", "services"}:
            compiled = state._json(args.session_dir / "native" / (args.component + ".json"))
            print(
                "\n".join(
                    (original + " " + alias for alias, original in compiled["images"].items())
                    if field == "images"
                    else compiled["services"]
                )
            )
        else:
            raise CredentialConfigurationError("rotation: unsupported information field")
    elif action == "mark":
        state.mark_phase(args.session_dir, args.phase)
    elif action in {"step", "verify"}:
        captured = state._json(args.session_dir / "inventory.json")
        if args.component not in captured.get("capabilities", {}):
            raise CredentialConfigurationError("rotation: selected native capability is unverified")
        evidence = {"old": args.socket_old, "new": args.socket_new}
        if action == "step":
            print(
                native.change_component(
                    args.session_dir, args.component, key_file=args.key_file, evidence=evidence, apply=args.apply
                )
            )
        else:
            native.verify_component(args.session_dir, args.component, key_file=args.key_file, evidence=evidence)
    elif action == "persist":
        state.record_component(args.session_dir, args.component, "FILES_PERSISTED")
    elif action == "policy":
        state.write_deployment_policy(args.session_dir, key_file=args.key_file)
    elif action == "export":
        compiled = state._json(args.session_dir / "native" / (args.component + ".json"))
        write_private(args.out, json.dumps(compiled["compose"]))
    return 0


def validate_owned_endpoints(settings, selected, inventory):
    """Require Docker-owned addresses, including MinIO's Milvus consumer."""
    import socket
    from urllib.parse import urlparse

    from sqlalchemy.engine import make_url

    redis_url = settings.redis_url if isinstance(settings.redis_url, str) else settings.redis_url.get("url", "")
    es_urls = settings.vector_stores.elasticsearch.elasticsearch_url
    if isinstance(es_urls, str):
        es_urls = [es_urls]
    endpoints = {
        "mysql": [make_url(settings.database_url).host],
        "redis": [urlparse(redis_url).hostname],
        "minio": [urlparse("//" + settings.object_storage.minio.endpoint).hostname],
        "milvus": [(settings.vector_stores.milvus.connection_args or {}).get("host")],
        "elasticsearch": [urlparse(u).hostname for u in es_urls],
    }
    managed = list(dict.fromkeys([*selected, *(["milvus"] if "minio" in selected else [])]))
    for name in managed:
        service = inventory.get("compose", {}).get("services", {}).get(name)
        if (
            not service
            or name not in endpoints
            or not endpoints[name]
            or any(host not in {name, service.get("container_name")} for host in endpoints[name])
        ):
            raise CredentialConfigurationError("rotation: external/ambiguous endpoint is outside managed native scope")
        matches = [
            c
            for c in inventory.get("containers", [])
            if c.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == name
        ]
        if len(matches) != 1:
            raise CredentialConfigurationError("rotation: native endpoint ownership is ambiguous")
        expected = {
            v
            for n in matches[0].get("NetworkSettings", {}).get("Networks", {}).values()
            for v in (n.get("IPAddress"), n.get("GlobalIPv6Address"))
            if v
        }
        for host in endpoints[name]:
            try:
                addresses = {row[4][0] for row in socket.getaddrinfo(host, 0, type=socket.SOCK_STREAM)}
            except OSError:
                raise CredentialConfigurationError("rotation: native endpoint address cannot be verified") from None
            if not addresses or not addresses.issubset(expected):
                raise CredentialConfigurationError(
                    "rotation: configured endpoint is outside the captured native container"
                )
