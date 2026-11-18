"""Durable single-host credential plans; no infrastructure or application lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

import yaml

from bisheng.core.config.credential_artifacts import (
    bundle_native_files,
    read_confidential,
    write_bundle_native,
    write_confidential,
    write_private_atomic,
)
from bisheng.core.config.credential_bundle import prepare_bundle
from bisheng.core.config.credential_inputs import read_inputs, write_private
from bisheng.core.config.credential_tool import check_bundle, redis_password
from bisheng.core.config.secret_crypto import CredentialConfigurationError, load_keyring

ORDER = ("mysql", "redis", "elasticsearch", "telemetry_elasticsearch", "minio", "milvus")
_COMPONENT_PHASES = ("PENDING", "CHANGE_INTENT", "NATIVE_VERIFIED", "FILES_PERSISTED")
_PHASES = {
    "PREPARED",
    "PREFLIGHT_OK",
    "MAINTENANCE_CONFIRMED",
    "CONSUMERS_STOPPED",
    "CHANGING",
    "ALL_VERIFIED",
    "ACTIVATING",
    "SERVICES_READY",
    "COMPLETE",
    "NEEDS_ATTENTION",
}


def _fail(reason):
    raise CredentialConfigurationError("rotation: " + reason)


def _raw(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o027:
                _fail("private regular file required")
            content = stream.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            _fail("artifact too large")
        return content
    except OSError:
        _fail("artifact cannot be read")


def _read(path):
    raw = _raw(path)
    if b'"bisheng.credentials.v2"' in raw[:256]:
        try:
            marker = json.loads(raw)
        except ValueError:
            _fail("invalid encrypted state")
        if marker.get("role") == "maintenance":
            return read_confidential(path)
    return raw


def _json(path):
    try:
        return json.loads(_read(path))
    except (ValueError, TypeError):
        _fail("invalid state document")


def atomic_json(path, value, *, key_file=None, deployment=None):
    """Durability is required before the caller may perform a server-side write."""
    path = Path(path)
    public = {"plan.json", "journal.json", "manifest.json", "deployment-policy.json", ".artifact-context.json"}
    if path.name not in public:
        write_confidential(
            path, json.dumps(value, ensure_ascii=False).encode(), key_file=key_file, deployment=deployment
        )
        return
    temp = path.parent / (".rotation-" + uuid.uuid4().hex)
    try:
        write_private(temp, json.dumps(value, ensure_ascii=False, indent=2))
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        _fail("durable state write failed; do not continue server changes")
    finally:
        temp.unlink(missing_ok=True)


def key_identity(path):
    load_keyring(path)
    return hashlib.sha256(json.dumps(_json(path), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def credentials(settings):
    from sqlalchemy.engine import make_url

    db = make_url(settings.database_url)
    args = settings.vector_stores.milvus.connection_args or {}
    token = args.get("token") or ""
    result = {
        "mysql": str(db.password or ""),
        "redis": str(redis_password(settings.redis_url)),
        "minio": str(settings.object_storage.minio.secret_key or ""),
        "milvus": str(args.get("password") or token.partition(":")[2]),
    }
    for name, conf in (
        ("elasticsearch", settings.vector_stores.elasticsearch),
        ("telemetry_elasticsearch", settings.telemetry_elasticsearch),
    ):
        if name == "elasticsearch" or conf.elasticsearch_url:
            auth = conf.ssl_verify.get("basic_auth")
            result[name] = str(auth[1] if auth else "")
    return result


def _hashes(root):
    if not Path(root).is_dir():
        _fail("immutable baseline directory is missing")
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            _fail("symlink in immutable artifacts")
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(_raw(path)).hexdigest()
    return result


def prepare_rotation(
    *,
    base_bundle,
    key_file,
    inputs,
    out_dir,
    env_file=None,
    deployment_root=None,
    inventory_file=None,
    installer_root=None,
    secret_gid="0",
    rollback_session=None,
):
    """Prepare every stage without activating a file or changing an account."""
    root = Path(out_dir).absolute()
    backend = Path(__file__).resolve().parents[3]
    if root.resolve().is_relative_to(backend) or root.exists() or root.is_symlink():
        _fail("new private output directory outside build context required")
    settings, manifest, pending = check_bundle(base_bundle, env_file=env_file)
    if manifest["version"] != 2:
        _fail("encrypted bundle migration required before native changes")
    supplied = read_inputs(inputs)
    selected = [name for name in ORDER if name in supplied]
    if not selected:
        _fail("explicit selected inputs required")
    old = credentials(settings)
    for name in selected:
        value = supplied[name].get("secret_key" if name == "minio" else "password")
        if name == "milvus" and supplied[name].get("token"):
            value = supplied[name]["token"].partition(":")[2]
        if name not in old:
            _fail("selected component is not configured")
        if value == old[name]:
            _fail("unchanged password; choose retain or provide a different value")
    if pending and manifest.get("mode") != "adopt-key":
        if rollback_session:
            forward = read_plan(rollback_session, key_file=key_file)
            if (
                Path(base_bundle) != Path(forward["stages"][forward["selected"][-1]])
                or not read_journal(rollback_session)["consumers_stopped"]
            ):
                _fail("rollback base is not bound to a paused forward plan")
        else:
            validate_deployment_policy(base_bundle, key_file=key_file, env_file=env_file)
    try:
        root.mkdir(mode=0o700, parents=True)
        run_id = uuid.uuid4().hex
        atomic_json(
            root / ".artifact-context.json",
            {"version": 2, "revision": run_id, "deployment_id": manifest["deployment_id"]},
        )
        source = root / "source"
        shutil.copytree(base_bundle, source)
        captured = _json(inventory_file) if inventory_file else {}
        atomic_json(root / "inventory.json", captured, key_file=key_file)
        if env_file:
            write_confidential(root / "env.before", _read(env_file), key_file=key_file)
        else:
            write_confidential(root / "env.before", b"", key_file=key_file)
        (root / "inputs").mkdir(mode=0o700)
        all_inputs = {"version": 1}
        for name in selected:
            row = {}
            for field, value in supplied[name].items():
                if field in ("user", "username"):
                    row[field] = value
                else:
                    filename = name + "." + field
                    write_confidential(root / "inputs" / filename, value, key_file=key_file)
                    row[field + "_file"] = filename
            all_inputs[name] = row
        write_private(root / "inputs" / "request.yaml", yaml.safe_dump(all_inputs))
        working = root / "captured-base"
        shutil.copytree(source, working)
        for path in working.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        native = captured.get("native_files", {})
        if "milvus.yaml" in native and captured.get("milvus_auth_enabled") is True and old.get("milvus"):
            # defaultRootPassword initializes new stores; it may lag an already
            # changed native root. Bind initialization metadata to the verified
            # current identity while preserving all other native configuration.
            document = yaml.safe_load(native["milvus.yaml"])
            document.setdefault("common", {}).setdefault("security", {})["defaultRootPassword"] = old["milvus"]
            native["milvus.yaml"] = yaml.safe_dump(document)

        if not isinstance(native, dict) or set(native) - {"milvus.yaml", "redis-users.acl"}:
            _fail("invalid captured native configuration")
        derived = _json(working / "manifest.json")
        working_native = bundle_native_files(working, key_file)
        for name, content in native.items():
            if not isinstance(content, str):
                _fail("invalid native baseline")
            working_native[name] = content
            if name not in derived["native_files"]:
                derived["native_files"].append(name)
        derived.update(write_bundle_native(working, working_native))
        (working / "deployment-policy.json").unlink(missing_ok=True)
        atomic_json(working / "manifest.json", derived)
        stages = {}
        base = working
        (root / "stages").mkdir(mode=0o700)
        for name in selected:
            request = root / "inputs" / (name + ".yaml")
            write_private(request, yaml.safe_dump({"version": 1, name: all_inputs[name]}))
            target = root / "stages" / name
            prepare_bundle(
                mode="password-change",
                component=name,
                base_bundle=base,
                inputs=request,
                key_file=key_file,
                out_dir=target,
                env_file=env_file,
                deployment_root=deployment_root,
            )
            check_bundle(target, env_file=env_file)
            stages[name] = "stages/" + name
            base = target
        if installer_root:
            from bisheng.core.config.credential_rotation_compose import compile_native

            if set(captured.get("capabilities", {})) != set(selected):
                _fail("all selected native capabilities must be verified before preparing")
            (root / "native").mkdir(mode=0o700)
            for name in selected:
                compiled = compile_native(
                    captured,
                    component=name,
                    bundle=str(root / stages[name]),
                    installer_root=installer_root,
                    secret_gid=secret_gid,
                    run_id=run_id,
                )
                if compiled["redis_conf"] is not None:
                    # Option C: Redis mounts this host file as /etc/redis.conf; it must
                    # be plaintext, never a sealed credentials envelope.
                    payload = compiled["redis_conf"]
                    write_private_atomic(
                        root / "native/redis.conf",
                        payload.encode() if isinstance(payload, str) else payload,
                        mode=0o600,
                    )
                atomic_json(root / "native" / (name + ".json"), compiled)
        plan = {
            "version": 1,
            "run_id": run_id,
            "selected": selected,
            "key_file": str(Path(key_file).absolute()),
            "key_identity": key_identity(key_file),
            "source": "source",
            "source_revision": manifest["revision"],
            "stages": stages,
            "retained_pending": sorted(set(pending) - set(selected)),
            "request_digest": _policy_mac({"kind": "rotation-request-v2", "inputs": supplied}, key_file),
            "artifacts": _hashes(root),
        }
        atomic_json(root / "plan.json", plan)
        atomic_json(
            root / "journal.json",
            {
                "version": 1,
                "phase": "PREPARED",
                "sequence": 0,
                "consumers_stopped": False,
                "components": {name: {"phase": "PENDING", "accounts": {}} for name in selected},
            },
        )
        return root
    except Exception:
        # No native write occurs here. Remove only this unactivated attempt.
        shutil.rmtree(root)
        raise


def read_plan(session, *, key_file=None):
    root = Path(session).absolute()
    if root.is_symlink() or not root.is_dir():
        _fail("private session directory required")
    plan = _json(root / "plan.json")
    try:
        if (
            plan["version"] != 1
            or len(plan["run_id"]) != 32
            or plan["selected"] != [n for n in ORDER if n in plan["selected"]]
            or not plan["selected"]
        ):
            raise ValueError
        if key_identity(key_file or plan["key_file"]) != plan["key_identity"]:
            _fail("deployment key identity changed")
        for name, digest in plan["artifacts"].items():
            path = root / name
            if (
                Path(name).is_absolute()
                or not path.resolve().is_relative_to(root)
                or path.is_symlink()
                or hashlib.sha256(_raw(path)).hexdigest() != digest
            ):
                _fail("immutable session artifacts changed")
        for value in [plan["source"], *plan["stages"].values()]:
            if Path(value).is_absolute() or not (root / value).resolve().is_relative_to(root):
                _fail("invalid session path")
        plan["source"] = str(root / plan["source"])
        plan["stages"] = {name: str(root / value) for name, value in plan["stages"].items()}
        plan["key_file"] = str(Path(key_file or plan["key_file"]).absolute())
        return plan
    except (KeyError, ValueError, TypeError):
        _fail("invalid plan or artifacts")


def read_journal(session):
    journal = _json(Path(session) / "journal.json")
    if (
        journal.get("version") != 1
        or journal.get("phase") not in _PHASES
        or not isinstance(journal.get("components"), dict)
    ):
        _fail("invalid progress journal")
    return journal


def mark_phase(session, phase, **changes):
    if phase not in _PHASES or set(changes) - {"consumers_stopped", "current", "reason", "action"}:
        _fail("invalid progress transition")
    journal = read_journal(session)
    previous = journal["phase"]
    transitions = {
        "PREFLIGHT_OK": {"PREPARED", "PREFLIGHT_OK", "NEEDS_ATTENTION"},
        "MAINTENANCE_CONFIRMED": _PHASES - {"PREPARED", "COMPLETE"},
        "CONSUMERS_STOPPED": {"MAINTENANCE_CONFIRMED", "CONSUMERS_STOPPED"},
        "ALL_VERIFIED": {"CONSUMERS_STOPPED", "CHANGING", "ALL_VERIFIED"},
        "ACTIVATING": {"ALL_VERIFIED", "ACTIVATING"},
        "SERVICES_READY": {"ACTIVATING", "SERVICES_READY"},
        "COMPLETE": {"SERVICES_READY", "COMPLETE"},
        "NEEDS_ATTENTION": _PHASES - {"COMPLETE"},
    }
    if previous not in transitions.get(phase, set()):
        _fail("global verification cannot be skipped")
    if phase in {"ALL_VERIFIED", "ACTIVATING", "SERVICES_READY", "COMPLETE"} and any(
        item["phase"] != "FILES_PERSISTED" for item in journal["components"].values()
    ):
        _fail("targets have not all been persisted and verified")
    if phase == "CONSUMERS_STOPPED":
        changes["consumers_stopped"] = True
    journal.update(changes)
    journal["phase"] = phase
    journal["sequence"] += 1
    atomic_json(Path(session) / "journal.json", journal)


def record_component(session, component, phase):
    plan = read_plan(session)
    journal = read_journal(session)
    if journal["phase"] not in {"CONSUMERS_STOPPED", "CHANGING"} or not journal["consumers_stopped"]:
        _fail("maintenance and consumer pause required before account changes")
    if component not in plan["selected"] or phase not in _COMPONENT_PHASES:
        _fail("invalid component transition")
    for name in plan["selected"]:
        if name == component:
            break
        if journal["components"][name]["phase"] != "FILES_PERSISTED":
            _fail("previous target has not been verified")
    old = journal["components"][component]["phase"]
    old_index, new_index = _COMPONENT_PHASES.index(old), _COMPONENT_PHASES.index(phase)
    if old_index > new_index:
        return
    if new_index > old_index + 1:
        _fail("component verification cannot be skipped")
    journal["components"][component]["phase"] = phase
    journal["current"] = component
    journal["phase"] = "CHANGING"
    journal["sequence"] += 1
    atomic_json(Path(session) / "journal.json", journal)


def record_account(session, component, account, phase):
    if phase not in ("INTENT", "VERIFIED") or not isinstance(account, str):
        _fail("invalid account checkpoint")
    journal = read_journal(session)
    journal["components"][component]["accounts"][account] = phase
    journal["sequence"] += 1
    atomic_json(Path(session) / "journal.json", journal)


def resume_decision(new, old):
    if new == "UNKNOWN" or old == "UNKNOWN":
        return "STOP"
    return {("OK", "DENIED"): "PERSIST", ("DENIED", "OK"): "APPLY", ("OK", "OK"): "DUAL"}.get((new, old), "STOP")


def _policy_mac(payload, key_file):
    key = _json(key_file)["keys"][0].encode()
    return hmac.new(
        key, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256
    ).hexdigest()


def write_deployment_policy(session, *, key_file=None):
    plan = read_plan(session, key_file=key_file)
    journal = read_journal(session)
    if any(item["phase"] != "FILES_PERSISTED" for item in journal["components"].values()):
        _fail("all native targets must be verified before policy activation")
    final = Path(plan["stages"][plan["selected"][-1]])
    _, manifest, pending = check_bundle(final, env_file=Path(session) / "env.before")
    if set(pending) != set(plan["retained_pending"]):
        _fail("unexpected pending credentials")
    source = Path(plan["source"])
    _, original, _ = check_bundle(source, env_file=Path(session) / "env.before")
    preserve_native = plan.get("preserve_native", original["mode"] == "adopt-key")
    if (source / "deployment-policy.json").exists():
        preserve_native = validate_deployment_policy(
            source, key_file=plan["key_file"], env_file=Path(session) / "env.before"
        )["preserve_native"]
    payload = {
        "version": 1,
        "revision": manifest["revision"],
        "key_identity": plan["key_identity"],
        "baseline": str(source),
        "baseline_hashes": _hashes(source),
        "bundle_hashes": {k: v for k, v in _hashes(final).items() if k != "deployment-policy.json"},
        "retained_pending": pending,
        "selected": plan["selected"],
        "preserve_native": preserve_native,
        "run_id": plan["run_id"],
    }
    atomic_json(final / "deployment-policy.json", {"payload": payload, "mac": _policy_mac(payload, plan["key_file"])})
    return final


def validate_deployment_policy(bundle, *, key_file, env_file=None):
    document = _json(Path(bundle) / "deployment-policy.json")
    try:
        payload = document["payload"]
        if (
            not hmac.compare_digest(document["mac"], _policy_mac(payload, key_file))
            or payload["version"] != 1
            or payload["key_identity"] != key_identity(key_file)
        ):
            _fail("deployment policy signature/key mismatch")
        actual = {k: v for k, v in _hashes(bundle).items() if k != "deployment-policy.json"}
        if actual != payload["bundle_hashes"] or _hashes(payload["baseline"]) != payload["baseline_hashes"]:
            _fail("deployment policy baseline or bundle changed")
        _, manifest, pending = check_bundle(bundle, env_file=env_file)
        # retained_pending is the frozen governance set at policy write time.
        # Live pending may shrink when passwords are strengthened or input rules
        # relax; that must not block reuse. Newly weak items outside the freeze,
        # or overlap with selected rotations, remain a scope failure.
        retained = set(payload["retained_pending"])
        if (
            manifest["revision"] != payload["revision"]
            or set(pending) - retained
            or set(pending) & set(payload["selected"])
        ):
            _fail("deployment policy credential scope mismatch")
        return payload
    except CredentialConfigurationError:
        raise
    except (KeyError, TypeError, ValueError):
        _fail("invalid deployment policy")


def prepare_rollback(session, *, out_dir, key_file, installer_root, secret_gid="0"):
    """Prepare an explicit paired return for a sealed, paused managed plan.

    Existing input validation deliberately forbids restoring weak passwords.
    Such legacy incidents retain maintenance and use resume, rather than an
    implicit downgrade or a whole-database restore.
    """
    from bisheng.core.config.credential_inputs import is_weak

    plan = read_plan(session, key_file=key_file)
    journal = read_journal(session)
    if not journal["consumers_stopped"] or journal["phase"] == "COMPLETE":
        _fail("rollback requires an incomplete paused plan")
    original, manifest, _ = check_bundle(plan["source"], env_file=Path(session) / "env.before")
    old = credentials(original)
    if any(is_weak(old[name], name) for name in plan["selected"]):
        _fail(
            "restoring selected weak legacy passwords is unsupported; resume the saved plan or obtain specialist recovery"
        )
    if plan.get("rollback_of"):
        _fail("nested rollback is unsupported")
    parent = Path(out_dir).parent
    inputs = parent / (".rollback-inputs-" + uuid.uuid4().hex)
    inputs.mkdir(mode=0o700)
    try:
        atomic_json(
            inputs / ".artifact-context.json",
            {"version": 2, "revision": uuid.uuid4().hex, "deployment_id": manifest["deployment_id"]},
        )
        request = {"version": 1}
        for name in plan["selected"]:
            filename = name + ".password"
            write_confidential(inputs / filename, old[name], key_file=key_file)
            request[name] = {"secret_key_file" if name == "minio" else "password_file": filename}
        write_private(inputs / "request.yaml", yaml.safe_dump(request))
        inventory = _json(Path(session) / "inventory.json")
        inventory["native_files"] = {}
        atomic_json(inputs / "inventory.json", inventory)
        target = prepare_rotation(
            base_bundle=plan["stages"][plan["selected"][-1]],
            key_file=key_file,
            inputs=inputs / "request.yaml",
            out_dir=out_dir,
            env_file=Path(session) / "env.before",
            inventory_file=inputs / "inventory.json",
            installer_root=installer_root,
            secret_gid=secret_gid,
            rollback_session=session,
        )
        data = _json(target / "plan.json")
        data["rollback_of"] = plan["run_id"]
        data["preserve_native"] = manifest["mode"] == "adopt-key"
        if (Path(plan["source"]) / "deployment-policy.json").exists():
            data["preserve_native"] = validate_deployment_policy(
                plan["source"], key_file=key_file, env_file=Path(session) / "env.before"
            )["preserve_native"]
        data["request_digest"] = plan["request_digest"]
        atomic_json(target / "plan.json", data)
        return target
    finally:
        shutil.rmtree(inputs)
