"""覆盖 AC: AC-11, AC-12, AC-14。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.flow import (
    PlatformKnowledgeExecutionError,
    PlatformKnowledgePermissionError,
    WorkFlowInvalidUserInputError,
)
from bisheng.core.config.settings import PlatformKnowledgeConf
from bisheng.workflow.application.platform_knowledge import KnowledgeRun
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest


async def test_commit_rechecks_actor_and_rejects_revoked_execution():
    config = PlatformKnowledgeConf()
    service = SimpleNamespace(
        config=config,
        config_source=lambda: config,
        authorize=AsyncMock(return_value=SimpleNamespace(token_version=3)),
    )
    store = SimpleNamespace(check=lambda *_: None, commit=lambda *_: pytest.fail("stale output committed"))
    run = KnowledgeRun(
        service,
        store,
        {
            "execution_id": "fixture",
            "workflow_id": "flow",
            "action": "use",
            "token_version": 2,
            "environment": canonical_digest(config.model_dump()),
        },
        "owner",
        SimpleNamespace(user_id=12, tenant_id=7),
    )
    with pytest.raises(PlatformKnowledgePermissionError):
        await run.commit("node", 0)


async def test_published_path_rejects_non_user_before_creating_session(monkeypatch):
    from bisheng.workflow.domain.services import published_workflow_service as published

    service = published.PublishedWorkflowService
    monkeypatch.setattr(
        service,
        "get_workflow",
        AsyncMock(
            return_value=SimpleNamespace(
                data={"nodes": [{"data": {"type": "platform_knowledge_retriever"}}]},
            )
        ),
    )
    session = AsyncMock()
    monkeypatch.setattr(published.ChatSessionService, "get_subject_session_if_exists", session)
    with pytest.raises(PlatformKnowledgePermissionError):
        await service.prepare_invocation(
            workflow_id="flow",
            operator_user_id=12,
            session_subject=None,
            execution_snapshot=SimpleNamespace(authorization_subject_type="service_account", effective_user_id=12),
            session_id=None,
            override=None,
            user_input=None,
            message_id=None,
        )
    session.assert_not_awaited()


def test_worker_never_runs_after_owner_authorization_fails(monkeypatch):
    from unittest.mock import Mock

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.worker.workflow import tasks

    status = Mock()
    claimed = SimpleNamespace(
        authorize=AsyncMock(side_effect=PlatformKnowledgePermissionError()),
        store=SimpleNamespace(status=status),
        execution_id="test-run",
        owner="owner",
    )
    monkeypatch.setattr(tasks, "claim_knowledge_execution", Mock(return_value=claimed))
    runner = Mock()
    with tenant_execution_scope(7):
        tasks._run_knowledge_workflow(
            {"execution_id": "test-run", "dispatch_id": "dispatch"},
            None,
            runner,
            "session",
            "flow",
            "chat",
            12,
            "platform",
            None,
            "START",
        )
    runner.assert_not_called()
    status.assert_called_once_with("test-run", "owner", "FAILED", PlatformKnowledgePermissionError.Msg)


def test_rejected_event_never_falls_back_to_legacy_queue():
    from unittest.mock import Mock

    from bisheng.worker.workflow.redis_callback import RedisCallback

    callback = RedisCallback.__new__(RedisCallback)
    callback.platform_agent_execution_id = None
    callback.platform_knowledge_execution_id = "stale"
    callback.platform_knowledge_owner = "worker"
    callback.knowledge_store = SimpleNamespace(event=Mock(return_value=False))
    callback.redis_client = Mock()
    output = {"category": "output_msg", "message": {"msg": "late result"}}
    callback.insert_workflow_response(output)
    callback.knowledge_store.event.assert_called_once_with("stale", "worker", output)
    callback.redis_client.rpush.assert_not_called()


async def test_invalid_published_input_does_not_consume_resume(monkeypatch):
    from bisheng.workflow.application import platform_knowledge
    from bisheng.workflow.domain.services import published_workflow_service as published

    callback = published.RedisCallback.__new__(published.RedisCallback)
    callback.chat_id = "chat"
    callback.platform_knowledge_execution_id = "run"
    callback.workflow_input_key = "input"
    callback.knowledge_store = SimpleNamespace(stop=Mock())
    callback.redis_client = SimpleNamespace(aset=AsyncMock())
    callback.get_workflow_status = lambda: {"status": "INPUT"}
    callback.get_platform_agent_reference = lambda: None
    monkeypatch.setattr(published, "RedisCallback", lambda *_, **__: callback)
    monkeypatch.setattr(
        published.PublishedWorkflowService,
        "get_workflow",
        AsyncMock(
            return_value=SimpleNamespace(
                data={"nodes": [{"data": {"type": "platform_knowledge_retriever"}}]},
            )
        ),
    )
    monkeypatch.setattr(
        published.ChatSessionService,
        "get_subject_session_if_exists",
        AsyncMock(
            return_value=SimpleNamespace(flow_id="flow"),
        ),
    )
    monkeypatch.setattr(published.workflow_stateful_worker, "find_task_node", AsyncMock())
    from bisheng.worker.workflow import redis_callback

    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(redis_callback.ChatMessageDao, "aget_message_by_id", lookup)
    resume = AsyncMock(return_value={"execution_id": "run", "dispatch_id": "resume"})
    monkeypatch.setattr(platform_knowledge.BrowserPlatformKnowledgeRuntime, "resume", resume)
    snapshot = SimpleNamespace(
        authorization_subject_type="user",
        effective_user_id=12,
        tenant_id=7,
        model_dump=lambda **_: {},
    )
    kwargs = {
        "workflow_id": "flow",
        "operator_user_id": 12,
        "session_subject": None,
        "execution_snapshot": snapshot,
        "session_id": "chat_run",
        "override": None,
        "user_input": {"input": {"question": "text"}},
        "message_id": 1,
    }
    with pytest.raises(WorkFlowInvalidUserInputError):
        await published.PublishedWorkflowService.prepare_invocation(**kwargs)
    resume.assert_not_awaited()
    callback.knowledge_store.stop.assert_not_called()
    callback.redis_client.aset.assert_not_awaited()
    lookup.return_value = SimpleNamespace(
        chat_id="chat",
        category=redis_callback.WorkflowEventType.UserInput.value,
        message=json.dumps({"node_id": "input", "input_schema": {"tab": "dialog_input", "key": "question"}}),
    )
    callback.save_chat_message = Mock(side_effect=lambda _: resume.assert_awaited_once())
    callback.workflow_expire_time = 10
    callback.async_set_workflow_status = AsyncMock()
    dispatch = Mock()
    monkeypatch.setattr(published.continue_workflow, "apply_async", dispatch)
    await published.PublishedWorkflowService.prepare_invocation(**kwargs)
    callback.redis_client.aset.assert_awaited_once()
    assert dispatch.call_args.kwargs["kwargs"]["platform_knowledge_execution"] == resume.return_value


@pytest.mark.parametrize("replaced_agent", [False, True])
def test_stale_worker_does_not_persist_downstream_output(monkeypatch, replaced_agent):
    from bisheng.worker.workflow import redis_callback

    callback = redis_callback.RedisCallback.__new__(redis_callback.RedisCallback)
    callback.platform_knowledge_execution_id = "stopped"
    callback.platform_knowledge_owner = "worker"
    callback.platform_agent_execution_id = "old-agent" if replaced_agent else None
    callback.get_platform_agent_reference = lambda: "new-agent"
    callback.knowledge_store = SimpleNamespace(
        check=Mock(
            side_effect=None if replaced_agent else PlatformKnowledgeExecutionError,
        )
    )
    callback.chat_id = "chat"
    callback.workflow_id = "flow"
    callback.user_id = 12
    monkeypatch.setattr(callback, "_finalize_citation_items", Mock(return_value=[]))
    insert = Mock(side_effect=AssertionError("stopped output persisted"))
    monkeypatch.setattr(redis_callback.ChatMessageDao, "insert_one", insert)
    with pytest.raises(PlatformKnowledgeExecutionError):
        callback.save_chat_message(redis_callback.ChatResponse(category="output_msg", message="late result"))
    insert.assert_not_called()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_mixed_event_reader_discards_replaced_agent_reference(asynchronous):
    from bisheng.worker.workflow.redis_callback import RedisCallback

    callback = RedisCallback.__new__(RedisCallback)
    callback.platform_knowledge_execution_id = "knowledge-run"
    callback.get_platform_agent_reference = lambda: "new-agent"
    callback.knowledge_store = SimpleNamespace(
        pop=Mock(
            side_effect=[
                json.dumps(
                    {
                        "category": "output_msg",
                        "message": "stale output",
                        "_platform_agent_execution_id": "old-agent",
                    }
                ),
                None,
            ]
        )
    )
    response = await callback.async_get_workflow_response() if asynchronous else callback.get_workflow_response()
    assert response is None


async def test_new_plain_published_run_clears_previous_knowledge_reference(monkeypatch):
    from bisheng.workflow.domain.services import published_workflow_service as published

    callback = SimpleNamespace(
        platform_knowledge_execution_id="previous-run",
        get_workflow_status=lambda: None,
        clear_platform_agent_reference=Mock(),
        clear_platform_knowledge_reference=Mock(),
        set_workflow_status=Mock(),
        set_workflow_data=Mock(),
    )
    monkeypatch.setattr(published, "RedisCallback", lambda *_, **__: callback)
    graph = {"nodes": [], "edges": []}
    monkeypatch.setattr(
        published.PublishedWorkflowService, "get_workflow", AsyncMock(return_value=SimpleNamespace(data=graph))
    )
    monkeypatch.setattr(
        published.ChatSessionService,
        "get_subject_session_if_exists",
        AsyncMock(
            return_value=SimpleNamespace(flow_id="flow"),
        ),
    )
    monkeypatch.setattr(published.workflow_stateful_worker, "find_task_node", AsyncMock())
    dispatch = Mock()
    monkeypatch.setattr(published.execute_workflow, "apply_async", dispatch)
    await published.PublishedWorkflowService.prepare_invocation(
        workflow_id="flow",
        operator_user_id=12,
        session_subject=None,
        execution_snapshot=SimpleNamespace(model_dump=lambda **_: {}),
        session_id="chat_run",
        override=None,
        user_input=None,
        message_id=None,
    )
    callback.clear_platform_knowledge_reference.assert_called_once()
    callback.set_workflow_data.assert_called_once_with(graph, override=None)
    dispatch.assert_called_once()
