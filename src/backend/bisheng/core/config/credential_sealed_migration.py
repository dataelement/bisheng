"""Recoverable v1 artifact conversion; no daemon or account lifecycle access."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from bisheng.core.config.credential_artifacts import (
    bundle_native_files,
    read_confidential,
    read_private,
    write_bundle_native,
    write_confidential,
    write_private_atomic,
)
from bisheng.core.config.credential_rotation import _hashes, _policy_mac, credentials, key_identity
from bisheng.core.config.credential_tool import check_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError


def _fail():
    raise CredentialConfigurationError(
        "sealed migration: invalid, changed or unsupported recovery state; preserve all files"
    )


def _public(path, value):
    write_private_atomic(path, json.dumps(value, indent=2, sort_keys=True).encode())


def _save(session, value, key_file):
    value = {k: v for k, v in value.items() if k != "mac"}
    _public(
        Path(session) / "journal.json",
        {**value, "mac": _policy_mac({"kind": "sealed-migration-v2", "journal": value}, key_file)},
    )


def status(session, *, key_file=None):
    key_file = key_file or os.environ.get("BS_SECRET_KEYS_FILE")
    value = json.loads(read_private(Path(session) / "journal.json"))
    mac = value.pop("mac", "")
    if not key_file or not hmac.compare_digest(
        mac, _policy_mac({"kind": "sealed-migration-v2", "journal": value}, key_file)
    ):
        _fail()
    if value.get("version") != 2 or key_identity(key_file) != value.get("key_identity"):
        _fail()
    return value


def _old_files(source, store, *, allow_external_source=False):
    roots = {source}
    active = store / "rotation.active"
    if active.exists():
        previous = Path(read_private(active).decode().strip())
        journal = json.loads(read_private(previous / "journal.json"))
        if journal.get("phase") != "COMPLETE":
            raise CredentialConfigurationError(
                "sealed migration: unfinished v1 rotation requires verified identity recovery before conversion"
            )
    for manifest in (store / "revisions").glob("**/manifest.json"):
        if json.loads(read_private(manifest)).get("version") == 1:
            roots.add(manifest.parent)
    for directory in (store / "rotations").glob("*"):
        if directory.is_dir() and not (directory / ".artifact-context.json").exists():
            if (directory / "journal.json").exists() and json.loads(read_private(directory / "journal.json")).get(
                "phase"
            ) != "COMPLETE":
                _fail()
            roots.add(directory)
    for directory in store.glob("rotation-capture.*"):
        if directory.is_dir() and not (directory / ".artifact-context.json").exists():
            roots.add(directory)
    files = set()
    for directory in roots:
        if not directory.resolve().is_relative_to(store.resolve()) and not (
            allow_external_source and directory == source
        ):
            raise CredentialConfigurationError(
                "sealed migration: external source requires explicit ownership and cleanup authorization"
            )
        for p in directory.rglob("*"):
            if p.is_symlink():
                _fail()
            if p.is_file():
                files.add(p)
    for directory in [store / "inputs", *store.glob("rotation-inputs.*")]:
        if directory.is_symlink():
            _fail()
        if not directory.is_dir():
            continue
        for p in directory.rglob("*"):
            if p.is_symlink():
                _fail()
            if p.name in {".artifact-context.json", "inputs.yaml", "components"}:
                continue  # Retained encrypted inputs still need their identity and manifest.
            if p.is_file() and b'"bisheng.credentials.v2"' not in read_private(p)[:256]:
                files.add(p)
    for p in files:
        if p.stat().st_uid != os.geteuid() or p.stat().st_nlink != 1:
            _fail()
    return sorted(files)


def _is_input_path(path, store):
    return path.is_relative_to(store / "inputs") or any(
        parent.parent == store and parent.name.startswith("rotation-inputs.") for parent in path.parents
    )


def prepare_migration(
    source_bundle,
    *,
    store,
    key_file,
    out_dir,
    deployment,
    env_file=None,
    es_mode=None,
    inputs=None,
    allow_external_source=False,
):
    source, store, out = Path(source_bundle).absolute(), Path(store).absolute(), Path(out_dir).absolute()
    if out.exists() or out.is_symlink() or not out.is_relative_to(store / "migrations"):
        _fail()
    settings, original, _ = check_bundle(source, env_file=env_file)
    if original["version"] not in (1, 2):
        _fail()
    from bisheng.core.config.credential_es_migration import prepare_es_material

    document, expected, es = prepare_es_material(source, settings, key_file, env_file, es_mode, inputs)
    paths = (
        [
            p
            for p in _old_files(source, store, allow_external_source=allow_external_source)
            if p.resolve() != Path(key_file).resolve()
        ]
        if original["version"] == 1
        else []
    )
    native = bundle_native_files(source, key_file, allow_legacy=True)
    native.pop("telemetry_elasticsearch.password", None)
    if original.get("mode") == "adopt-key" and not original["native_files"]:
        from bisheng.core.config.credential_bundle import _native

        native = {k: v.encode() for k, v in _native(document, expected, expected["milvus"]).items()}
    if es:
        native["elasticsearch.password"] = expected["elasticsearch"].encode()
        from bisheng.core.config.credential_es_migration import rewrite_security_config

        rewrite_security_config(native, bool(expected.get("elasticsearch")))
    if not expected.get("redis"):
        native.update({"redis.password": b"", "redis-users.acl": b"user default on nopass ~* &* +@all\n"})
    try:
        out.mkdir(mode=0o700)
        _public(
            out / ".artifact-context.json", {"version": 2, "revision": uuid.uuid4().hex, "deployment_id": deployment}
        )
        backup = out / "backups"
        backup.mkdir(mode=0o700)
        records = []
        external_backups = []
        for i, p in enumerate(paths):
            content = read_private(p)
            dest = backup / (str(i).zfill(6) + ".sealed")
            write_confidential(dest, content, key_file=key_file, deployment=deployment)
            input_file = _is_input_path(p, store)
            record = {
                "path": str(p),
                "backup": str(dest.relative_to(out)),
                "sha256": hashlib.sha256(content).hexdigest(),
                "action": "seal-input" if input_file else "unlink",
            }
            if not p.resolve().is_relative_to(store.resolve()):
                external_backups.append(record)  # Read-only source import; never delete the old project's files.
            else:
                records.append(record)
        from bisheng.core.config.credential_loader import load_config

        inventory = {
            "files": records,
            "external_backups": external_backups,
            "credentials": expected,
            "original_credentials": credentials(settings),
            "original_document": load_config(source / "config.yaml", env_file=env_file).data,
        }
        write_confidential(
            out / "inventory.sealed.json", json.dumps(inventory).encode(), key_file=key_file, deployment=deployment
        )
        bundle = out / "bundle"
        bundle.mkdir(mode=0o700)
        from bisheng.core.config.credential_loader import dump_document

        write_private_atomic(bundle / "config.yaml", dump_document(document).encode())
        manifest = {
            **original,
            "version": 2,
            "mode": "sealed-migration",
            "source_mode": original.get("mode"),
            "revision": uuid.uuid4().hex,
            "deployment_id": deployment,
            "runtime_seeded": original.get("runtime_seeded", []) if original["version"] == 2 else [],
            "sealed_migration": True,
        }
        manifest["es_security_enabled"] = bool(expected.get("elasticsearch"))
        from bisheng.core.config.credential_inputs import is_weak

        manifest["pending"] = sorted(
            {name for name, value in expected.items() if is_weak(value, name)}
            | ({"elasticsearch"} if not manifest["es_security_enabled"] else set())
        )
        manifest.update(write_bundle_native(bundle, native))
        _public(bundle / "manifest.json", manifest)
        value = {
            "version": 2,
            "phase": "SEALED",
            "source": str(source),
            "bundle": str(bundle),
            "store": str(store),
            "key_identity": key_identity(key_file),
            "request": "",
            "inventory_sha256": hashlib.sha256(read_private(out / "inventory.sealed.json")).hexdigest(),
        }
        value["source_mode"] = original.get("mode", "")
        if es:
            value["es"] = es
        _save(out, value, key_file)
        return out
    except Exception:
        shutil.rmtree(out)
        raise


def _inventory(session, value, key_file):
    p = Path(session) / value.get("inventory_file", "inventory.sealed.json")
    if p.parent != Path(session):
        _fail()
    if hashlib.sha256(read_private(p)).hexdigest() != value["inventory_sha256"]:
        _fail()
    return json.loads(read_confidential(p, key_file=key_file))


def verify_staged(session, bundle, *, key_file, env_file=None):
    value = status(session, key_file=key_file)
    if value["phase"] not in {"SEALED", "VERIFIED"}:
        _fail()
    bundle = Path(bundle).absolute()
    if not bundle.is_relative_to(Path(value["store"])) or bundle.is_symlink():
        _fail()
    settings, manifest, pending = check_bundle(bundle, env_file=env_file)
    inventory = _inventory(session, value, key_file)
    if manifest["version"] != 2 or credentials(settings) != inventory["credentials"]:
        _fail()
    baseline = Path(session) / "backups"
    payload = {
        "version": 1,
        "revision": manifest["revision"],
        "key_identity": key_identity(key_file),
        "baseline": str(baseline),
        "baseline_hashes": _hashes(baseline),
        "bundle_hashes": {k: v for k, v in _hashes(bundle).items() if k != "deployment-policy.json"},
        "retained_pending": pending,
        "selected": [],
        "preserve_native": False,
        "run_id": json.loads(read_private(Path(session) / ".artifact-context.json"))["revision"],
    }
    _public(bundle / "deployment-policy.json", {"payload": payload, "mac": _policy_mac(payload, key_file)})
    value.update(phase="VERIFIED", bundle=str(bundle))
    _save(session, value, key_file)


def mark_phase(session, phase, *, key_file=None, request=None):
    key_file = key_file or os.environ.get("BS_SECRET_KEYS_FILE")
    value = status(session, key_file=key_file)
    if phase == "CONSUMERS_SWITCHED" and value["phase"] not in {"VERIFIED", "CONSUMERS_SWITCHED"}:
        _fail()
    if phase not in {value["phase"], "CONSUMERS_SWITCHED"}:
        _fail()
    value["phase"] = phase
    if request is not None:
        value["request"] = str(request)
    _save(session, value, key_file)


def cleanup(session, *, key_file):
    value = status(session, key_file=key_file)
    if value["phase"] not in {"CONSUMERS_SWITCHED", "COMPLETE"}:
        _fail()
    # Missing source paths are not evidence of deletion unless the real store
    # is mounted. Exact-file/session-only mounts can fabricate an empty parent.
    deployment = json.loads(read_private(Path(session) / ".artifact-context.json"))["deployment_id"]
    if read_private(Path(value["store"]) / "deployment.id").decode().strip() != deployment:
        _fail()
    inventory = _inventory(session, value, key_file)
    candidates = []
    for row in inventory["files"]:
        if row.get("action", "unlink") not in {"seal-input", "unlink"}:
            _fail()
        backup = Path(session) / row["backup"]
        if not backup.resolve().is_relative_to(Path(session).resolve()):
            _fail()
        restored = read_confidential(backup, key_file=key_file)
        if hashlib.sha256(restored).hexdigest() != row["sha256"]:
            _fail()
        p = Path(row["path"])
        if not p.resolve().is_relative_to(Path(value["store"]).resolve()) or p.is_symlink():
            _fail()
        if p.exists():
            if p.stat().st_uid != os.geteuid():
                _fail()
            if hashlib.sha256(read_private(p)).hexdigest() != row["sha256"]:
                if row.get("action") == "seal-input" and read_confidential(p, key_file=key_file) == restored:
                    continue  # An interrupted cleanup already sealed this exact input.
                _fail()
            if _is_input_path(p, Path(value["store"])) and p.name in {
                ".artifact-context.json",
                "inputs.yaml",
                "components",
            }:
                continue  # Older in-flight inventories may include v2 input metadata.
            candidates.append((p, row.get("action", "unlink"), restored))
    # Verify the whole cleanup batch before removing even the first old file.
    for p, action, restored in candidates:
        if action == "seal-input":
            write_confidential(p, restored, key_file=key_file, deployment=deployment)
        elif action == "unlink":
            p.unlink()
        else:
            _fail()
    value["phase"] = "COMPLETE"
    _save(session, value, key_file)


def verify_bindings(session, bindings, *, key_file):
    """Reject even stopped consumers still referencing a plaintext source."""
    value = status(session, key_file=key_file)
    inventory = _inventory(session, value, key_file)
    if not isinstance(bindings, list) or not bindings:
        _fail()
    sources = []
    for source in bindings:
        if not isinstance(source, str) or not Path(source).is_absolute():
            _fail()
        sources.append(Path(source).resolve())
    for row in inventory["files"]:
        old = Path(row["path"]).resolve()
        if any(old == source or old.is_relative_to(source) for source in sources):
            raise CredentialConfigurationError(
                "sealed migration: a consumer still mounts legacy plaintext; cleanup refused"
            )


def sanitize_environment(bundle, env_file, session, *, key_file):
    """Remove consumed password aliases only after preserving an encrypted copy."""
    from bisheng.core.config.credential_loader import load_config, read_env_file

    bundle, env_file, session = Path(bundle), Path(env_file), Path(session)
    manifest = json.loads(read_private(bundle / "manifest.json"))
    environment = read_env_file(env_file)
    remaining = set(load_config(bundle / "config.yaml", environment).sources.values())
    owned = (
        "database_url",
        "redis_url",
        "celery_redis_url",
        # Match prepare_bundle's materialized credential fields, not whole
        # component objects: topology !env references remain live in the bundle.
        "object_storage.minio.secret_key",
        "object_storage.minio.access_key",
        "vector_stores.milvus.connection_args",
        "vector_stores.elasticsearch.ssl_verify",
        "vector_stores.elasticsearch.url",
        "telemetry_elasticsearch.ssl_verify",
        "telemetry_elasticsearch.url",
    )
    names = {
        name
        for location, name in manifest.get("sources", {}).items()
        if any(location == p or location.startswith(p + ".") for p in owned)
    }
    names.update(
        {
            "MYSQL_ROOT_PASSWORD",
            "MYSQL_PASSWORD",
            "REDIS_PASSWORD",
            "MINIO_ROOT_PASSWORD",
            "MINIO_SECRET_KEY",
            "ELASTICSEARCH_PASSWORD",
            "ELASTIC_PASSWORD",
            "MILVUS_PASSWORD",
            "bisheng_DATABASE_URL",
        }
    )
    names.intersection_update(environment)
    if not names:
        return
    if remaining & names:
        raise CredentialConfigurationError(
            "environment: a consumed password alias still has another config consumer; automatic cleanup refused"
        )
    raw = read_private(env_file)
    if env_file.stat().st_uid != os.geteuid() or env_file.stat().st_nlink != 1:
        _fail()
    lines = raw.decode().splitlines(keepends=True)
    kept = []
    for line in lines:
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match is None or match[1] not in names:
            kept.append(line)
    session.mkdir(mode=0o700, exist_ok=True)
    context = session / ".artifact-context.json"
    if not context.exists():
        _public(context, {"version": 2, "revision": uuid.uuid4().hex, "deployment_id": manifest["deployment_id"]})
    backup = session / "environment.before.sealed"
    if backup.exists():
        if read_confidential(backup, key_file=key_file) != raw:
            _fail()
    else:
        write_confidential(backup, raw, key_file=key_file, deployment=manifest["deployment_id"])
    write_private_atomic(env_file, "".join(kept).encode())
