"""Database URL passwords with special characters stay in the password field."""

import logging

import pytest
from cryptography.fernet import InvalidToken
from sqlalchemy.engine.url import make_url

from bisheng.core.config.settings import decrypt_database_url, encrypt_token
from bisheng.core.database.connection import DatabaseConnectionManager


def _encrypted_url(password: str, username: str = "user", host: str = "10.0.0.1") -> str:
    token = encrypt_token(password).decode()
    return f"mysql+pymysql://{username}:{token}@{host}:3306/app?charset=utf8mb4"


@pytest.mark.parametrize("password", ["p@ss", "a#b", "a/b", "a?b", "100%", "a b", "secret"])
def test_decrypt_database_url_round_trips_password(password):
    parsed = make_url(decrypt_database_url(_encrypted_url(password)))
    assert parsed.password == password
    assert parsed.host == "10.0.0.1"
    assert parsed.database == "app"
    assert parsed.query["charset"] == "utf8mb4"


def test_username_with_at_sign_is_unchanged():
    parsed = make_url(decrypt_database_url(_encrypted_url("secret", username="user@corp")))
    assert parsed.username == "user@corp"
    assert parsed.password == "secret"
    assert parsed.host == "10.0.0.1"


def test_alphanumeric_password_matches_previous_url_shape():
    rendered = decrypt_database_url(_encrypted_url("secret"))
    assert rendered == "mysql+pymysql://user:secret@10.0.0.1:3306/app?charset=utf8mb4"


def test_empty_password_is_not_decrypted():
    original = "mysql+pymysql://root:@127.0.0.1:3306/bisheng"
    assert decrypt_database_url(original) == original


def test_sqlite_url_is_unchanged():
    original = "sqlite:///./bisheng.db"
    assert decrypt_database_url(original) == original


def test_invalid_ciphertext_is_not_treated_as_plaintext():
    url = "mysql+pymysql://user:not-a-token@10.0.0.1:3306/app"
    with pytest.raises(InvalidToken):
        decrypt_database_url(url)


def test_async_driver_change_does_not_rewrite_password():
    mgr = DatabaseConnectionManager.__new__(DatabaseConnectionManager)
    mgr._engine = None
    mgr._async_engine = None
    rendered = mgr._convert_to_async_url("mysql+pymysql://user:pymysql@10.0.0.1/app")
    parsed = make_url(rendered)
    assert parsed.drivername == "mysql+aiomysql"
    assert parsed.password == "pymysql"
    assert parsed.host == "10.0.0.1"


def test_mysql_charset_uses_backend_name_not_password_text():
    mgr = DatabaseConnectionManager.__new__(DatabaseConnectionManager)
    mgr._engine = None
    mgr._async_engine = None
    mgr.database_url = "postgresql+psycopg2://user:mysql@10.0.0.1/app"
    assert "charset" not in mgr._get_default_engine_config().get("connect_args", {})

    mgr.database_url = "mysql+pymysql://user:secret@10.0.0.1/app"
    assert mgr._get_default_engine_config()["connect_args"]["charset"] == "utf8mb4"


def test_engine_creation_logs_hide_password(caplog):
    caplog.set_level(logging.DEBUG, logger="bisheng.core.database.connection")
    mgr = DatabaseConnectionManager("mysql+pymysql://user:p%40ss@10.0.0.1:3306/app")
    _ = mgr.engine
    _ = mgr.async_engine
    assert "p@ss" not in caplog.text
    assert "p%40ss" not in caplog.text
    assert "***" in caplog.text
