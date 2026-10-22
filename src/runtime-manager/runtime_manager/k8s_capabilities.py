"""Derive readiness from installer-owned, scoped live probe evidence.

The installer performs privileged and negative checks. The manager has no
permission to change that baseline or to replace unknown evidence with flags.
"""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

REQUIRED_CHECKS = frozenset(
    {
        "namespace-budget",
        "restricted-psa",
        "admission-create",
        "status-provenance",
        "binding-delete-fence",
        "rbac-namespace",
        "no-exec",
        "network-ingress",
        "network-direct-denied",
        "network-egress-allowed",
        "network-dns-denied",
        "storage-sqlite",
        "image-cri",
        "material-tls",
        "platform-capabilities",
    }
)
_REASON = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_EVIDENCE = {"uid", "control_uid", "resource_version", "profile", "policy_revision", "code", "digest"}


def descriptor_digest(document):
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in document.items() if key != "probe_report"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _check(raw, name):
    if not isinstance(raw, dict) or raw.get("name") != name or raw.get("ok") is not True:
        return {"name": name, "ok": False, "reason": "not_verified", "evidence": {}}
    evidence = raw.get("evidence")
    try:
        if not isinstance(evidence, dict) or str(UUID(evidence.get("uid", ""))) != evidence["uid"]:
            raise ValueError()
        safe = {
            key: value
            for key, value in evidence.items()
            if key in _EVIDENCE and isinstance(value, str) and len(value) <= 256 and "\n" not in value
        }
        reason = raw.get("reason", "verified")
        if not isinstance(reason, str) or not _REASON.fullmatch(reason):
            raise ValueError()
        return {"name": name, "ok": True, "reason": reason, "evidence": safe}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"name": name, "ok": False, "reason": "invalid_evidence", "evidence": {}}


def assess_capabilities(document, *, now):
    raw = document.get("probe_report") or {}
    valid = isinstance(raw, dict)
    observed = raw.get("observed_at") if valid else None
    valid = valid and type(observed) in {int, float} and 0 <= now - observed <= 86400
    valid = (
        valid and raw.get("source") == "cluster-probe" and raw.get("descriptor_digest") == descriptor_digest(document)
    )
    rows = raw.get("checks", []) if valid else []
    known = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("name"), str):
                name = row["name"]
                known[name] = (
                    _check(row, name)
                    if name not in known
                    else {"name": name, "ok": False, "reason": "duplicate_check", "evidence": {}}
                )
    checks = [_check(known.get(name), name) for name in sorted(REQUIRED_CHECKS)]
    storage = document.get("storage", {})
    storage_ok = storage.get("sqlite_compatible") is True and storage.get("filesystem", "").lower() not in {
        "nfs",
        "nfs4",
        "cifs",
        "smb",
        "smbfs",
    }
    if not storage_ok:
        checks = [
            item
            if item["name"] != "storage-sqlite"
            else {"name": "storage-sqlite", "ok": False, "reason": "storage_incompatible", "evidence": {}}
            for item in checks
        ]
    ready = bool(valid and all(item["ok"] for item in checks))
    registry = _check(known.get("registry-push"), "registry-push")["ok"]
    paths = {
        "bundle": ready,
        "image": ready,
        "source-image": ready
        and registry
        and bool(document.get("image_repository"))
        and bool(document.get("assembler_image")),
    }
    warnings = ["node_local_storage"] if storage.get("node_local") else []
    if not valid:
        warnings.append("live_probe_report_missing_stale_or_changed")
    return {"ready": ready, "observed_at": observed, "checks": checks, "paths": paths, "warnings": warnings}


def run_checks(drivers, *, observed_at):
    results = []
    for name, driver in sorted(drivers.items()):
        try:
            result = _check({"name": name, **driver()}, name)
        except Exception:
            result = {"name": name, "ok": False, "reason": "probe_failed", "evidence": {}}
        results.append({**result, "observed_at": observed_at})
    return results


def network_checks(plan):
    import socket

    if (
        not isinstance(plan, dict)
        or set(plan) != {"targets"}
        or not isinstance(plan["targets"], list)
        or len(plan["targets"]) > 32
    ):
        raise ValueError("probe_network_plan_invalid")
    results = []
    for target in plan["targets"]:
        if (
            set(target) != {"name", "host", "port", "expected"}
            or not _REASON.fullmatch(target["name"])
            or target["expected"] not in {"allowed", "denied"}
        ):
            raise ValueError("probe_network_target_invalid")
        if type(target["port"]) is not int or not 1 <= target["port"] <= 65535:
            raise ValueError("probe_network_port_invalid")
        try:
            with socket.create_connection((target["host"], target["port"]), timeout=1):
                reason, reached = "connected", True
        except TimeoutError:
            reason, reached = "timeout", False
        except OSError:
            # An inactive target is not evidence that a policy denied access.
            results.append({"name": target["name"], "ok": False, "reason": "target_unconfirmed"})
            continue
        results.append({"name": target["name"], "ok": reached is (target["expected"] == "allowed"), "reason": reason})
    return {"checks": results}


def storage_checks(volume):
    import fcntl
    import os
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from runtime_manager.appdb import AppDbSchemaService, integrity
    from runtime_manager.config import Config

    root = Path(volume)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("probe_storage_unavailable")
    with TemporaryDirectory(prefix="preflight-", dir=root) as temporary:
        temporary = Path(temporary)
        descriptor = os.open(temporary / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = os.fork()
            if child == 0:
                os.close(descriptor)
                try:
                    with (temporary / "lock").open("rb") as other:
                        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os._exit(0)
                os._exit(1)
            _, status = os.waitpid(child, 0)
            if status != 0:
                raise ValueError("probe_storage_lock_ineffective")
        finally:
            os.close(descriptor)
        config = Config(data_root=temporary)
        AppDbSchemaService(config).migrate(
            "preflight",
            [
                {
                    "op": "create_table",
                    "table": "probe",
                    "columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
                }
            ],
        )
        database = config.app_data_dir("preflight") / "app.db"
        integrity(database)
        with database.open("rb") as source:
            os.fsync(source.fileno())
        directory = os.open(database.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return {"locking": True, "fsync": True, "sqlite_integrity": True}


def main():
    import os
    import sys

    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "network":
        result = network_checks(json.loads(os.environ["CAPABILITY_PLAN"]))
    elif action == "storage":
        result = storage_checks("/probe-volume")
    else:
        raise ValueError("probe_action_invalid")
    print("BISHENG_RUNTIME_RESULT " + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Runtime capability probe failed (" + type(exc).__name__ + ")", flush=True)
        raise SystemExit(1) from None
