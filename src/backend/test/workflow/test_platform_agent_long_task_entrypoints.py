import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.flow import PlatformAgentPermissionError
from bisheng.workflow.application import platform_agent
from bisheng.workflow.domain.services import published_workflow_service as published
from test.workflow.test_platform_agent_long_task_contract import long_remote as long_remote
from test.workflow.test_platform_agent_long_task_run import long_run as long_run


async def test_existing_stop_checks_owner_and_persists_intent_before_signal(long_run, monkeypatch):
    run = long_run
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    session_id = "long-session"
    flow_id = "f" * 32
    run.repo.reserve_long_call(
        run.dispatch, key, "digest", {"agent_id": "mock:echo", "version_id": "v1"}, 1000, 1005, 1030
    )
    run.repo.permit_long_start(run.dispatch, key)
    wake = []
    run.service.long_wake = lambda *args: wake.append(args)
    monkeypatch.setattr(platform_agent, "get_service", lambda: run.service)
    monkeypatch.setattr(
        published.ChatSessionService, "get_subject_session", AsyncMock(return_value=SimpleNamespace(flow_id=flow_id))
    )

    async def signal(*, long_committed):
        assert long_committed
        assert run.repo.long_snapshot(execution_id, key)["cancel_state"] == "INTENT"

    monkeypatch.setattr(
        published,
        "RedisCallback",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_platform_agent_reference=lambda: execution_id, async_set_workflow_stop=signal
        ),
    )
    runtime = platform_agent.BrowserPlatformAgentRuntime()
    with pytest.raises(PlatformAgentPermissionError):
        await runtime.long_status(SimpleNamespace(user_id=11, tenant_id=7), flow_id, session_id, execution_id)
    with pytest.raises(PlatformAgentPermissionError):
        await runtime.stop_long(SimpleNamespace(user_id=12, tenant_id=8), flow_id, session_id, execution_id)
    await published.PublishedWorkflowService.stop(
        workflow_id=flow_id,
        session_id=session_id,
        operator_user_id=12,
        session_subject=SessionSubject.natural_person(tenant_id=7, user_id=12),
    )
    summary = await runtime.long_status(run.user, flow_id, session_id, execution_id)
    assert summary["local_state"] == "STOPPED" and summary["cancel_state"] == "INTENT"
    assert wake == [(7, execution_id, None)]
    assert not {"ref", "actor_reference", "lease"} & summary.keys()


async def test_existing_status_action_recovers_original_summary_after_redis_status_is_gone(long_run, monkeypatch):
    from bisheng.common.chat.clients import workflow_client

    run = long_run
    flow_id = "f" * 32
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    run.repo.reserve_long_call(
        run.dispatch, key, "digest", {"agent_id": "mock:echo", "version_id": "v1"}, 1000, 1005, 1030
    )
    run.repo.permit_long_start(run.dispatch, key)
    run.repo.request_stop(execution_id, cancel_long=True)
    monkeypatch.setattr(platform_agent, "get_service", lambda: run.service)
    monkeypatch.setattr(
        workflow_client,
        "RedisCallback",
        lambda *_: SimpleNamespace(get_platform_agent_reference=lambda: None, get_workflow_status=lambda: None),
    )
    monkeypatch.setattr(
        workflow_client.ChatSessionService,
        "get_subject_session_if_exists",
        AsyncMock(return_value=SimpleNamespace(flow_id=flow_id)),
    )
    client = workflow_client.WorkflowClient(
        None,
        "connection",
        flow_id,
        "",
        12,
        run.user,
        None,
        None,
        session_subject=SessionSubject.natural_person(tenant_id=7, user_id=12),
        platform_agent_runtime=platform_agent.BrowserPlatformAgentRuntime(run.repo),
    )
    client.init_history = AsyncMock()
    client.ensure_workflow_available = AsyncMock(return_value=True)
    client.send_response = AsyncMock()
    with run.repo.transaction() as db:
        from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution

        db.get(PlatformAgentExecution, execution_id).session_id = "status-chat_async_task_id"
    rerun, _ = await client.check_status({"chat_id": "status-chat", "execution_id": execution_id})
    assert not rerun
    summary = client.send_response.await_args.args[2]["agent_long_task"]
    assert summary["execution_id"] == execution_id and summary["cancel_state"] == "INTENT"


