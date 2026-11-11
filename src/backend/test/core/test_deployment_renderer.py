"""F009 AC-12/16/18/21: production configuration from mounted Secrets."""

from urllib.parse import unquote, urlparse

import pytest
from sqlalchemy.engine import make_url

from bisheng.core.config.deployment_renderer import render_settings, write_private
from bisheng.core.config.settings import decrypt_database_url, decrypt_redis_url


def test_secret_passwords_round_trip_with_reserved_characters(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("a@:/?#% password")
    document = {
        "settings": {"app_runtime": {"enabled": False}},
        "database": {
            "driver": "mysql+pymysql",
            "host": "mysql",
            "port": 3306,
            "name": "bisheng",
            "username": "app",
            "password_file": str(secret),
        },
        "redis": {"host": "redis", "port": 6379, "password_file": str(secret), "cacheDb": 1, "celeryDb": 2},
    }
    result = render_settings(document)
    assert make_url(decrypt_database_url(result["database_url"])).password == secret.read_text()
    assert unquote(urlparse(decrypt_redis_url(result["redis_url"])).password) == secret.read_text()
    assert result["app_runtime"]["enabled"] is False
    assert "a@:/?#% password" not in str(result)


def test_nested_secret_files_are_not_environment_interpolation(tmp_path):
    secret = tmp_path / "token"
    secret.write_text("test-private-token")
    result = render_settings(
        {
            "settings": {"sandbox_conf": {"endpoints": ["http://runner:8080"]}},
            "secret_files": [{"path": ["sandbox_conf", "token"], "file": str(secret)}],
        }
    )
    assert result["sandbox_conf"]["token"] == "test-private-token"
    output = tmp_path / "private.yaml"
    write_private(output, result)
    assert output.stat().st_mode & 0o777 == 0o600


def test_invalid_binding_and_retired_admin_cannot_create_users(tmp_path):
    with pytest.raises(ValueError, match="binding"):
        render_settings({"settings": {}, "secret_files": [{"path": "x", "file": "missing"}]})
    assert "admin" not in render_settings({"settings": {"admin": {"password": "retired"}}})


def test_json_secret_binding_preserves_auth_array(tmp_path):
    secret = tmp_path / "basic-auth"
    secret.write_text('["elastic", "reserved:@password"]')
    result = render_settings(
        {
            "settings": {"vector_stores": {"elasticsearch": {"ssl_verify": {"verify_certs": True}}}},
            "secret_files": [
                {
                    "path": ["vector_stores", "elasticsearch", "ssl_verify", "basic_auth"],
                    "file": str(secret),
                    "encoding": "json",
                }
            ],
        }
    )
    assert result["vector_stores"]["elasticsearch"]["ssl_verify"] == {
        "verify_certs": True,
        "basic_auth": ["elastic", "reserved:@password"],
    }
