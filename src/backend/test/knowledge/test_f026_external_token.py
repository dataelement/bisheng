"""Signed external-user token for WeKnora API-key requests (signed_token mode)."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import jwt
import pytest

from bisheng.knowledge.application import provider_v1_runtime as runtime
from bisheng.knowledge.application.provider_external_token import (
    EXTERNAL_USER_TOKEN_HEADER,
    current_external_user_id,
    provider_external_identity,
)
from bisheng.knowledge.application.provider_instance_admin import seal_api_key
from bisheng.knowledge.application.provider_v1_runtime import (
    ProviderFeatureUnavailable,
    _attach_external_identity,
)

SECRET = "fixture-hmac-secret-32bytes-min!!"


def _decode(headers):
    return jwt.decode(headers[EXTERNAL_USER_TOKEN_HEADER], SECRET, algorithms=["HS256"], audience="weknora")


def test_instance_without_sealed_secret_keeps_api_key_only():
    params = {"headers": {"X-API-Key": "k"}}
    assert _attach_external_identity(params, None, "10000") is params


def test_bound_identity_adds_a_scoped_token_without_mutating_params():
    params = {"headers": {"X-API-Key": "k"}}
    with provider_external_identity(17):
        attached = _attach_external_identity(params, seal_api_key(SECRET), "10000")
    claims = _decode(attached["headers"])
    assert (claims["sub"], claims["tenant_id"], claims["aud"]) == ("17", 10000, "weknora")
    assert params["headers"] == {"X-API-Key": "k"}


def test_sealed_secret_without_bound_identity_fails_closed():
    with pytest.raises(ProviderFeatureUnavailable):
        _attach_external_identity({"headers": {}}, seal_api_key(SECRET), "10000")


def test_unreadable_secret_and_invalid_scope_fail_closed():
    with provider_external_identity(1):
        with pytest.raises(ProviderFeatureUnavailable):
            _attach_external_identity({"headers": {}}, "plain", "10000")
        with pytest.raises(ProviderFeatureUnavailable):
            _attach_external_identity({"headers": {}}, seal_api_key(SECRET), "not-a-scope")


def test_identity_binding_is_scoped_and_reset():
    with provider_external_identity(5):
        assert current_external_user_id() == 5
    assert current_external_user_id() is None


class _Result:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, _):
        return _Result(("https://wk.example.invalid", seal_api_key("api-key"), seal_api_key(SECRET)))


async def test_instance_client_sends_the_token_on_the_wire(monkeypatch):
    route = NS(
        tenant_id=1,
        space_id=10,
        provider_key="weknora",
        generation=1,
        instance_id=1,
        remote_scope_id="10000",
        remote_kb_id="kb",
        capability_revision=1,
    )
    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(runtime, "resolve_space_route", AsyncMock(return_value=route))
    monkeypatch.setattr(runtime, "get_async_db_session", lambda: _Session())
    monkeypatch.setattr(runtime.httpx, "AsyncClient", _Client)

    with provider_external_identity(17):
        async with runtime.instance_client(route):
            pass

    assert _decode(captured["headers"])["sub"] == "17"


async def test_instance_client_refuses_a_sealed_instance_without_identity(monkeypatch):
    route = NS(
        tenant_id=1,
        space_id=10,
        provider_key="weknora",
        generation=1,
        instance_id=1,
        remote_scope_id="10000",
        remote_kb_id="kb",
        capability_revision=1,
    )
    monkeypatch.setattr(runtime, "resolve_space_route", AsyncMock(return_value=route))
    monkeypatch.setattr(runtime, "get_async_db_session", lambda: _Session())

    with pytest.raises(ProviderFeatureUnavailable):
        async with runtime.instance_client(route):
            pass
