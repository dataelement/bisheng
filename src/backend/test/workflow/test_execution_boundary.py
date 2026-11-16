"""Execution boundary regressions; all payloads are inert local data."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.chat.clients import workflow_client as client_module
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.workflow.domain.services import published_workflow_service as service_module
from bisheng.workflow.graph.graph_engine import GraphEngine

FORM = {"node_id": "input_1", "input_schema": {"tab": "form_input", "value": [{"key": "city", "value": "City"}]}}
DIALOG = {"node_id": "input_1", "input_schema": {"tab": "dialog_input", "key": "user_input"}}


@pytest.mark.parametrize(
    "schema,answer",
    [
        (FORM, {"input_1": {"city": "Paris"}, "tool_1": {"url": "changed"}}),
        (DIALOG, {"input_1": {"user_input": "hi", "code": "changed"}}),
    ],
)
def test_input_rejects_extra_nodes_and_executable_fields(schema, answer):
    with pytest.raises(WorkFlowInvalidUserInputError):
        RedisCallback._verify_input_schema(schema, answer)


def test_output_rejects_extra_inner_fields():
    message = SimpleNamespace(
        category="output_with_choose_msg", message=json.dumps({"node_id": "output_1", "key": "output_result"})
    )
    with pytest.raises(WorkFlowInvalidUserInputError):
        RedisCallback._update_old_message({"output_1": {"output_result": "yes", "url": "changed"}}, message, None, True)


@pytest.mark.parametrize(
    "schema,answer",
    [(FORM, {"input_1": {"city": "Paris"}}), (DIALOG, {"input_1": {"user_input": "hi", "dialog_files_content": []}})],
)
def test_defined_input_remains_accepted(schema, answer):
    RedisCallback._verify_input_schema(schema, answer)


def test_override_does_not_mutate_authoritative_graph():
    graph = {"nodes": [{"data": {"id": "tool_1", "group_params": [{"params": [{"key": "url", "value": "original"}]}]}}]}
    original = copy.deepcopy(graph)
    changed = RedisCallback.override_nodes_params(graph, {"tool_1": {"url": "changed"}})
    assert graph == original
    assert changed != original


@pytest.mark.parametrize("override", [{"missing": {"url": "changed"}}, {"tool_1": {"missing": "changed"}}])
def test_override_rejects_unknown_target(override):
    graph = {"nodes": [{"data": {"id": "tool_1", "group_params": [{"params": [{"key": "url", "value": "original"}]}]}}]}
    with pytest.raises(WorkFlowInvalidUserInputError):
        RedisCallback.override_nodes_params(graph, override)


async def test_websocket_rejects_message_workflow_switch_before_session_access(monkeypatch):
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_id, client.chat_id, client.session_subject = "allowed", "own", object()
    lookup = AsyncMock()
    monkeypatch.setattr(client_module.ChatSessionService, "get_subject_session_if_exists", lookup)
    with pytest.raises(HTTPException):
        await client.check_status({"flow_id": "different", "chat_id": "victim"})
    lookup.assert_not_awaited()
    assert client.chat_id == "own"


async def test_foreign_subject_fails_before_runtime_read(monkeypatch):
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_id, client.chat_id = "allowed", "own"
    client.session_subject = SessionSubject.natural_person(tenant_id=1, user_id=2)
    monkeypatch.setattr(
        client_module.ChatSessionService, "get_subject_session_if_exists", AsyncMock(side_effect=HTTPException(404))
    )
    callback = Mock()
    monkeypatch.setattr(client_module, "RedisCallback", callback)
    with pytest.raises(HTTPException):
        await client.check_status({"chat_id": "victim"})
    callback.assert_not_called()
    assert client.chat_id == "own"


@pytest.mark.parametrize("public_without_chat", [False, True])
async def test_use_only_init_ignores_client_graph(monkeypatch, public_without_chat):
    client = WorkflowClient.__new__(WorkflowClient)
    client.workflow, client.client_id, client.chat_id, client.user_id = None, "allowed", "chat", 2
    client.login_user = SimpleNamespace(user_id=2)
    client.execution_snapshot = {"channel": "public_v3"} if public_without_chat else None
    if public_without_chat:
        client.chat_id = ""
    client.check_status = AsyncMock(return_value=(True, "run"))
    client.get_execute_worker = AsyncMock(return_value="q")
    client.send_response, client.workflow_run = AsyncMock(), AsyncMock()
    callback = SimpleNamespace(async_set_workflow_data=AsyncMock(), async_set_workflow_status=AsyncMock())
    graph = {"nodes": [], "edges": [], "source": "persisted"}
    monkeypatch.setattr(client_module.FlowDao, "get_flow_by_id", Mock(return_value=SimpleNamespace(data=graph)))
    monkeypatch.setattr(client_module, "RedisCallback", Mock(return_value=callback))
    monkeypatch.setattr(client_module, "ensure_client_execution_lease", AsyncMock(return_value="skipped"))
    monkeypatch.setattr(client_module, "record_business_activity", AsyncMock())
    monkeypatch.setattr(client_module.execute_workflow, "apply_async", Mock())
    await client.init_workflow({"data": {"source": "client"}})
    callback.async_set_workflow_data.assert_awaited_once_with(graph)


@pytest.mark.parametrize("can_edit", [False, True])
async def test_draft_graph_requires_edit_and_keeps_editor_preview(monkeypatch, can_edit):
    client = WorkflowClient.__new__(WorkflowClient)
    client.workflow, client.client_id, client.chat_id, client.user_id = None, "wf", "", 2
    client.login_user = SimpleNamespace(user_id=2)
    client.execution_snapshot = None
    client.check_status = AsyncMock(return_value=(True, "run"))
    client.get_execute_worker = AsyncMock(return_value="q")
    client.send_response, client.workflow_run = AsyncMock(), AsyncMock()
    callback = SimpleNamespace(async_set_workflow_data=AsyncMock(), async_set_workflow_status=AsyncMock())
    monkeypatch.setattr(client_module, "RedisCallback", Mock(return_value=callback))
    monkeypatch.setattr(client_module, "ensure_client_execution_lease", AsyncMock(return_value="skipped"))
    monkeypatch.setattr(client_module, "record_business_activity", AsyncMock())
    monkeypatch.setattr(client_module.execute_workflow, "apply_async", Mock())
    gate = AsyncMock(side_effect=None if can_edit else UnAuthorizedError())
    monkeypatch.setattr(client_module, "require_business_action", gate)
    graph = {"nodes": [], "edges": [], "source": "draft"}
    await client.init_workflow({"data": graph})
    assert gate.await_args.kwargs["action"] == "edit"
    if can_edit:
        callback.async_set_workflow_data.assert_awaited_once_with(graph)
    else:
        callback.async_set_workflow_data.assert_not_awaited()
        client.check_status.assert_not_awaited()


async def test_published_override_requires_edit_before_writing(monkeypatch):
    monkeypatch.setattr(
        service_module.PublishedWorkflowService, "get_workflow", AsyncMock(return_value=SimpleNamespace(data={}))
    )
    gate = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(service_module, "require_business_action", gate, raising=False)
    lookup = AsyncMock(side_effect=AssertionError("must authorize before creating session"))
    monkeypatch.setattr(service_module.ChatSessionService, "get_subject_session_if_exists", lookup)
    with pytest.raises(UnAuthorizedError):
        await service_module.PublishedWorkflowService.prepare_invocation(
            workflow_id="wf",
            operator_user_id=2,
            session_subject=SessionSubject.natural_person(tenant_id=1, user_id=2),
            execution_snapshot=SimpleNamespace(tenant_id=1),
            session_id=None,
            override={"tool_1": {"url": "changed"}},
            user_input=None,
            message_id=None,
        )
    assert gate.await_args.kwargs["action"] == "edit"
    lookup.assert_not_awaited()


async def test_authorized_editor_override_is_enqueued(monkeypatch):
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(data=graph)
    monkeypatch.setattr(service_module.PublishedWorkflowService, "get_workflow", AsyncMock(return_value=workflow))
    gate = AsyncMock()
    monkeypatch.setattr(service_module, "require_business_action", gate)
    monkeypatch.setattr(
        service_module.ChatSessionService,
        "get_subject_session_if_exists",
        AsyncMock(return_value=SimpleNamespace(flow_id="wf")),
    )
    callback = SimpleNamespace(get_workflow_status=lambda: None, set_workflow_data=Mock(), set_workflow_status=Mock())
    monkeypatch.setattr(service_module, "RedisCallback", Mock(return_value=callback))
    monkeypatch.setattr(service_module.workflow_stateful_worker, "find_task_node", AsyncMock(return_value="q"))
    enqueue = Mock()
    monkeypatch.setattr(service_module.execute_workflow, "apply_async", enqueue)
    snapshot = SimpleNamespace(tenant_id=1, model_dump=lambda **kwargs: {"channel": "open_api_v2"})
    override = {"tool_1": {"url": "changed"}}
    await service_module.PublishedWorkflowService.prepare_invocation(
        workflow_id="wf",
        operator_user_id=2,
        session_subject=SessionSubject.natural_person(tenant_id=1, user_id=2),
        execution_snapshot=snapshot,
        session_id="chat_async_task_id",
        override=override,
        user_input=None,
        message_id=None,
    )
    assert gate.await_args.kwargs["action"] == "edit"
    callback.set_workflow_data.assert_called_once_with(graph, override=override)
    enqueue.assert_called_once()


@pytest.mark.parametrize("async_mode", [False, True])
async def test_engine_rejects_noninterrupted_node_before_any_mutation(async_mode):
    engine = GraphEngine.__new__(GraphEngine)
    engine.graph_config = {}
    engine.graph = SimpleNamespace(get_state=Mock(return_value=SimpleNamespace(next=("input_1",))))
    waiting = SimpleNamespace(type="input", node_params={"user_input": ""}, handle_input=Mock())
    downstream = SimpleNamespace(type="tool", handle_input=Mock())
    engine.nodes_map = {"input_1": waiting, "tool_1": downstream}
    engine._run, engine._arun = Mock(), AsyncMock()
    data = {"input_1": {"user_input": "hi"}, "tool_1": {"url": "changed"}}
    with pytest.raises(WorkFlowInvalidUserInputError):
        if async_mode:
            await engine.acontinue_run(data)
        else:
            engine.continue_run(data)
    waiting.handle_input.assert_not_called()
    downstream.handle_input.assert_not_called()


@pytest.mark.parametrize("async_mode", [False, True])
async def test_engine_accepts_defined_interrupted_input(async_mode):
    engine = GraphEngine.__new__(GraphEngine)
    engine.graph_config = {}
    engine.graph = SimpleNamespace(get_state=Mock(return_value=SimpleNamespace(next=("input_1",))))
    node = SimpleNamespace(
        type="input", node_params={"user_input": "", "dialog_files_content": []}, handle_input=Mock()
    )
    engine.nodes_map = {"input_1": node}
    engine._run, engine._arun = Mock(), AsyncMock()
    data = {"input_1": {"user_input": "hi", "dialog_files_content": []}}
    if async_mode:
        await engine.acontinue_run(data)
        engine._arun.assert_awaited_once_with(None)
    else:
        engine.continue_run(data)
        engine._run.assert_called_once_with(None)
    node.handle_input.assert_called_once_with(data["input_1"])


async def test_engine_accepts_interrupted_output_not_its_fake_id():
    engine = GraphEngine.__new__(GraphEngine)
    engine.graph_config = {}
    engine.graph = SimpleNamespace(get_state=Mock(return_value=SimpleNamespace(next=("output_1_fake",))))
    output = SimpleNamespace(id="output_1", handle_input=Mock())
    fake = SimpleNamespace(type="fake_output", output_node=output, get_input_schema=lambda: ["output_result"])
    engine.nodes_map = {"output_1": output, "output_1_fake": fake}
    engine._run = Mock()
    engine.continue_run({"output_1": {"output_result": "yes"}})
    output.handle_input.assert_called_once_with({"output_result": "yes"})


@pytest.mark.parametrize("message_id", [None, 4, 6])
def test_pending_message_replay_is_rejected(message_id):
    callback = RedisCallback.__new__(RedisCallback)
    with pytest.raises(WorkFlowInvalidUserInputError):
        callback._verify_pending_input({"message": FORM, "message_id": 5}, {"input_1": {"city": "Paris"}}, message_id)


async def test_v1_route_binds_natural_person_subject(monkeypatch):
    from bisheng.api.v1 import workflow as endpoint

    dispatch = AsyncMock()
    monkeypatch.setattr(endpoint, "require_business_action", AsyncMock())
    monkeypatch.setattr(endpoint.chat_manager, "dispatch_client", dispatch)
    await endpoint.workflow_ws(workflow_id="wf", websocket=Mock(), login_user=SimpleNamespace(tenant_id=7, user_id=9))
    assert dispatch.await_args.kwargs["session_subject"] == SessionSubject.natural_person(tenant_id=7, user_id=9)


@pytest.mark.parametrize(
    "subject,session,allowed",
    [
        (SessionSubject.natural_person(tenant_id=1, user_id=2), {"tenant_id": 1, "user_id": 3}, False),
        (SessionSubject.natural_person(tenant_id=1, user_id=2), {"tenant_id": 2, "user_id": 2}, False),
        (
            SessionSubject.service_account(
                tenant_id=1, service_account_id=5, resource_owner_user_id=2, external_user_id="a"
            ),
            {
                "tenant_id": 1,
                "user_id": 2,
                "api_subject_type": "service_account",
                "api_subject_id": 5,
                "external_user_id": "b",
            },
            False,
        ),
        (
            SessionSubject.public_v3(tenant_id=1, operator_user_id=2, resource_id="wf"),
            {"tenant_id": 1, "user_id": 99, "api_subject_type": "public_v3", "flow_id": "wf"},
            True,
        ),
    ],
)
def test_existing_subject_contract_preserves_public_and_service_isolation(subject, session, allowed):
    row = {
        "is_delete": False,
        "api_subject_type": None,
        "api_subject_id": None,
        "external_user_id": None,
        "flow_id": "wf",
    }
    row.update(session)
    assert subject.matches(SimpleNamespace(**row)) is allowed
