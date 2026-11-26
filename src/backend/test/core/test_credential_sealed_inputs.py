"""Encrypted interactive input is never staged as a plaintext password file."""

import json
import secrets

import pytest
import yaml
from cryptography.fernet import Fernet

from bisheng.core.config.credential_artifact_cli import seal_input_value
from bisheng.core.config.credential_inputs import read_inputs, validate_password
from bisheng.core.config.secret_crypto import CredentialConfigurationError


@pytest.fixture
def input_context(tmp_path, monkeypatch):
    key = tmp_path / "keys.json"
    key.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    key.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(key))
    monkeypatch.setenv("BS_CREDENTIAL_DEPLOYMENT_ID", "input-deployment")
    return key, tmp_path


def test_sealed_input_can_be_validated_without_plaintext_file(input_context):
    key, root = input_context
    value = secrets.token_urlsafe(24)
    p = root / "mysql.password"
    seal_input_value(value.encode(), p, key_file=key, deployment="input-deployment", component="mysql")
    request = root / "inputs.yaml"
    request.write_text(yaml.safe_dump({"version": 1, "mysql": {"password_file": p.name}}))
    assert value.encode() not in p.read_bytes()
    assert read_inputs(request, allow_plaintext=False)["mysql"]["password"] == value


def test_placeholder_input_does_not_write_partial_file(input_context):
    key, root = input_context
    p = root / "mysql.password"
    with pytest.raises(CredentialConfigurationError, match="placeholder"):
        seal_input_value(b"<password>", p, key_file=key, deployment="input-deployment", component="mysql")
    assert not p.exists()
    assert not list(root.glob(".sealed-*"))


@pytest.mark.parametrize("component", ["mysql", "redis", "elasticsearch", "milvus", "telemetry_elasticsearch"])
@pytest.mark.parametrize("password", ["123456", "654321", "abcdef", "!!!!!!"])
def test_six_character_password_without_character_classes_is_accepted(input_context, component, password):
    key, root = input_context
    path = root / (component + ".password")
    seal_input_value(password.encode(), path, key_file=key, deployment="input-deployment", component=component)
    assert password.encode() not in path.read_bytes()
    assert validate_password(password, component) == password


@pytest.mark.parametrize("component", ["mysql", "redis", "minio", "elasticsearch", "milvus", "telemetry_elasticsearch"])
def test_five_character_password_is_rejected_before_writing(input_context, component):
    key, root = input_context
    path = root / (component + ".password")
    with pytest.raises(CredentialConfigurationError, match="at least 6"):
        seal_input_value(b"54321", path, key_file=key, deployment="input-deployment", component=component)
    assert not path.exists()


@pytest.mark.parametrize("password", ["87654321", "abcdefgh", "!!!!!!!!"])
def test_minio_native_eight_character_limit_is_enforced(input_context, password):
    key, root = input_context
    path = root / "minio.password"
    for short in (b"654321", b"7654321"):
        with pytest.raises(CredentialConfigurationError, match="at least 8"):
            seal_input_value(short, path, key_file=key, deployment="input-deployment", component="minio")
    assert not path.exists()
    seal_input_value(password.encode(), path, key_file=key, deployment="input-deployment", component="minio")
    assert password.encode() not in path.read_bytes()


def test_plaintext_is_only_an_explicit_import(input_context):
    _, root = input_context
    p = root / "redis.password"
    p.write_text(secrets.token_urlsafe(24))
    request = root / "inputs.yaml"
    request.write_text(yaml.safe_dump({"version": 1, "redis": {"password_file": p.name}}))
    with pytest.raises(CredentialConfigurationError):
        read_inputs(request, allow_plaintext=False)
    assert read_inputs(request, allow_plaintext=True)["redis"]["password"] == p.read_text()


def test_input_cannot_be_used_in_another_deployment(input_context, monkeypatch):
    key, root = input_context
    p = root / "milvus.password"
    seal_input_value(b"milvus-test-new-secret", p, key_file=key, deployment="input-deployment", component="milvus")
    request = root / "inputs.yaml"
    request.write_text(yaml.safe_dump({"version": 1, "milvus": {"password_file": p.name}}))
    monkeypatch.setenv("BS_CREDENTIAL_DEPLOYMENT_ID", "other-deployment")
    with pytest.raises(CredentialConfigurationError):
        read_inputs(request, allow_plaintext=False)
