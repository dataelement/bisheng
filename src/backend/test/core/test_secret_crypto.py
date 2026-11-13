"""External key lifecycle and fail-closed credential encryption.

Coverage: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-30.
All key material is generated in temporary files, never a production constant.
"""

import json
import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet, InvalidToken

from bisheng.core.config import secret_crypto


@pytest.fixture(autouse=True)
def isolate_runtime_keyring(monkeypatch):
    monkeypatch.delenv("BS_SECRET_KEYS_FILE", raising=False)
    secret_crypto.get_keyring.cache_clear()
    yield
    secret_crypto.get_keyring.cache_clear()


@pytest.fixture
def keyfile(tmp_path):
    def create(keys=None, name="keyring.json"):
        keys = keys if keys is not None else [Fernet.generate_key()]
        path = tmp_path / name
        path.write_text(json.dumps({"version": 1, "keys": [k.decode() for k in keys]}))
        path.chmod(0o600)
        return path

    return create


def test_no_key_path_never_uses_default():
    with pytest.raises(secret_crypto.CredentialConfigurationError, match="BS_SECRET_KEYS_FILE"):
        secret_crypto.encrypt_token("credential")


def test_import_does_not_require_or_generate_key(tmp_path, monkeypatch):
    workdir = tmp_path / "untouched-runtime"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    assert list(workdir.iterdir()) == []
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.get_keyring()
    assert list(workdir.iterdir()) == []


def test_relative_path_is_rejected(keyfile, monkeypatch):
    path = keyfile()
    monkeypatch.chdir(path.parent)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", path.name)
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.get_keyring()


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.load_keyring(tmp_path / "missing")


@pytest.mark.parametrize("mode", [0o604, 0o606, 0o620, 0o666])
def test_unsafe_permissions_rejected(keyfile, mode):
    path = keyfile()
    path.chmod(mode)
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.load_keyring(path)


def test_group_read_for_secret_volume_is_supported(keyfile):
    path = keyfile()
    path.chmod(0o640)
    ring = secret_crypto.load_keyring(path)
    assert ring.decrypt(ring.encrypt("credential")) == "credential"


def test_symlink_secret_volume_is_supported(keyfile):
    target = keyfile()
    link = target.parent / "mounted-secret"
    link.symlink_to(target)
    ring = secret_crypto.load_keyring(link)
    assert ring.decrypt(ring.encrypt("credential")) == "credential"


def test_file_read_failure_is_redacted(keyfile, monkeypatch):
    path = keyfile()

    def denied(*args, **kwargs):
        raise PermissionError("upstream includes confidential input")

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(secret_crypto.CredentialConfigurationError) as caught:
        secret_crypto.load_keyring(path)
    assert "confidential input" not in str(caught.value)


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "[]",
        '{"version":true,"keys":[]}',
        '{"version":2,"keys":[]}',
        '{"version":1,"keys":[]}',
        '{"version":1,"keys":"not-an-array"}',
        '{"version":1,"keys":[null]}',
        '{"version":1,"keys":["invalid-sensitive-key"]}',
        '{"version":1,"version":1,"keys":[]}',
    ],
)
def test_malformed_keyring_rejected_without_input(tmp_path, content):
    path = tmp_path / "keyring.json"
    path.write_text(content)
    path.chmod(0o600)
    with pytest.raises(secret_crypto.CredentialConfigurationError) as caught:
        secret_crypto.load_keyring(path)
    assert content not in str(caught.value)
    assert "invalid-sensitive-key" not in str(caught.value)


def test_duplicate_keys_rejected(keyfile):
    key = Fernet.generate_key()
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.load_keyring(keyfile([key, key]))


def test_binary_keyfile_is_rejected(keyfile):
    path = keyfile()
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.load_keyring(path)


def test_separate_deployments_cannot_decrypt_each_other(keyfile):
    first = secret_crypto.load_keyring(keyfile(name="first.json"))
    second = secret_crypto.load_keyring(keyfile(name="second.json"))
    token = first.encrypt("credential")
    with pytest.raises(secret_crypto.CredentialDecryptionError):
        second.decrypt(token)


def test_rotation_reads_old_and_writes_only_current(keyfile):
    current, old = Fernet.generate_key(), Fernet.generate_key()
    ring = secret_crypto.load_keyring(keyfile([current, old]))
    old_token = Fernet(old).encrypt("original-凭据".encode())
    assert ring.decrypt(old_token) == "original-凭据"
    new_token = ring.encrypt("original-凭据")
    assert Fernet(current).decrypt(new_token).decode() == "original-凭据"
    with pytest.raises(InvalidToken):
        Fernet(old).decrypt(new_token)
    assert ring.decrypt_primary(new_token) == "original-凭据"
    with pytest.raises(secret_crypto.CredentialDecryptionError):
        ring.decrypt_primary(old_token)


@pytest.mark.parametrize("value", ["p@ss:/#%$", " leading and trailing ", "中文密码"])
def test_compatibility_functions_preserve_types_and_text(keyfile, monkeypatch, value):
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(keyfile()))
    token = secret_crypto.encrypt_token(value)
    assert isinstance(token, bytes)
    assert secret_crypto.decrypt_token(token) == value
    assert secret_crypto.decrypt_token(token.decode()) == value


def test_current_process_keeps_snapshot_until_explicit_restart(keyfile, monkeypatch):
    path = keyfile()
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    first = secret_crypto.get_keyring()
    token = first.encrypt("credential")
    keyfile(name=path.name)
    assert secret_crypto.get_keyring() is first
    assert secret_crypto.decrypt_token(token) == "credential"
    # Clearing the cache simulates starting a fresh process after deployment.
    secret_crypto.get_keyring.cache_clear()
    with pytest.raises(secret_crypto.CredentialDecryptionError):
        secret_crypto.decrypt_token(token)


def test_snapshot_does_not_accept_env_path_changes(keyfile, monkeypatch):
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(keyfile(name="first.json")))
    first = secret_crypto.get_keyring()
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(keyfile(name="second.json")))
    assert secret_crypto.get_keyring() is first


def test_damaged_tokens_do_not_fall_back_to_plaintext(keyfile):
    ring = secret_crypto.load_keyring(keyfile())
    for value in ["plain-sensitive-password", "坏密文", b"", None]:
        with pytest.raises(secret_crypto.CredentialDecryptionError) as caught:
            ring.decrypt(value)
        assert "plain-sensitive-password" not in str(caught.value)
        assert "坏密文" not in str(caught.value)


def test_exception_remains_compatible_with_invalid_token(keyfile):
    ring = secret_crypto.load_keyring(keyfile())
    with pytest.raises(InvalidToken):
        ring.decrypt("invalid")


def test_no_key_material_in_representation(keyfile):
    key = Fernet.generate_key()
    ring = secret_crypto.load_keyring(keyfile([key]))
    assert key.decode() not in repr(ring)


def test_nonregular_file_rejected(tmp_path):
    with pytest.raises(secret_crypto.CredentialConfigurationError):
        secret_crypto.load_keyring(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes required")
def test_named_pipe_is_rejected_without_waiting_for_a_writer(tmp_path):
    path = tmp_path / "not-a-key-file"
    os.mkfifo(path, 0o600)
    code = """
import sys
from bisheng.core.config.secret_crypto import load_keyring, CredentialConfigurationError
try:
    load_keyring(sys.argv[1])
except CredentialConfigurationError:
    raise SystemExit(0)
raise SystemExit(1)
"""
    completed = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, timeout=3, check=False)
    assert completed.returncode == 0
