import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.websockets import WebSocketState

from bisheng.common.chat.clients import workflow_client
from bisheng.common.chat.manager import ChatManager
from bisheng.common.errcode.flow import PlatformAgentPermissionError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.session import MessageSessionDao
from bisheng.worker.workflow import tasks
from bisheng.workflow.application import platform_agent
from bisheng.workflow.common.workflow import WorkflowStatus
from test.workflow.test_platform_agent_interaction_submit import CALL, waiting
from test.workflow.test_platform_agent_interaction_wait import FLOW_ID, SESSION, prepare, run_worker, sample_graph
from test.workflow.test_platform_agent_interaction_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_interaction_wait import long_remote as long_remote

CHAT_ID = SESSION.removesuffix("_async_task_id")


@pytest.fixture
def browser(interaction_runtime, monkeypatch):
    run = interaction_runtime
    reference = [None]

    def restore(execution_id):
        reference[0] = execution_id
        return True

    callback = SimpleNamespace(
        workflow_id=FLOW_ID,
        unique_id=SESSION,
        get_platform_agent_reference=lambda: reference[0],
        get_workflow_status=Mock(return_value={"status": "input"}),
        restore_platform_agent_reference=Mock(side_effect=restore),
        async_set_workflow_stop=AsyncMock(),
    )
    monkeypatch.setattr(workflow_client, "RedisCallback", lambda *_: callback)
    client = workflow_client.WorkflowClient(
        None,
        "connection",
        FLOW_ID,
        CHAT_ID,
        run.user.user_id,
        run.user,
        None,
        None,
        platform_agent_runtime=platform_agent.BrowserPlatformAgentRuntime(run.repo),
    )
    client.send_response = AsyncMock()
    client.init_history = AsyncMock()
    client.workflow_run = AsyncMock()
    client.ensure_workflow_available = AsyncMock(return_value=True)
    return client, callback, reference


async def test_waiting_form_and_stop_with_missing_redis_reference(interaction_runtime, browser):
    run = interaction_runtime
    client, _, reference = browser
    execution_id, interaction_id, revision = await waiting(run)
    with tenant_execution_scope(7):
        again, _ = await client.check_status({"chat_id": CHAT_ID, "flow_id": FLOW_ID})
        assert not again
        assert reference[0] == execution_id
        form = client.send_response.await_args.args[2]["agent_interaction"]
        assert (form["interaction_id"], form["revision"], form["phase"]) == (interaction_id, revision, "WAITING_INPUT")
        assert set(form["form"]) == {"type", "label", "required", "max_length"}
        client.init_history.assert_not_awaited()
        client.workflow_run.assert_not_awaited()

        reference[0] = None
        client.workflow = None
        await client.handle_message({"action": "stop", "execution_id": execution_id})
        assert run.repo.long_snapshot(execution_id, CALL)["local_state"] == "STOPPED"
        await client.check_status({"chat_id": CHAT_ID, "execution_id": execution_id})
        view = client.send_response.await_args.args[2]["agent_interaction"]
        assert view["phase"] == "TERMINAL" and "form" not in view


@pytest.mark.parametrize("disconnected", [True, False])
async def test_waiting_connection_cleanup_sends_no_processing_frame(browser, disconnected):
    client, _, _ = browser
    client.websocket = SimpleNamespace(
        client_state=WebSocketState.DISCONNECTED if disconnected else WebSocketState.CONNECTED,
        close=AsyncMock(),
    )
    manager = ChatManager.__new__(ChatManager)
    manager.active_clients = {client.client_key: client}
    await manager.close_client(client.client_key, code=1000, reason="fixture")
    client.send_response.assert_not_awaited()
    assert client.ws_closed
    assert not manager.active_clients
    assert client.websocket.close.await_count == int(not disconnected)


async def test_initial_open_keeps_stopped_interaction_but_manual_rerun_can_start(interaction_runtime, browser):
    run = interaction_runtime
    client, callback, reference = browser
    execution_id, _, _ = await waiting(run)
    reference[0] = execution_id
    with tenant_execution_scope(7):
        run.repo.request_stop(execution_id, cancel_long=True)
    callback.get_workflow_status.return_value = None

    open_message = {"action": "init_data", "chat_id": CHAT_ID, "flow_id": FLOW_ID}
    should_start, _ = await client.check_status({**open_message, "initial_open": True}, is_init=True)
    assert not should_start
    payload = client.send_response.await_args.args[2]
    assert payload["agent_interaction"]["execution_id"] == execution_id
    assert payload["agent_interaction"]["phase"] == "TERMINAL"
    assert "form" not in payload["agent_interaction"]

    should_start, _ = await client.check_status(open_message, is_init=True)
    assert should_start


