"""Redis and Celery URL passwords with special characters stay in the password field."""

from urllib.parse import unquote, urlparse

import pytest
from cryptography.fernet import InvalidToken
from redis.connection import parse_url

from bisheng.core.config.celery_redis import _build_sentinel_endpoint
from bisheng.core.config.settings import Settings, decrypt_redis_url, encrypt_token


def _encrypted_url(
    password: str,
    *,
    username: str = "",
    scheme: str = "redis",
    hostport: str = "192.168.106.107:6379",
    path: str = "/1",
    query: str = "",
) -> str:
    token = encrypt_token(password).decode()
    userinfo = f"{username}:{token}"
    rendered = f"{scheme}://{userinfo}@{hostport}{path}"
    if query:
        rendered = f"{rendered}?{query}"
    return rendered


@pytest.mark.parametrize("password", ["p@ss", "a#b", "a/b", "a?b", "100%", "a b"])
def test_decrypt_redis_url_round_trips_password(password):
    rendered = decrypt_redis_url(_encrypted_url(password))
    parsed = parse_url(rendered)
    assert parsed["password"] == password
    assert "username" not in parsed
    assert parsed["host"] == "192.168.106.107"
    assert parsed["port"] == 6379
    assert parsed["db"] == 1


def test_username_is_kept():
    rendered = decrypt_redis_url(_encrypted_url("p@ss", username="root", hostport="redis:6379", path="/0"))
    parsed = parse_url(rendered)
    assert parsed["username"] == "root"
    assert parsed["password"] == "p@ss"
    assert rendered.startswith("redis://root:")


def test_percent_encoded_username_is_not_quoted_again():
    rendered = decrypt_redis_url(_encrypted_url("p@ss", username="user%40corp"))
    assert "user%40corp:" in rendered
    assert "user%2540corp" not in rendered
    parsed = parse_url(rendered)
    assert parsed["username"] == "user@corp"
    assert parsed["password"] == "p@ss"


def test_alphanumeric_password_matches_previous_url_shape():
    rendered = decrypt_redis_url(_encrypted_url("secret", hostport="10.0.0.1:6379"))
    assert rendered == "redis://:secret@10.0.0.1:6379/1"


def test_empty_password_is_not_decrypted():
    original = "redis://:@127.0.0.1:6379/1"
    assert decrypt_redis_url(original) == original


def test_url_without_password_is_unchanged():
    original = "redis://redis:6379/1"
    assert decrypt_redis_url(original) == original


def test_invalid_ciphertext_is_not_treated_as_plaintext():
    with pytest.raises(InvalidToken):
        decrypt_redis_url("redis://:not-a-token@10.0.0.1:6379/1")


def test_ipv6_host_and_query_are_preserved():
    rendered = decrypt_redis_url(
        _encrypted_url(
            "p@ss",
            scheme="rediss",
            hostport="[::1]:6379",
            query="socket_timeout=5",
        )
    )
    assert "[::1]:6379" in rendered
    assert "socket_timeout=5" in rendered
    parsed = parse_url(rendered)
    assert parsed["password"] == "p@ss"
    assert parsed["host"] == "::1"
    assert parsed["port"] == 6379
    assert parsed["socket_timeout"] == 5.0


def test_settings_string_branches_share_decryption():
    encrypted = _encrypted_url("p@ss")
    redis_values = Settings.set_redis_url({"redis_url": encrypted})
    celery_values = Settings.set_celery_redis_url({"celery_redis_url": encrypted})
    assert redis_values["redis_url"] == celery_values["celery_redis_url"]
    assert parse_url(redis_values["redis_url"])["password"] == "p@ss"


def test_dict_encrypt_keeps_plaintext_password():
    token = encrypt_token("p@ss").decode()
    wrapped = f"encrypt({token})"
    redis_values = Settings.set_redis_url(
        {
            "redis_url": {"password": wrapped, "sentinel_password": wrapped},
        }
    )
    celery_values = Settings.set_celery_redis_url(
        {
            "celery_redis_url": {"password": wrapped, "sentinel_password": wrapped},
        }
    )
    assert redis_values["redis_url"]["password"] == "p@ss"
    assert redis_values["redis_url"]["sentinel_password"] == "p@ss"
    assert celery_values["celery_redis_url"]["password"] == "p@ss"
    assert "%40" not in celery_values["celery_redis_url"]["password"]


def test_celery_sentinel_endpoint_quotes_plaintext_once():
    endpoint = _build_sentinel_endpoint(
        {"host": "10.0.0.1", "port": 26379},
        db=0,
        username=None,
        password="p@ss",
    )
    assert "p%40ss" in endpoint
    parsed = urlparse(endpoint)
    assert parsed.password == "p%40ss"
    assert unquote(parsed.password) == "p@ss"
