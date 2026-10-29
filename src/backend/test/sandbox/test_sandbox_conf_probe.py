"""Sandbox connection probe classification (F086)."""

from __future__ import annotations

import json

import httpx
import pytest

from bisheng.common.errcode.sandbox import SandboxEndpointInvalidError
from bisheng.core.config.settings import SandboxConf, encrypt_token
from bisheng.tool.domain.services.sandbox_conf_service import SandboxConfService

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _enc(token: str) -> str:
    raw = encrypt_token(token)
    return raw.decode() if isinstance(raw, bytes) else raw


class _Row:
    def __init__(self, value: str):
        self.value = value


def _install(monkeypatch, handler, rows=None, deployment=None):
    requests: list[httpx.Request] = []
    timeouts: list = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped)

    def factory(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr("bisheng.tool.domain.services.sandbox_conf_service.httpx.AsyncClient", factory)
    monkeypatch.setattr(
        "bisheng.tool.domain.services.sandbox_conf_service.settings.sandbox_conf",
        deployment if deployment is not None else SandboxConf(endpoints=["http://dep:8080"], token="dep-token"),
    )

    def get_config(key):
        if not rows:
            return None
        return _Row(rows)

    monkeypatch.setattr("bisheng.tool.domain.services.sandbox_conf_service.ConfigDao.get_config", get_config)
    return requests, timeouts


@pytest.mark.parametrize(
    "endpoints",
    [
        ["ftp://h"],
        ["http://"],
        ["http://h:99999"],
        ["http://h:8080/", "http://h:8080"],
        ["http://h:8080"] * 33,
        [""],
    ],
)
async def test_invalid_address_sends_nothing(monkeypatch, endpoints):
    requests, _timeouts = _install(monkeypatch, lambda request: httpx.Response(200))
    with pytest.raises(SandboxEndpointInvalidError):
        await SandboxConfService.test(endpoints, "tok")
    assert requests == []


async def test_ok_strips_slash_and_deletes_lease(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "body": "secret-health"})
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "s1", "lease_token": "lease-1", "body": "secret-session"})
        assert request.headers["x-lease-token"] == "lease-1"
        return httpx.Response(200, json={"ok": True})

    requests, timeouts = _install(monkeypatch, handler)
    result = await SandboxConfService.test(["http://host:8080/"], "typed-token")
    assert result == {"results": [{"url": "http://host:8080", "status": "ok"}]}
    assert str(requests[0].url) == "http://host:8080/health"
    assert requests[1].method == "POST"
    assert str(requests[1].url) == "http://host:8080/v1/sessions"
    assert requests[1].headers["authorization"] == "Bearer typed-token"
    assert requests[2].method == "DELETE"
    assert requests[2].url.path == "/v1/sessions/s1"
    assert "secret-health" not in json.dumps(result)
    assert "secret-session" not in json.dumps(result)
    assert timeouts == [5.0]


async def test_health_failure_does_not_open_a_session(monkeypatch):
    requests, _timeouts = _install(monkeypatch, lambda request: httpx.Response(500))
    result = await SandboxConfService.test(["http://host:8080"], "tok")
    assert result["results"] == [{"url": "http://host:8080", "status": "unreachable"}]
    assert [request.method for request in requests] == ["GET"]


async def test_timeout_is_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    _install(monkeypatch, handler)
    result = await SandboxConfService.test(["http://host:8080"], "tok")
    assert result["results"][0]["status"] == "unreachable"


async def test_401_and_503(monkeypatch):
    def rejected(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(401, json={"error": "no"})

    requests, _timeouts = _install(monkeypatch, rejected)
    result = await SandboxConfService.test(["http://host:8080"], "bad")
    assert result["results"][0]["status"] == "token_rejected"
    assert not any(request.method == "DELETE" for request in requests)

    def busy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(503, json={"error": "full"})

    requests, _timeouts = _install(monkeypatch, busy)
    result = await SandboxConfService.test(["http://host:8080"], "tok")
    assert result["results"][0]["status"] == "busy"
    assert "full" not in json.dumps(result)


async def test_empty_addresses_probe_deployment(monkeypatch):
    requests, _timeouts = _install(monkeypatch, lambda request: httpx.Response(500))
    result = await SandboxConfService.test([], "tok")
    assert str(requests[0].url) == "http://dep:8080/health"
    assert result["results"][0]["url"] == "http://dep:8080"


async def test_empty_everywhere_returns_no_results(monkeypatch):
    requests, _timeouts = _install(monkeypatch, lambda request: httpx.Response(200), deployment=SandboxConf())
    result = await SandboxConfService.test([], "")
    assert result == {"results": []}
    assert requests == []


async def test_mask_uses_saved_token_then_deployment(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer saved-token"
        return httpx.Response(401)

    stored = json.dumps({"endpoints": ["http://host:8080"], "token_enc": _enc("saved-token")})
    _install(monkeypatch, handler, rows=stored)
    await SandboxConfService.test(["http://host:8080"], "********")

    def deployment_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer dep-token"
        return httpx.Response(401)

    _install(monkeypatch, deployment_handler)
    await SandboxConfService.test(["http://host:8080"], "********")
