"""Sandbox config HTTP routes (F086)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.routing import APIRoute

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.tool.api import tool as tool_api
from bisheng.tool.domain.services.sandbox_conf_service import SandboxConfService


def _routes() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for route in tool_api.router.routes:
        if isinstance(route, APIRoute):
            found.setdefault(route.path, set()).update(route.methods or set())
    return found


def _user(is_super: bool) -> UserPayload:
    return UserPayload(user_id=1, user_name="tester", user_role=[], is_global_super=is_super)


def test_routes_are_on_the_tool_router():
    routes = _routes()
    assert "GET" in routes["/tool/sandbox_conf"]
    assert "POST" in routes["/tool/sandbox_conf"]
    assert "POST" in routes["/tool/sandbox_conf/test"]


def test_non_super_is_rejected_and_does_not_write(monkeypatch: pytest.MonkeyPatch):
    writes = []

    async def insert(*args, **kwargs):
        writes.append(args)

    monkeypatch.setattr("bisheng.common.models.config.ConfigDao.insert_or_update_config", insert)
    user = _user(False)
    body = tool_api.SandboxEndpointBody(endpoints=["http://h:8080"], token="x")
    with pytest.raises(UnAuthorizedError):
        asyncio.run(tool_api.get_sandbox_conf(user))
    with pytest.raises(UnAuthorizedError):
        asyncio.run(tool_api.save_sandbox_conf(None, body, user))
    with pytest.raises(UnAuthorizedError):
        asyncio.run(tool_api.test_sandbox_conf(body, user))
    assert writes == []


def test_super_delegates_and_save_does_not_require_a_probe(monkeypatch: pytest.MonkeyPatch):
    called = {"test": 0}
    user = _user(True)
    monkeypatch.setattr(SandboxConfService, "get", staticmethod(lambda: {"endpoints": ["http://a:8080"], "token": ""}))

    async def save(endpoints, token, actor, ip):
        called["save"] = (endpoints, token, actor.is_global_super, ip)

    async def probe(endpoints, token):
        called["test"] += 1
        return {"results": [{"url": endpoints[0], "status": "ok"}]}

    monkeypatch.setattr(SandboxConfService, "save", staticmethod(save))
    monkeypatch.setattr(SandboxConfService, "test", staticmethod(probe))
    monkeypatch.setattr(tool_api, "get_request_ip", lambda request: "10.0.0.1")

    viewed = asyncio.run(tool_api.get_sandbox_conf(user))
    assert viewed.status_code == 200
    assert viewed.data["endpoints"] == ["http://a:8080"]

    body = tool_api.SandboxEndpointBody(endpoints=["http://h:8080"], token="secret")
    saved = asyncio.run(tool_api.save_sandbox_conf(None, body, user))
    assert saved.status_code == 200
    assert called["test"] == 0
    assert called["save"] == (["http://h:8080"], "secret", True, "10.0.0.1")

    probed = asyncio.run(tool_api.test_sandbox_conf(body, user))
    assert probed.status_code == 200
    assert probed.data["results"][0]["status"] == "ok"
    assert called["test"] == 1
