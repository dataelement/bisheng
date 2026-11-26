"""Configuration source and preflight contracts: AC-03/04/08/09/11/38."""

import json

import pytest
import yaml
from cryptography.fernet import Fernet

from bisheng.core.config import credential_loader as loader
from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring


def test_local_env_loader_and_sources(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("redis_url: !env ${CACHE_URL}\ncustom: [one, two]\n")
    doc = loader.load_config(path, environ={"CACHE_URL": "redis://redis/1"})
    assert doc.data["redis_url"] == "redis://redis/1"
    assert doc.sources[("redis_url",)] == "CACHE_URL"
    assert doc.data["custom"] == ["one", "two"]
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load("value: !env ${CACHE_URL}")


def test_missing_environment_does_not_show_input(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("password: !env ${MISSING}\n")
    with pytest.raises(CredentialConfigurationError, match="MISSING"):
        loader.load_config(path, environ={})


def test_invalid_yaml_and_duplicate_fields_are_redacted(tmp_path):
    for content in ["password: [secret-value", "password: secret-value\npassword: other\n"]:
        path = tmp_path / "config.yaml"
        path.write_text(content)
        with pytest.raises(CredentialConfigurationError) as caught:
            loader.load_config(path, environ={})
        assert "secret-value" not in str(caught.value)


def test_yaml_env_round_trip_preserves_references(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("endpoint: !env ${ENDPOINT}\n")
    doc = loader.load_config(path, environ={"ENDPOINT": "minio:9000"})
    dumped = loader.dump_document(doc.raw)
    assert "!env" in dumped and "ENDPOINT" in dumped


def test_dotenv_matches_single_line_rules_without_execution(tmp_path):
    path = tmp_path / "input.env"
    marker = tmp_path / "must-not-exist"
    path.write_text(f"export A='literal $HOME'\nB=unquoted # comment\nC=\"a$$b\\tend\"\nD=$(touch {marker})\n")
    data = loader.read_env_file(path)
    assert data["A"] == "literal $HOME"
    assert data["B"] == "unquoted"
    assert data["C"] == "a$b\tend"
    assert data["D"].startswith("$(touch ")
    assert not marker.exists()


@pytest.mark.parametrize("content", ["A=one\nA=two", 'A="bad\\nvalue"', "A='unterminated"])
def test_invalid_dotenv_rejected(tmp_path, content):
    path = tmp_path / "input.env"
    path.write_text(content)
    with pytest.raises(CredentialConfigurationError):
        loader.read_env_file(path)


def test_explicit_environment_conflict(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("value: !env ${VALUE}\n")
    env = tmp_path / "input.env"
    env.write_text("VALUE=file-value\n")
    with pytest.raises(CredentialConfigurationError, match="VALUE") as caught:
        loader.load_config(config, environ={"VALUE": "different-sensitive"}, env_file=env)
    assert "different-sensitive" not in str(caught.value)


def test_runtime_preflight_requires_key_and_database(tmp_path, monkeypatch):
    get_keyring.cache_clear()
    monkeypatch.delenv("BS_SECRET_KEYS_FILE", raising=False)
    with pytest.raises(CredentialConfigurationError):
        loader.validate_runtime({"database_url": "sqlite://"})
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    path.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    monkeypatch.delenv("bisheng_DATABASE_URL", raising=False)
    try:
        with pytest.raises(CredentialConfigurationError, match="database_url"):
            loader.validate_runtime({})
        assert loader.validate_runtime({"database_url": "sqlite://"}).database_url == "sqlite://"
    finally:
        get_keyring.cache_clear()


def test_runtime_preflight_ignores_unknown_top_level_keys_but_keeps_credential_checks(monkeypatch):
    warnings = []
    monkeypatch.setattr(loader.logger, "warning", lambda message, *args: warnings.append(message.format(*args)))
    settings = loader.validate_runtime(
        {"database_url": "sqlite://", "retired_section": {"token": "secret-value"}, "admin": {"password": "x"}}
    )
    assert settings.database_url == "sqlite://"
    assert len(warnings) == 1 and "retired_section" in warnings[0] and "secret-value" not in warnings[0]
    with pytest.raises(CredentialConfigurationError, match="secret_key") as error:
        loader.validate_runtime(
            {
                "database_url": "sqlite://",
                "unknown": 1,
                "object_storage": {"type": "minio", "minio": {"access_key": "u", "secret_key": "plain-secret"}},
            }
        )
    assert "plain-secret" not in str(error.value)


def test_legacy_database_file_source_is_materialized_when_yaml_omits_it(tmp_path):
    config = tmp_path / "source.yaml"
    config.write_text("redis_url: redis://redis/1\n")
    env = tmp_path / "deploy.env"
    env.write_text("bisheng_DATABASE_URL=mysql+pymysql://root:encrypted@mysql/db\n")
    document = loader.load_config(config, environ={}, env_file=env)
    assert document.data["database_url"].endswith("@mysql/db")
    assert document.sources[("database_url",)] == "bisheng_DATABASE_URL"
