"""Pure rewrap planning and durable recovery records containing ciphertext only."""

from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path

from bisheng.core.config.credential_inputs import write_private
from bisheng.core.config.secret_crypto import CredentialConfigurationError, CredentialDecryptionError


def record_token(kind, value):
    if kind == "org_sync":
        if value is not None and not isinstance(value, str):
            raise CredentialConfigurationError("rewrap: invalid organization credential structure")
        return value or ""
    if kind != "sandbox":
        raise CredentialConfigurationError("rewrap: unknown target")
    if not value:
        return ""
    try:
        payload = json.loads(value)
        token = payload.get("token_enc", "")
        if not isinstance(payload, dict) or not isinstance(token, str):
            raise ValueError
        return token
    except (ValueError, TypeError, AttributeError):
        raise CredentialConfigurationError("rewrap: invalid sandbox credential structure") from None


def plan_records(records, ring, *, primary_only=False):
    plan = []
    for row in records:
        token = record_token(row["kind"], row.get("value"))
        if not token:
            continue
        try:
            plain = ring.decrypt_primary(token) if primary_only else ring.decrypt(token)
        except CredentialDecryptionError:
            raise CredentialConfigurationError(
                f"rewrap: {row['kind']} id={row['id']} ciphertext cannot be decrypted"
            ) from None
        if row["kind"] == "org_sync":
            try:
                if not isinstance(json.loads(plain), dict):
                    raise ValueError
            except (ValueError, TypeError):
                raise CredentialConfigurationError("rewrap: organization plaintext must be a JSON object") from None
        try:
            ring.decrypt_primary(token)
            continue
        except CredentialDecryptionError:
            new = ring.encrypt(plain).decode()
        plan.append({"kind": row["kind"], "id": row["id"], "tenant_id": row.get("tenant_id"), "old": token, "new": new})
    return plan


def current_state(entry, token):
    if token == entry["new"]:
        return "NEW"
    if token == entry["old"]:
        return "OLD"
    raise CredentialConfigurationError(
        f"rewrap: {entry['kind']} id={entry['id']} concurrent or missing credential; recovery stopped"
    )


def replace_record(kind, value, token):
    if kind == "org_sync":
        return token
    payload = json.loads(value)
    payload["token_enc"] = token
    return json.dumps(payload, ensure_ascii=False)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_journal(directory, phase, completed):
    root = Path(directory)
    temp = root / (".journal-" + uuid.uuid4().hex)
    try:
        write_private(temp, json.dumps({"version": 1, "phase": phase, "completed": completed}))
        os.replace(temp, root / "journal.json")
        _sync_dir(root)
    finally:
        temp.unlink(missing_ok=True)


def backup_plan(directory, plan):
    root = Path(directory).absolute()
    if not root.parent.is_dir():
        raise CredentialConfigurationError("rewrap: create the private backup parent before apply")
    try:
        root.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        raise CredentialConfigurationError("rewrap: backup directory already exists; use resume") from None
    # All ciphertext is durable BEFORE the first database update. On I/O failure
    # retain evidence and refuse any write; operators inspect the incomplete dir.
    write_private(root / "plan.json", json.dumps({"version": 1, "entries": plan}, ensure_ascii=False))
    write_journal(root, "PREPARED", 0)
    _sync_dir(root.parent)


def load_plan(directory):
    root = Path(directory)
    try:
        for path in (root, root / "plan.json", root / "journal.json"):
            if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise ValueError
        doc = json.loads((root / "plan.json").read_text())
        journal = json.loads((root / "journal.json").read_text())
        if doc["version"] != 1 or journal["version"] != 1 or not isinstance(doc["entries"], list):
            raise ValueError
        for entry in doc["entries"]:
            if set(entry) != {"kind", "id", "tenant_id", "old", "new"} or entry["kind"] not in ("org_sync", "sandbox"):
                raise ValueError
            if type(entry["id"]) is not int or not all(isinstance(entry[x], str) and entry[x] for x in ("old", "new")):
                raise ValueError
        return doc["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        raise CredentialConfigurationError("rewrap: invalid or unsafe recovery records") from None
