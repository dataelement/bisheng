"""F009 AC-12/16/18/21: production configuration from mounted Secrets."""

from urllib.parse import unquote, urlparse

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from bisheng.core.config.deployment_renderer import render_settings, write_private
from bisheng.core.config.settings import ElasticsearchConf, Settings, decrypt_database_url, decrypt_redis_url


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
    ssl_verify = result["vector_stores"]["elasticsearch"]["ssl_verify"]
    assert ssl_verify["verify_certs"] is True
    username, password = ssl_verify["basic_auth"]
    assert username == "elastic"
    assert password.startswith("encrypt(") and "reserved:@password" not in password
    conf = ElasticsearchConf(url="http://es:9200", ssl_verify=ssl_verify)
    assert conf.ssl_verify["basic_auth"] == ("elastic", "reserved:@password")


def _write(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(value)
    return str(path)


def test_strict_credential_bindings_are_sealed_and_accepted_by_settings(tmp_path):
    """Chart bindings must satisfy the beta2 loader, which rejects plaintext."""
    result = render_settings(
        {
            "settings": {
                "object_storage": {"type": "minio", "minio": {"endpoint": "minio:9000"}},
                "vector_stores": {"milvus": {"connection_args": {"host": "milvus", "port": "19530", "user": "root"}}},
                "sandbox_conf": {"endpoints": ["http://runner:8080"]},
            },
            "secret_files": [
                {"path": ["object_storage", "minio", "access_key"], "file": _write(tmp_path, "ak", "minio-user")},
                {"path": ["object_storage", "minio", "secret_key"], "file": _write(tmp_path, "sk", "minio:@secret")},
                {
                    "path": ["vector_stores", "milvus", "connection_args", "password"],
                    "file": _write(tmp_path, "mp", "milvus-secret"),
                },
                {"path": ["sandbox_conf", "token"], "file": _write(tmp_path, "st", "runner-token")},
            ],
        }
    )
    minio = result["object_storage"]["minio"]
    milvus = result["vector_stores"]["milvus"]["connection_args"]
    assert minio["access_key"] == "minio-user"
    for sealed in (minio["secret_key"], milvus["password"]):
        assert sealed.startswith("encrypt(") and sealed.endswith(")")
    assert "minio:@secret" not in str(result) and "milvus-secret" not in str(result)
    # Fields the loader keeps as plain text are not wrapped.
    assert result["sandbox_conf"]["token"] == "runner-token"

    output = tmp_path / "config.yaml"
    write_private(output, result)
    settings = Settings(**yaml.safe_load(output.read_text()))
    assert settings.object_storage.minio.secret_key == "minio:@secret"
    assert settings.vector_stores.milvus.connection_args["password"] == "milvus-secret"


def test_plaintext_strict_credential_is_still_rejected_by_settings():
    with pytest.raises(ValidationError, match="encrypted credential required"):
        Settings(object_storage={"type": "minio", "minio": {"access_key": "u", "secret_key": "plain"}})


def test_empty_strict_credential_stays_empty(tmp_path):
    result = render_settings(
        {
            "settings": {},
            "secret_files": [{"path": ["object_storage", "minio", "secret_key"], "file": _write(tmp_path, "sk", "")}],
        }
    )
    assert result["object_storage"]["minio"]["secret_key"] == ""


def test_malformed_basic_auth_binding_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="binding"):
        render_settings(
            {
                "settings": {},
                "secret_files": [
                    {
                        "path": ["vector_stores", "elasticsearch", "ssl_verify", "basic_auth"],
                        "file": _write(tmp_path, "ba", '"elastic:password"'),
                        "encoding": "json",
                    }
                ],
            }
        )
