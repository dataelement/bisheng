"""AC-28..35: rewrap keeps logical values and resumes from durable ciphertext."""

import json

import pytest
from cryptography.fernet import Fernet

from bisheng.core.config.credential_rewrap import backup_plan, current_state, load_plan, plan_records, write_journal
from bisheng.core.config.secret_crypto import CredentialConfigurationError, load_keyring


def ring(tmp_path):
    p = tmp_path / "keys.json"
    # Generate the external ring directly, never use application defaults.
    old_key = Fernet.generate_key()
    old = Fernet(old_key)
    p.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode(), old_key.decode()]}))
    p.chmod(0o600)
    return load_keyring(p), old


def test_rewrap_preserves_unknown_json_and_primary_bytes(tmp_path):
    keys, old = ring(tmp_path)
    raw = json.dumps({"unknown": {"unicode": "你好"}, "api_key": "dynamic-value"})
    token = old.encrypt(raw.encode()).decode()
    records = [
        {"kind": "org_sync", "id": 7, "tenant_id": 3, "value": token},
        {
            "kind": "sandbox",
            "id": 1,
            "tenant_id": None,
            "value": json.dumps(
                {"token_enc": old.encrypt(b"token").decode(), "endpoints": ["https://runner"], "extra": 42}
            ),
        },
    ]
    plan = plan_records(records, keys)
    assert keys.decrypt_primary(plan[0]["new"]) == raw
    assert keys.decrypt_primary(plan[1]["new"]) == "token"
    assert plan_records([{"kind": "org_sync", "id": 7, "tenant_id": 3, "value": plan[0]["new"]}], keys) == []


def test_empty_skip_and_invalid_stops_before_backup(tmp_path):
    keys, _ = ring(tmp_path)
    assert plan_records([{"kind": "org_sync", "id": 1, "value": ""}], keys) == []
    for value in ("corrupt", keys.encrypt("[]").decode()):
        with pytest.raises(CredentialConfigurationError):
            plan_records([{"kind": "org_sync", "id": 1, "value": value}], keys)


def test_journal_lag_and_third_value(tmp_path):
    keys, old = ring(tmp_path)
    entry = plan_records([{"kind": "org_sync", "id": 1, "value": old.encrypt(b"{}").decode()}], keys)[0]
    assert current_state(entry, entry["old"]) == "OLD"
    assert current_state(entry, entry["new"]) == "NEW"
    with pytest.raises(CredentialConfigurationError):
        current_state(entry, "third-value")
    directory = tmp_path / "backup"
    backup_plan(directory, [entry])
    assert load_plan(directory) == [entry]
    assert (directory / "plan.json").stat().st_mode & 0o777 == 0o600
    write_journal(directory, "DB_COMPLETE_CACHE_PENDING", 1)
    assert json.loads((directory / "journal.json").read_text())["phase"] == "DB_COMPLETE_CACHE_PENDING"
    with pytest.raises(CredentialConfigurationError):
        backup_plan(directory, [entry])
