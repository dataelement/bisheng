"""Page sandbox config merge and cache (F086)."""

from __future__ import annotations

import json
import os

import pytest
from loguru import logger

from bisheng.common.models.config import ConfigKeyEnum
from bisheng.common.services.config_service import (
    SANDBOX_ENDPOINT_CACHE_KEY,
    SANDBOX_ENDPOINT_CACHE_TTL,
    ConfigService,
    write_sandbox_endpoint_cache,
)
from bisheng.core.config.settings import SandboxConf, Settings, encrypt_token

_UNREADABLE = "sandbox endpoint config unreadable; using deployment config"
_ENV_PREFIX = "BS_SANDBOX_CONF__"


def _enc(token: str) -> str:
    raw = encrypt_token(token)
    return raw.decode() if isinstance(raw, bytes) else raw


def _payload(endpoints: list[str], token: str) -> dict:
    return {"endpoints": endpoints, "token_enc": _enc(token) if token else ""}


class _Row:
    def __init__(self, value: str):
        self.value = value


class _Holder:
    def __init__(self, conf: SandboxConf):
        self.sandbox_conf = conf


class FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.set_calls: list = []
        self.setnx_calls: list = []
        self.get_error: Exception | None = None
        self.setnx_error: Exception | None = None
        self.miss_once = False
        self._reads = 0

    def get(self, key):
        if self.get_error:
            raise self.get_error
        self._reads += 1
        if self.miss_once and self._reads == 1:
            return None
        return self.store.get(key)

    def set(self, key, value, expiration=3600, enx=None):
        self.set_calls.append((key, value, expiration))
        self.store[key] = value

    def setNx(self, key, value, expiration=3600):
        self.setnx_calls.append((key, value, expiration))
        if self.setnx_error:
            raise self.setnx_error
        if key in self.store:
            return False
        self.store[key] = value
        return True


@pytest.fixture
def clean_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIX):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def deployment() -> _Holder:
    return _Holder(SandboxConf(endpoints=["http://deploy:8080"], token="deploy-token"))


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    client = FakeRedis()
    monkeypatch.setattr("bisheng.common.services.config_service.get_redis_client_sync", lambda: client)
    return client


@pytest.fixture
def dao(monkeypatch: pytest.MonkeyPatch) -> dict:
    holder = {"row": None, "calls": 0, "error": None}

    def get_config(key):
        holder["calls"] += 1
        assert key == ConfigKeyEnum.SANDBOX_ENDPOINT
        if holder["error"]:
            raise holder["error"]
        return holder["row"]

    monkeypatch.setattr("bisheng.common.services.config_service.ConfigDao.get_config", get_config)
    return holder


@pytest.fixture
def errors():
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(message.record["message"]), level="ERROR")
    yield messages
    logger.remove(sink)


def test_no_row_matches_deployment_fieldwise(deployment, redis, dao, errors):
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.model_dump() == deployment.sandbox_conf.model_dump()
    assert dao["calls"] == 1
    assert redis.set_calls == []
    assert redis.setnx_calls == []
    assert _UNREADABLE not in errors
    assert "deploy-token" not in " ".join(errors)


