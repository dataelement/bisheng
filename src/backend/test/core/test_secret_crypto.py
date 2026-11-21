"""Deployment keyring contract and public historical-key rejection."""

import json
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from bisheng.core.config.secret_crypto import CredentialConfigurationError, CredentialDecryptionError, load_keyring


def ring_file(tmp_path, keys):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"version": 1, "keys": [k.decode() for k in keys]}))
    path.chmod(0o600)
    return path


def test_bytes_text_and_primary_rotation(tmp_path):
    old, new = Fernet.generate_key(), Fernet.generate_key()
    ring = load_keyring(ring_file(tmp_path, [new, old]))
    token = ring.encrypt("中文:@")
    assert isinstance(token, bytes)
    assert ring.decrypt(token.decode()) == "中文:@"
    assert ring.decrypt_primary(token) == "中文:@"
    historical = Fernet(old).encrypt(b"migration")
    assert ring.decrypt(historical) == "migration"
    with pytest.raises(CredentialDecryptionError):
        ring.decrypt_primary(historical)


def test_public_historical_primary_is_migration_only(tmp_path):
    # Obtain the public historical value without embedding it in a new source file.
    root = Path(__file__).resolve().parents[4]
    source = subprocess.check_output(
        ["git", "show", "13440057e988990a7217b4b498f6358ecc96f766:src/backend/bisheng/core/config/settings.py"],
        cwd=root,
        text=True,
    )
    import ast

    public = next(
        ast.literal_eval(n.value)
        for n in ast.parse(source).body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "secret_key" for t in n.targets)
    ).encode()
    with pytest.raises(CredentialConfigurationError, match="public historical primary refused"):
        load_keyring(ring_file(tmp_path, [public]))
    ring = load_keyring(ring_file(tmp_path, [Fernet.generate_key(), public]))
    assert ring.decrypt(Fernet(public).encrypt(b"old credential")) == "old credential"


@pytest.mark.parametrize("mode", [0o644, 0o620, 0o666])
def test_unsafe_permissions_rejected(tmp_path, mode):
    path = ring_file(tmp_path, [Fernet.generate_key()])
    path.chmod(mode)
    with pytest.raises(CredentialConfigurationError, match="unsafe"):
        load_keyring(path)
