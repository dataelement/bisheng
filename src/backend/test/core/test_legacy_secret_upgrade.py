"""Image-only upgrade from feat/3.1.0-beta1: unset BS_SECRET_KEYS_FILE → legacy."""

import json
import pickle
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine.url import make_url

from bisheng.core.cache import serialization as codec
from bisheng.core.config import secret_crypto as sc
from bisheng.core.config.settings import (
    MinioConf,
    _credential,
    decrypt_database_url,
    decrypt_redis_url,
)


@pytest.fixture
def legacy_mode(monkeypatch):
    monkeypatch.delenv("BS_SECRET_KEYS_FILE", raising=False)
    sc.get_keyring.cache_clear()
    yield
    sc.get_keyring.cache_clear()


@pytest.fixture
def managed_mode(tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
    path.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    sc.get_keyring.cache_clear()
    yield path
    sc.get_keyring.cache_clear()


def test_unset_key_file_is_legacy(legacy_mode):
    assert sc.secret_mode() == "legacy"
    assert sc.is_legacy_secret_mode() is True
    ring = sc.get_keyring()
    token = ring.encrypt("1234")
    assert ring.decrypt(token) == "1234"


def test_legacy_decrypts_beta1_mysql_url_ciphertext(legacy_mode):
    # Same ciphertext as docker/bisheng/config/config.yaml on feat/3.1.0-beta1 (password 1234).
    url = (
        "mysql+pymysql://root:gAAAAABlp4b4c59FeVGF_OQRVf6NOUIGdxq8246EBD-b0hdK_jVKRs1x4PoAn0A6"
        "C5S6IiFKmWn0Nm5eBUWu-7jxcqw6TiVjQA==@mysql:3306/bisheng?charset=utf8mb4"
    )
    plain = decrypt_database_url(url)
    assert make_url(plain).password == "1234"


def test_legacy_accepts_plaintext_mysql_and_redis_url_passwords(legacy_mode):
    assert make_url(decrypt_database_url("mysql+pymysql://root:plainpass@mysql:3306/bisheng")).password == "plainpass"
    assert "plainpass" in decrypt_redis_url("redis://:plainpass@redis:6379/1")


def test_legacy_accepts_plaintext_minio_secret(legacy_mode):
    conf = MinioConf(secret_key="minioadmin", access_key="minioadmin")
    assert conf.secret_key == "minioadmin"
    assert _credential("elastic-password", "elasticsearch.basic_auth") == "elastic-password"
    assert _credential("", "milvus.password") == ""


def test_legacy_redis_cache_uses_pickle(legacy_mode):
    raw = codec.encode_redis_value("session", {"user": 1})
    assert not raw.startswith(codec._PREFIX)
    assert codec.decode_redis_value("session", raw) == {"user": 1}
    assert codec.decode_redis_value("session", pickle.dumps({"user": 1})) == {"user": 1}


def test_managed_still_requires_encrypt_wrapper(managed_mode):
    assert sc.secret_mode() == "managed"
    with pytest.raises(sc.CredentialConfigurationError, match="encrypted credential required"):
        _credential("minioadmin", "minio.secret_key")


def test_managed_rejects_empty_key_file_path_as_invalid_not_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(tmp_path / "missing.json"))
    sc.get_keyring.cache_clear()
    with pytest.raises(sc.CredentialConfigurationError, match="cannot be read"):
        sc.get_keyring()


def test_managed_primary_still_refuses_public_historical_key(tmp_path):
    root = Path(__file__).resolve().parents[4]
    import ast
    import subprocess

    source = subprocess.check_output(
        ["git", "show", "13440057e988990a7217b4b498f6358ecc96f766:src/backend/bisheng/core/config/settings.py"],
        cwd=root,
        text=True,
    )
    public = next(
        ast.literal_eval(n.value)
        for n in ast.parse(source).body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "secret_key" for t in n.targets)
    )
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 1, "keys": [public]}))
    path.chmod(0o600)
    with pytest.raises(sc.CredentialConfigurationError, match="public historical primary refused"):
        sc.load_keyring(path)
