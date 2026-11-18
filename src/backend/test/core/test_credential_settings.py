"""Runtime credential parsing: AC-04/05/06/07/11/18/21/24/27."""

import copy
import json

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from bisheng.core.config import secret_crypto
from bisheng.core.config.settings import ElasticsearchConf, MilvusConf, MinioConf, Settings


@pytest.fixture(autouse=True)
def external_keys(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    path = tmp_path / "keyring.json"
    path.write_text(json.dumps({"version": 1, "keys": [key.decode()]}))
    path.chmod(0o600)
    monkeypatch.setenv("BS_SECRET_KEYS_FILE", str(path))
    secret_crypto.get_keyring.cache_clear()
    yield
    secret_crypto.get_keyring.cache_clear()


def sealed(value):
    return "encrypt(" + secret_crypto.encrypt_token(value).decode() + ")"


def test_mysql_uses_external_key():
    token = secret_crypto.encrypt_token("p@ss:/#%$").decode()
    settings = Settings(database_url=f"mysql+pymysql://root:{token}@mysql/bisheng")
    assert make_url(settings.database_url).password == "p@ss:/#%$"
    assert "p@ss" not in repr(settings)


def test_database_env_has_no_plaintext_bypass(monkeypatch):
    monkeypatch.setenv("bisheng_DATABASE_URL", "mysql+pymysql://root:sensitive-plaintext@mysql/bisheng")
    with pytest.raises((ValidationError, ValueError)) as error:
        Settings.set_database_url(None)
    assert "sensitive-plaintext" not in str(error.value)


@pytest.mark.parametrize("factory,field", [(MinioConf, "secret_key"), (MilvusConf, "password")])
def test_plaintext_credentials_rejected(factory, field):
    values = {field: "plain-sensitive-password"}
    if factory is MilvusConf:
        values = {"connection_args": values}
    with pytest.raises((ValueError, ValidationError)) as error:
        factory(**values)
    assert "plain-sensitive-password" not in str(error.value)


def test_minio_secret_decrypts_without_mutating_caller():
    value = sealed("secret-中文 @:/")
    conf = MinioConf(secret_key=value)
    assert conf.secret_key == "secret-中文 @:/"
    assert value.startswith("encrypt(")
    assert "secret-中文" not in repr(conf)
    assert MinioConf().secret_key is None


def test_milvus_json_password_and_existing_model_reuse():
    data = {"host": "milvus", "password": sealed("p@ss"), "user": "root"}
    original = copy.deepcopy(data)
    conf = MilvusConf(connection_args=json.dumps(data))
    assert conf.connection_args["password"] == "p@ss"
    assert MilvusConf.model_validate(conf) is conf
    assert MilvusConf(connection_args=conf.connection_args).connection_args["password"] == "p@ss"
    assert data == original
    assert "p@ss" not in repr(conf)


def test_milvus_token_and_password_conflict():
    with pytest.raises((ValueError, ValidationError)):
        MilvusConf(connection_args={"token": sealed("root:a"), "password": sealed("a")})


def test_milvus_token_decrypts():
    assert MilvusConf(connection_args={"token": sealed("root:p@ss")}).connection_args["token"] == "root:p@ss"


@pytest.mark.parametrize("string_form", [False, True])
def test_es_auth_decrypts_and_preserves_tls(string_form):
    data = {"basic_auth": ["elastic", sealed("es-sensitive")], "verify_certs": True}
    original = copy.deepcopy(data)
    conf = ElasticsearchConf(ssl_verify=json.dumps(data) if string_form else data)
    assert conf.ssl_verify["basic_auth"][1] == "es-sensitive"
    assert conf.ssl_verify["verify_certs"] is True
    assert data == original
    assert "es-sensitive" not in repr(conf)


def test_es_url_credentials_not_silently_accepted():
    with pytest.raises((ValueError, ValidationError)) as error:
        ElasticsearchConf(url="http://elastic:es-sensitive@elasticsearch:9200")
    assert "es-sensitive" not in str(error.value)


def test_redis_dict_nested_url_is_decoded_once():
    token = secret_crypto.encrypt_token("r@:/#%$").decode()
    conf = Settings(redis_url={"mode": "single", "url": f"redis://:{token}@redis:6379/1"})
    from redis.connection import parse_url

    assert parse_url(conf.redis_url["url"])["password"] == "r@:/#%$"
    conf.debug = True
    assert parse_url(conf.redis_url["url"])["password"] == "r@:/#%$"


def test_redis_dict_does_not_mutate_source():
    values = {"redis_url": {"mode": "sentinel", "password": sealed("r-sensitive")}}
    original = copy.deepcopy(values)
    decoded = Settings.set_redis_url(values)
    assert decoded["redis_url"]["password"] == "r-sensitive"
    assert values == original


def test_independent_telemetry_es_uses_same_parser():
    conf = Settings(
        telemetry_elasticsearch={
            "url": "http://stats:9200",
            "ssl_verify": {"basic_auth": ["elastic", sealed("stats-sensitive")]},
        }
    )
    assert conf.get_telemetry_conf().ssl_verify["basic_auth"][1] == "stats-sensitive"


def test_redis_url_and_password_conflict_is_rejected():
    from bisheng.core.config.secret_crypto import encrypt_token
    from bisheng.core.config.settings import _redis_credentials

    token = encrypt_token("value").decode()
    with pytest.raises(ValueError, match="conflict"):
        _redis_credentials({"mode": "single", "url": f"redis://:{token}@redis/1", "password": f"encrypt({token})"})


def test_legacy_database_environment_is_resolved_when_yaml_field_is_missing(monkeypatch):
    token = secret_crypto.encrypt_token("legacy-password").decode()
    monkeypatch.setenv("bisheng_DATABASE_URL", f"mysql+pymysql://root:{token}@mysql/bisheng")
    assert make_url(Settings().database_url).password == "legacy-password"


def test_conflicting_database_yaml_and_environment_are_rejected(monkeypatch):
    first = secret_crypto.encrypt_token("first").decode()
    second = secret_crypto.encrypt_token("second").decode()
    monkeypatch.setenv("bisheng_DATABASE_URL", f"mysql+pymysql://root:{first}@mysql/bisheng")
    with pytest.raises(ValueError):
        Settings(database_url=f"mysql+pymysql://root:{second}@mysql/bisheng")
