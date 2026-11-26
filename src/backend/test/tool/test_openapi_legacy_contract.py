"""Characterize HEAD's ordinary OpenAPI contract without real network access.

Saved/bounded execution is deliberately a separate opt-in contract.
"""

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from bisheng_langchain.utils import requests as legacy_requests


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("legacy contract tests must not access DNS or sockets")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def implementation(**kwargs):
    return OpenApiTools(
        url="http://10.0.0.8:8080",
        params={"path": "/internal", "method": "get", "parameters": []},
        **kwargs,
    )


@pytest.mark.parametrize("status", [201, 302, 500])
def test_sync_non_200_raises_with_status_and_response_body(monkeypatch, status):
    monkeypatch.setattr(
        legacy_requests.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=status, text="upstream body"),
    )
    with pytest.raises(Exception, match=rf"^api_call_fail: {status} upstream body$"):
        implementation().run()


async def test_async_non_200_returns_response_body(monkeypatch):
    class Response:
        status = 500

        async def text(self):
            return "upstream error body"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def request(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(legacy_requests.aiohttp, "ClientSession", Session)
    assert await implementation().arun() == "upstream error body"


@pytest.mark.parametrize("method", ["get", "post", "put", "delete"])
async def test_injected_clients_receive_mapped_arguments_and_proxy(method):
    sync = Mock()
    asynchronous = Mock()
    getattr(sync, method).return_value = SimpleNamespace(status_code=200, text="sync result")
    async_call = AsyncMock(return_value="async result")
    setattr(asynchronous, "a" + method, async_call)
    tool = OpenApiTools(
        url="http://192.168.1.5:8080",
        client=sync,
        async_client=asynchronous,
        api_key="saved-key",
        params={
            "path": "/items/{item_id}",
            "method": method.upper(),
            "api_location": "query",
            "parameter_name": "credential",
            "parameters": [
                {"name": "item_id", "in": "path", "schema": {"type": "integer"}},
                {"name": "count", "in": "query", "schema": {"type": "integer"}},
                {"name": "ratio", "in": "body", "schema": {"type": "number"}},
                {"name": "enabled", "in": "body", "schema": {"type": "boolean"}},
            ],
        },
    )
    supplied = {
        "item_id": "client-id",
        "count": "7",
        "ratio": "1.5",
        "enabled": "true",
        "extra": "kept",
        "credential": "caller-value",
        "proxy": "http://proxy.internal:8080",
    }
    expected = {
        "params": {"count": 7, "extra": "kept", "credential": "saved-key"},
        "proxy": "http://proxy.internal:8080",
    }
    if method != "get":
        expected["json"] = {"ratio": 1.5, "enabled": True}
    assert tool.run(**supplied) == "sync result"
    assert await tool.arun(**supplied) == "async result"
    getattr(sync, method).assert_called_once_with("http://192.168.1.5:8080/items/client-id", **expected)
    async_call.assert_awaited_once_with("http://192.168.1.5:8080/items/client-id", **expected)
    assert tool.client is sync
    assert tool.async_client is asynchronous


def test_sync_private_url_headers_proxy_and_timeout_reach_legacy_transport(monkeypatch):
    get = Mock(return_value=SimpleNamespace(status_code=200, text="ok"))
    monkeypatch.setattr(legacy_requests.requests, "get", get)
    tool = implementation(request_timeout=95, headers={"X-Fixture": "value"}, proxy="http://proxy.internal")
    assert tool.run(q="hello") == "ok"
    get.assert_called_once_with(
        "http://10.0.0.8:8080/internal",
        headers={"X-Fixture": "value"},
        auth=None,
        timeout=95,
        proxies={"http": "http://proxy.internal", "https": "http://proxy.internal"},
        params={"q": "hello"},
    )


async def test_async_private_url_and_timeout_reach_legacy_transport(monkeypatch):
    observed = {}

    class Response:
        async def text(self):
            return "ok"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Session:
        def __init__(self, *, timeout):
            observed["timeout"] = timeout.total

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def request(self, method, url, **kwargs):
            observed.update(method=method, url=url, kwargs=kwargs)
            return Response()

    monkeypatch.setattr(legacy_requests.aiohttp, "ClientSession", Session)
    assert await implementation(request_timeout=95).arun(q="hello") == "ok"
    assert observed == {
        "timeout": 95,
        "method": "GET",
        "url": "http://10.0.0.8:8080/internal",
        "kwargs": {"headers": None, "proxy": None, "auth": None, "params": {"q": "hello"}},
    }
