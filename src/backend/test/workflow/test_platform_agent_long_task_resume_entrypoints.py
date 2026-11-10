from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.chat.clients import workflow_client
from bisheng.common.errcode.flow import PlatformAgentError, PlatformAgentPermissionError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.workflow.application import platform_agent
from test.workflow.test_platform_agent_interaction_wait import FLOW_ID, SESSION
from test.workflow.test_platform_agent_long_task_resume_output import MESSAGE, ready
from test.workflow.test_platform_agent_long_task_resume_reconcile import runtime as runtime
from test.workflow.test_platform_agent_long_task_resume_reconcile import start
from test.workflow.test_platform_agent_long_task_resume_wait import CALL
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote

CHAT_ID = SESSION.removesuffix("_async_task_id")


async def test_status_and_stop_use_same_persisted_execution_when_redis_reference_is_missing(runtime, monkeypatch):
    execution_id, _ = await start(runtime, monkeypatch)
    callback = SimpleNamespace(get_platform_agent_reference=lambda: None)
    monkeypatch.setattr(workflow_client, "RedisCallback", lambda *_: callback)
    client = workflow_client.WorkflowClient(
        None,
        "test",
        FLOW_ID,
        CHAT_ID,
        runtime.user.user_id,
        runtime.user,
        None,
        None,
        platform_agent_runtime=platform_agent.BrowserPlatformAgentRuntime(runtime.repo),
    )
    client.send_response = AsyncMock()
    client.send_json = AsyncMock()
    assert await client.check_status({"chat_id": CHAT_ID}) == (False, SESSION)
    waiting = client.send_response.await_args.args[2]["agent_long_task"]
    assert waiting["execution_id"] == execution_id and waiting["local_state"] == "WAITING_RESULT"
    assert waiting["deadline"] == 1030 and not waiting.get("interaction_pending")
    await client.handle_message({"action": "stop", "execution_id": execution_id})
    assert await client.check_status({"chat_id": CHAT_ID, "initial_open": True}, is_init=True) == (False, SESSION)
    stopped = next(
        call.args[2]["agent_long_task"]
        for call in reversed(client.send_response.await_args_list)
        if call.args[:2] == ("processing", "info")
    )
    assert stopped["execution_id"] == execution_id and stopped["local_state"] == "STOPPED"
    assert stopped["status_version"] > waiting["status_version"]
    assert await client.check_status({"chat_id": CHAT_ID}, is_init=True) == (True, SESSION)
    client.send_response.reset_mock()
    await client.check_status({"chat_id": "other-session", "execution_id": execution_id})
    assert client.send_response.await_args.args[:2] == ("error", "over")


async def test_recovered_result_requires_current_owner_and_agent_permission(runtime, monkeypatch):
    execution_id, dispatch_id = await ready(runtime, monkeypatch)
    browser = platform_agent.BrowserPlatformAgentRuntime(runtime.repo)
    with tenant_execution_scope(7):
        attempt = await platform_agent.claim_long_task_resume(execution_id, CALL, dispatch_id)
        message_id = await platform_agent.commit_long_task_resume_output(attempt, MESSAGE)
    view = await browser.long_task_resume_status(runtime.user, FLOW_ID, SESSION, None)
    assert view["output"] == {"message_id": message_id, "message": MESSAGE}
    with pytest.raises(PlatformAgentPermissionError):
        await browser.long_task_resume_status(runtime.publisher, FLOW_ID, SESSION, execution_id)
    wrong_tenant = SimpleNamespace(user_id=runtime.user.user_id, tenant_id=8)
    with pytest.raises(PlatformAgentError):
        await browser.long_task_resume_status(wrong_tenant, FLOW_ID, SESSION, execution_id)
    wrong_source = SimpleNamespace(user_id=runtime.user.user_id, tenant_id=7, auth_source="different")
    with pytest.raises(PlatformAgentPermissionError):
        await browser.long_task_resume_status(wrong_source, FLOW_ID, SESSION, execution_id)
    monkeypatch.setattr(runtime.provider, "check_use", AsyncMock(side_effect=PlatformAgentPermissionError))
    with pytest.raises(PlatformAgentPermissionError):
        await browser.long_task_resume_status(runtime.user, FLOW_ID, SESSION, execution_id)