@pytest.mark.parametrize("explicit_id", ["original", ""])
async def test_explicit_status_never_consumes_current_run_without_an_original_summary(
    long_run, monkeypatch, explicit_id
):
    from bisheng.common.chat.clients import workflow_client
    from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution

    run = long_run
    flow_id = "f" * 32
    execution_id = run.dispatch.execution_id
    with run.repo.transaction() as db:
        db.get(PlatformAgentExecution, execution_id).session_id = "status-chat_async_task_id"
    status_reads = []
    callback = SimpleNamespace(
        get_platform_agent_reference=lambda: "a" * 32,
        get_workflow_status=lambda: status_reads.append(True) or {"status": "RUNNING"},
    )
    monkeypatch.setattr(platform_agent, "get_service", lambda: run.service)
    monkeypatch.setattr(workflow_client, "RedisCallback", lambda *_: callback)
    monkeypatch.setattr(
        workflow_client.ChatSessionService,
        "get_subject_session_if_exists",
        AsyncMock(return_value=SimpleNamespace(flow_id=flow_id)),
    )
    client = workflow_client.WorkflowClient(
        None,
        "connection",
        flow_id,
        "",
        12,
        run.user,
        None,
        None,
        session_subject=SessionSubject.natural_person(tenant_id=7, user_id=12),
        platform_agent_runtime=platform_agent.BrowserPlatformAgentRuntime(run.repo),
    )
    client.init_history = AsyncMock()
    client.ensure_workflow_available = AsyncMock(return_value=True)
    client.send_response = AsyncMock()
    client.workflow_run = AsyncMock()
    if explicit_id:
        rerun, _ = await client.check_status({"chat_id": "status-chat", "execution_id": execution_id})
        assert not rerun
    else:
        with pytest.raises(PlatformAgentPermissionError):
            await client.check_status({"chat_id": "status-chat", "execution_id": explicit_id})
    assert status_reads == []
    client.workflow_run.assert_not_awaited()
    assert client.workflow is None


async def test_browser_stop_releases_run_and_fences_its_pending_event_reader(monkeypatch):
    from bisheng.common.chat.clients import workflow_client

    read_started = asyncio.Event()
    release_event = asyncio.Event()

    async def events():
        read_started.set()
        await release_event.wait()
        yield {"category": "stream_msg", "message": "迟到的旧结果"}

    flow_id = "f" * 32
    execution_id = "a" * 32
    workflow = SimpleNamespace(
        workflow_id=flow_id,
        unique_id="status-chat_async_task_id",
        get_platform_agent_reference=lambda: execution_id,
        get_workflow_status=Mock(return_value={"status": "RUNNING"}),
        async_set_workflow_stop=AsyncMock(),
        get_response_until_break=events,
        async_get_workflow_status=AsyncMock(return_value=None),
        async_clear_workflow_status=AsyncMock(),
    )
    runtime = SimpleNamespace(stop_long=AsyncMock(return_value=True), long_status=AsyncMock(return_value=None))
    client = workflow_client.WorkflowClient(
        None, "connection", flow_id, "status-chat", 12, None, None, None, platform_agent_runtime=runtime
    )
    monkeypatch.setattr(workflow_client, "RedisCallback", lambda *_: workflow)
    client.init_history = AsyncMock()
    client.ensure_workflow_available = AsyncMock(return_value=True)
    client.send_response = AsyncMock()
    client.send_json = AsyncMock()
    client.workflow = workflow
    reader = asyncio.create_task(client.workflow_run())
    await read_started.wait()
    try:
        await client.close(force_stop=True)
        assert client.workflow is None
        rerun, _ = await client.check_status({"chat_id": "status-chat"}, is_init=True)
        assert rerun
        workflow.get_workflow_status.assert_not_called()
        replacement = SimpleNamespace()
        client.workflow = replacement
    finally:
        release_event.set()
        await reader
    assert client.workflow is replacement
    client.send_json.assert_not_awaited()
    workflow.async_set_workflow_stop.assert_awaited_once_with(long_committed=True)
    client.send_response.assert_awaited_once_with("processing", "close", "")