@pytest.mark.parametrize("mismatch", ["user", "tenant", "binding", "revoked", "disabled", "session"])
async def test_interaction_requires_current_original_actor(interaction_runtime, browser, monkeypatch, mismatch):
    run = interaction_runtime
    client, _, _ = browser
    if mismatch == "binding":
        run.user.auth_source = "kunlian"
        run.user._runtime_credential_reference = {"binding_id": 81}
    execution_id, interaction_id, revision = await waiting(run)
    if mismatch == "user":
        client.login_user = SimpleNamespace(user_id=999, tenant_id=7)
    if mismatch == "tenant":
        client.login_user = SimpleNamespace(user_id=12, tenant_id=8)
    if mismatch == "binding":
        run.user._runtime_credential_reference = {"binding_id": 82}
    if mismatch == "revoked":
        from bisheng.common.errcode.http_error import UnAuthorizedError

        monkeypatch.setattr(run.service, "authorize", AsyncMock(side_effect=UnAuthorizedError))
    if mismatch == "disabled":
        monkeypatch.setattr(run.service, "identity_reader", AsyncMock(return_value={12: {"state": "disabled"}}))
    chat_id = "another-chat" if mismatch == "session" else CHAT_ID
    await client.handle_message(
        {
            "action": "agent_interaction_submit",
            "chat_id": chat_id,
            "execution_id": execution_id,
            "interaction_id": interaction_id,
            "revision": revision,
            "submission_id": "key",
            "answer": "protected",
        }
    )
    assert client.send_response.await_args.args[0:2] == ("error", "over")
    with tenant_execution_scope(7):
        assert run.repo.long_snapshot(execution_id, CALL)["interaction"]["phase"] == "WAITING_INPUT"


async def test_submission_frames_redact_answer_and_keep_native_input_separate(
    interaction_runtime, browser, monkeypatch
):
    from bisheng.common.chat.clients import base

    client, _, _ = browser
    execution_id, interaction_id, revision = await waiting(interaction_runtime)
    log = Mock()
    monkeypatch.setattr(base, "logger", log)
    client.handle_user_input = AsyncMock()
    message = {
        "action": "agent_interaction_submit",
        "chat_id": CHAT_ID,
        "execution_id": execution_id,
        "interaction_id": interaction_id,
        "revision": revision,
        "submission_id": "key",
        "answer": "secret-answer-for-log-test",
    }
    await client.handle_message({**message, "revision": "old-revision"})
    assert client.send_response.await_args.args[2]["agent_interaction_error"] == "retry"
    await client.handle_message(message)
    view = client.send_response.await_args.args[2]["agent_interaction"]
    assert view["phase"] == "SUBMIT_QUEUED" and "form" not in view
    await client.handle_message(message)
    assert client.send_response.await_args.args[2]["agent_interaction"]["status_version"] == view["status_version"]
    assert message["answer"] not in str(log.mock_calls) + str(client.send_response.mock_calls)
    await client._handle_message({"action": "input", "data": {"native": {}}})
    client.handle_user_input.assert_awaited_once_with({"native": {}})


async def test_wrong_explicit_id_does_not_fall_back(interaction_runtime, browser):
    client, callback, _ = browser
    await waiting(interaction_runtime)
    rerun, _ = await client.check_status({"chat_id": CHAT_ID, "execution_id": "a" * 32})
    assert not rerun
    assert client.send_response.await_args.args[0:2] == ("error", "over")
    callback.restore_platform_agent_reference.assert_not_called()


async def test_explicit_stop_cannot_fall_back_to_another_execution(interaction_runtime, browser):
    run = interaction_runtime
    client, _, reference = browser
    execution_id, _, _ = await waiting(run)
    reference[0] = execution_id
    client.close = AsyncMock()
    with tenant_execution_scope(7):
        actor = await run.service.authorize(run.user, FLOW_ID, "use")
        unrelated, _ = run.repo.prepare_execution(
            FLOW_ID, "another-session", actor, {"nodes": [], "edges": []}, run.service.config, "PUBLISHED"
        )
    for wrong in (unrelated["execution_id"], None):
        await client.handle_message({"action": "stop", "execution_id": wrong})
        client.close.assert_not_awaited()
        assert client.send_response.await_args.args[:2] == ("error", "over")
    with tenant_execution_scope(7):
        assert run.repo.long_snapshot(execution_id, CALL)["interaction"]["phase"] == "WAITING_INPUT"


async def test_revoked_status_returns_a_safe_error_on_the_websocket(interaction_runtime, browser, monkeypatch):
    run = interaction_runtime
    client, _, _ = browser
    execution_id, _, _ = await waiting(run)
    monkeypatch.setattr(run.service, "authorize", AsyncMock(side_effect=PlatformAgentPermissionError))
    await client._handle_message({"action": "check_status", "chat_id": CHAT_ID, "execution_id": execution_id})
    category, kind, payload = client.send_response.await_args.args
    assert (category, kind) == ("error", "over")
    assert payload["agent_interaction_error"] == "blocked"
    assert payload["data"] == {}
    assert "agent_interaction" not in payload


