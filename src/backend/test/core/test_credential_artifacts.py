"""Authenticated disk artifacts and per-role keys, independent of application state."""

import json

import pytest
from cryptography.fernet import Fernet

from bisheng.core.config.credential_artifacts import (
    derive_keyring,
    open_artifact,
    read_private,
    seal_artifact,
    write_private_atomic,
)
from bisheng.core.config.secret_crypto import CredentialConfigurationError


@pytest.fixture
def master(tmp_path):
    p = tmp_path / "master.json"
    p.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    p.chmod(0o600)
    return p


def test_roundtrip_disk_contains_no_plaintext_and_tokens_are_random(master, tmp_path):
    values = {"mysql.password": b"unique-password-quote'\\$@-1234"}
    a = seal_artifact(values, master, role="mysql", revision="revision1", deployment="deployment1")
    b = seal_artifact(values, master, role="mysql", revision="revision1", deployment="deployment1")
    assert a != b and values["mysql.password"] not in a
    p = tmp_path / "sealed.json"
    write_private_atomic(p, a)
    assert open_artifact(read_private(p), master, role="mysql", revision="revision1", deployment="deployment1") == values
    assert p.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("field,value", [("role", "redis"), ("revision", "other"), ("deployment", "other")])
def test_identity_mismatch_cannot_be_rebound_by_changing_outer_metadata(master, field, value):
    raw = seal_artifact({"mysql.password": b"secret"}, master, role="mysql", revision="r", deployment="d")
    outer = json.loads(raw)
    if field != "deployment":
        outer[field] = value
    expected = {"role": "mysql", "revision": "r", "deployment": "d", field: value}
    with pytest.raises(CredentialConfigurationError):
        open_artifact(json.dumps(outer).encode(), master, **expected)


def test_role_key_cannot_decrypt_other_role(master, tmp_path):
    role = tmp_path / "role.json"
    write_private_atomic(role, json.dumps(derive_keyring(master, "redis")).encode())
    raw = seal_artifact({"mysql.password": b"secret"}, master, role="mysql", revision="r", deployment="d")
    with pytest.raises(CredentialConfigurationError):
        open_artifact(raw, role, role="mysql", revision="r", deployment="d", derived=True)
    redis = seal_artifact({"redis.password": b"secret"}, master, role="redis", revision="r", deployment="d")
    assert open_artifact(redis, role, role="redis", revision="r", deployment="d", derived=True)["redis.password"] == b"secret"


def test_tampered_token_and_duplicate_json_fields_fail_redacted(master):
    raw = seal_artifact({"mysql.password": b"secret-value"}, master, role="mysql", revision="r", deployment="d")
    outer = json.loads(raw)
    outer["token"] = outer["token"][:-8] + "XXXXXXXX"
    for content in [json.dumps(outer).encode(), b'{"format":"x",' + raw[1:]]:
        with pytest.raises(CredentialConfigurationError) as err:
            open_artifact(content, master, role="mysql", revision="r", deployment="d")
        assert "secret-value" not in str(err.value)


@pytest.mark.parametrize("name", ["../outside", "/etc/passwd", "a/../b", "a//b", "a/./b", "", "a\x00b"])
def test_unsafe_names_rejected_before_output(master, name):
    with pytest.raises(CredentialConfigurationError):
        seal_artifact({name: b"secret"}, master, role="mysql", revision="r", deployment="d")


def test_retiring_keys_and_role_derivation_are_stable(master):
    old = derive_keyring(master, "mysql")["keys"][0]
    raw = seal_artifact({"mysql.password": b"secret"}, master, role="mysql", revision="r", deployment="d")
    ring = json.loads(master.read_text())
    ring["keys"].insert(0, Fernet.generate_key().decode())
    write_private_atomic(master, json.dumps(ring).encode())
    assert derive_keyring(master, "mysql")["keys"][1] == old
    assert open_artifact(raw, master, role="mysql", revision="r", deployment="d")["mysql.password"] == b"secret"


def test_read_private_refuses_world_read_and_symlinks(master, tmp_path):
    master.chmod(0o644)
    with pytest.raises(CredentialConfigurationError):
        read_private(master)
    master.chmod(0o600)
    p = tmp_path / "link"
    p.symlink_to(master)
    with pytest.raises(CredentialConfigurationError):
        read_private(p)
    assert not list(tmp_path.glob(".sealed-*"))


def test_write_refuses_symlink_without_touching_target(master, tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"original")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(CredentialConfigurationError):
        write_private_atomic(link, b"replacement")
    assert target.read_bytes() == b"original"