def test_page_endpoints_override_address_only(deployment, redis, dao):
    dao["row"] = _Row(json.dumps(_payload(["http://page:8080"], "")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.endpoints == ["http://page:8080"]
    assert result.token == "deploy-token"
    assert redis.setnx_calls[0][0] == SANDBOX_ENDPOINT_CACHE_KEY
    assert redis.setnx_calls[0][1] == {"endpoints": ["http://page:8080"], "token_enc": ""}
    assert redis.setnx_calls[0][2] == SANDBOX_ENDPOINT_CACHE_TTL
    assert not isinstance(redis.setnx_calls[0][1], str)


def test_page_token_overrides_token_only(deployment, redis, dao):
    dao["row"] = _Row(json.dumps(_payload([], "page-token")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.endpoints == ["http://deploy:8080"]
    assert result.token == "page-token"
    cached = redis.store[SANDBOX_ENDPOINT_CACHE_KEY]
    assert "page-token" not in json.dumps(cached)
    assert cached["token_enc"]


def test_empty_page_fields_fall_back(deployment, redis, dao):
    dao["row"] = _Row(json.dumps(_payload([], "")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.endpoints == ["http://deploy:8080"]
    assert result.token == "deploy-token"


def test_page_token_beats_env_overlay(clean_sandbox_env, monkeypatch, redis, dao):
    monkeypatch.setenv(f"{_ENV_PREFIX}TOKEN", "env-token")
    base = Settings()
    assert base.sandbox_conf.token == "env-token"
    dao["row"] = _Row(json.dumps(_payload([], "page-token")))
    result = ConfigService.get_sandbox_conf(base)
    assert result.token == "page-token"


def test_cache_hit_skips_db(deployment, redis, dao):
    redis.store[SANDBOX_ENDPOINT_CACHE_KEY] = _payload(["http://cached:8080"], "cached-token")
    dao["row"] = _Row(json.dumps(_payload(["http://db:8080"], "db-token")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.endpoints == ["http://cached:8080"]
    assert result.token == "cached-token"
    assert dao["calls"] == 0
    assert redis.set_calls == []
    assert redis.setnx_calls == []


@pytest.mark.parametrize(
    "cached",
    [
        ["http://not-a-dict"],
        {"endpoints": [1], "token_enc": ""},
        {"endpoints": [], "token_enc": None},
        {"token_enc": ""},
        None,
    ],
)
def test_invalid_cache_reads_db_and_does_not_write(deployment, redis, dao, cached):
    if cached is not None:
        redis.store[SANDBOX_ENDPOINT_CACHE_KEY] = cached
    else:
        redis.store[SANDBOX_ENDPOINT_CACHE_KEY] = {"endpoints": "nope", "token_enc": ""}
    dao["row"] = _Row(json.dumps(_payload(["http://db:8080"], "db-token")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "db-token"
    assert result.endpoints == ["http://db:8080"]
    assert redis.set_calls == []
    assert redis.setnx_calls == []


def test_redis_error_reads_db_without_writing(deployment, redis, dao, errors):
    redis.get_error = RuntimeError("redis down")
    dao["row"] = _Row(json.dumps(_payload(["http://db:8080"], "db-token")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "db-token"
    assert redis.set_calls == []
    assert redis.setnx_calls == []
    assert _UNREADABLE not in errors


def test_db_error_falls_back_without_raising(deployment, redis, dao, errors):
    redis.get_error = RuntimeError("redis down")
    dao["error"] = RuntimeError("db down")
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.model_dump() == deployment.sandbox_conf.model_dump()
    assert _UNREADABLE in errors
    assert "deploy-token" not in " ".join(errors)


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"endpoints": [1], "token_enc": ""}', "{}"])
def test_bad_db_value_falls_back(deployment, redis, dao, errors, raw):
    dao["row"] = _Row(raw)
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "deploy-token"
    assert redis.setnx_calls == []
    assert _UNREADABLE in errors
    assert "deploy-token" not in " ".join(errors)


def test_decrypt_failure_on_cache_falls_back(deployment, redis, dao, errors):
    redis.store[SANDBOX_ENDPOINT_CACHE_KEY] = {"endpoints": ["http://page:8080"], "token_enc": "not-fernet"}
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "deploy-token"
    assert dao["calls"] == 0
    assert _UNREADABLE in errors
    assert "not-fernet" not in " ".join(errors)
    assert "deploy-token" not in " ".join(errors)


def test_decrypt_failure_on_db_does_not_fill(deployment, redis, dao, errors):
    dao["row"] = _Row(json.dumps({"endpoints": [], "token_enc": "not-fernet"}))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "deploy-token"
    assert redis.setnx_calls == []
    assert _UNREADABLE in errors


def test_setnx_error_still_returns_db_value(deployment, redis, dao):
    redis.setnx_error = RuntimeError("cannot fill")
    dao["row"] = _Row(json.dumps(_payload(["http://db:8080"], "db-token")))
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "db-token"
    assert result.endpoints == ["http://db:8080"]


def test_existing_key_is_not_overwritten_by_fill(deployment, redis, dao):
    newer = _payload(["http://new:8080"], "new-token")
    redis.store[SANDBOX_ENDPOINT_CACHE_KEY] = newer
    redis.miss_once = True
    dao["row"] = _Row(json.dumps(_payload(["http://old:8080"], "old-token")))
    first = ConfigService.get_sandbox_conf(deployment)
    assert first.token == "old-token"
    assert redis.store[SANDBOX_ENDPOINT_CACHE_KEY] == newer
    assert redis.set_calls == []
    second = ConfigService.get_sandbox_conf(deployment)
    assert second.token == "new-token"
    assert second.endpoints == ["http://new:8080"]


def test_write_then_read_uses_new_cache(deployment, redis, dao):
    payload = _payload(["http://saved:8080"], "saved-token")
    write_sandbox_endpoint_cache(payload)
    assert redis.set_calls[0][0] == SANDBOX_ENDPOINT_CACHE_KEY
    assert redis.set_calls[0][2] == SANDBOX_ENDPOINT_CACHE_TTL
    assert isinstance(redis.set_calls[0][1], dict)
    assert "saved-token" not in json.dumps(redis.set_calls[0][1])
    result = ConfigService.get_sandbox_conf(deployment)
    assert result.token == "saved-token"
    assert dao["calls"] == 0


def test_write_rejects_bad_payload(redis):
    with pytest.raises(ValueError):
        write_sandbox_endpoint_cache({"endpoints": "nope", "token_enc": ""})
    assert redis.set_calls == []
