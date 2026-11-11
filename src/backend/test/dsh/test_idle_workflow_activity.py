"""AC-IDLE-02/03: WS business messages renew before permission checks, polling does not."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import HTTPConnection

from bisheng.common.chat.manager import ChatManager
from bisheng.core.session_activity import business_activity
from bisheng.dsh.application.session_activity import DshSessionActivity
from bisheng.dsh.domain.services.access import DshPrincipal


@business_activity(http=False, websocket_actions=("init_data", "input"))
async def entrance():
    pass


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("action,expected", [("check_status", 0), ("init_data", 1), ("input", 1), ("stop", 0)])
async def test_ws_activity_is_transport_owned_and_independent_of_business_permission(allowed, action, expected):
    order = []
    record = AsyncMock(side_effect=lambda _p: order.append("activity"))
    conn = HTTPConnection({"type": "websocket", "endpoint": entrance, "path": "/workflow", "headers": []})
    conn.state.authenticated_activity = DshSessionActivity(
        SimpleNamespace(record_activity=record), DshPrincipal(tenant_id="2", user_id="20", session_id="verified")
    )
    manager = object.__new__(ChatManager)
    manager._has_use_action = AsyncMock(side_effect=lambda *_: (order.append("permission"), allowed)[1])
    client = SimpleNamespace(handle_message=AsyncMock(side_effect=lambda *_: order.append("business")))
    result = await manager._dispatch_message(
        client, {"action": action}, login_user=object(), work_type=object(), client_id="workflow", connection=conn
    )
    assert result is allowed
    assert record.await_count == expected
    assert order == (["activity"] if expected else []) + ["permission"] + (["business"] if allowed else [])