async def test_start_checks_existing_session_ownership(interaction_runtime, monkeypatch):
    run = interaction_runtime
    with tenant_execution_scope(7):
        run.repo.save_version(1, data=sample_graph())
        graph = await run.service.publish(run.publisher, FLOW_ID, 1)
        session_lookup = AsyncMock(
            return_value=SimpleNamespace(
                is_delete=False,
                tenant_id=7,
                user_id=99,
                api_subject_type=None,
                flow_id=FLOW_ID,
            )
        )
        monkeypatch.setattr(MessageSessionDao, "async_get_one", session_lookup)
        runtime = platform_agent.BrowserPlatformAgentRuntime(run.repo)
        with pytest.raises(PlatformAgentPermissionError):
            await runtime.prepare(run.user, FLOW_ID, SESSION, graph, published=True)
        session_lookup.assert_awaited_once_with(CHAT_ID)
        assert run.repo.find_session_execution(FLOW_ID, SESSION) is None


async def test_public_non_interaction_stop_keeps_existing_dispatch(browser):
    client, _, _ = browser
    client.session_subject = SimpleNamespace(subject_type="public_v3")
    client.close = AsyncMock()
    await client.handle_message({"action": "stop"})
    client.close.assert_awaited_once_with(force_stop=True)


@pytest.mark.parametrize("revoked_during_read", [False, True])
async def test_submit_then_reconnect_resumes_original_graph_and_attaches_to_its_output(
    interaction_runtime, browser, monkeypatch, revoked_during_read
):
    run = interaction_runtime
    client, callback, reference = browser
    feature = Path(__file__).resolve().parents[4] / "features/v3.0.0/125-kunlian-agent-interaction"
    graph = json.loads((feature / "mock-workflow.example.json").read_text())
    with tenant_execution_scope(7):
        execution, initial_dispatch = await prepare(run, graph)
    await asyncio.to_thread(run_worker, execution, initial_dispatch)
    execution_id = execution["execution_id"]
    with tenant_execution_scope(7):
        form = run.repo.long_snapshot(execution_id, CALL)["interaction"]
    interaction_id, revision = form["interaction_id"], form["form"]["revision"]
    initial = len(run.starts)

    def task(**_options):
        def decorate(function):
            function.request = SimpleNamespace(headers={"tenant_id": 7})
            return function

        return decorate

    resume = tasks.register_interaction_resume(SimpleNamespace(task=task))
    await client.handle_message(
        {
            "action": "agent_interaction_submit",
            "execution_id": execution_id,
            "interaction_id": interaction_id,
            "revision": revision,
            "submission_id": "reconnect",
            "answer": "same-run",
        }
    )
    with tenant_execution_scope(7):
        original = run.repo.long_snapshot(execution_id, CALL)
        dispatch_id = original["interaction"]["dispatch_id"]
    await asyncio.to_thread(resume, execution_id, interaction_id, dispatch_id)
    await asyncio.to_thread(resume, execution_id, interaction_id, dispatch_id)
    assert len(run.outputs) == 1 and "same-run" in str(run.outputs[0])
    assert len(run.starts) > initial
    assert run.starts.count("start_example") == 1
    reference[0] = execution_id
    callback.get_workflow_status.return_value = {"status": WorkflowStatus.SUCCESS.value}
    callback.async_get_workflow_status = AsyncMock(return_value={"status": WorkflowStatus.SUCCESS.value})
    callback.async_clear_workflow_status = AsyncMock()
    client.send_json = AsyncMock()
    del client.workflow_run

    async def events():
        if revoked_during_read:
            monkeypatch.setattr(run.service, "authorize", AsyncMock(side_effect=PlatformAgentPermissionError))
        yield {"category": "output_msg", "message": "protected-result"}

    callback.get_response_until_break = events
    await client.check_status({"chat_id": CHAT_ID, "execution_id": execution_id})
    if revoked_during_read:
        client.send_json.assert_not_awaited()
        assert client.send_response.await_args.args[2]["agent_interaction_error"] == "blocked"
    else:
        client.send_json.assert_awaited_once_with({"category": "output_msg", "message": "protected-result"})
    result = next(
        call.args[2]
        for call in client.send_response.await_args_list
        if call.args[:2] == ("processing", "info") and call.args[2]["agent_interaction"]["phase"] == "TERMINAL"
    )
    assert result["agent_long_task"]["agent_run_id"] == original["run_id"]
    assert result["agent_interaction"]["phase"] == "TERMINAL"
