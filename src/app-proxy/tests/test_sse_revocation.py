"""Revoking a visitor ends even an otherwise idle event stream."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app_proxy import sse
from app_proxy.authz import Verdict


@pytest.mark.asyncio
async def test_idle_sse_rechecks_access_and_closes_upstream(monkeypatch):
    closed = asyncio.Event()
    class Upstream:
        async def aiter_raw(self):
            await asyncio.Event().wait()
            yield b"unreachable"
        async def aclose(self):
            closed.set()
    monkeypatch.setattr(sse, "get_config", lambda: SimpleNamespace(ws_reauthorize_interval_seconds=1))
    check = AsyncMock(return_value=Verdict(decision="forbidden"))
    monkeypatch.setattr(sse, "authorize", check)
    request = Request({"type": "http", "path": "/apps/demo/api/events", "path_params": {"slug": "demo"},
                       "headers": [(b"cookie", b"bisheng_app_session_demo=bs-view-session")]})
    stream = sse.authorized_events(Upstream(), request, Verdict(decision="allow"), slug="demo", request_id="request")
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), 3)
    assert closed.is_set()
    check.assert_awaited_once_with(slug="demo", access_token="bs-view-session", request_id="request")
