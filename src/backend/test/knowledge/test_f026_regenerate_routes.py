"""Drive the actual workbench SSE and history routes over an isolated SQL store."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, LinsightSessionVersionDao
from bisheng.workstation.api.endpoints import chat
from bisheng.workstation.domain.services import chat_service as svc


@pytest.fixture
async def routes(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for model in (MessageSession, ChatMessage, LinsightSessionVersion):
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    for mod in (
        "database.models.message",
        "database.models.session",
        "linsight.domain.models.linsight_session_version",
    ):
        monkeypatch.setattr(f"bisheng.{mod}.get_async_db_session", sessions)
    with tenant_execution_scope(1):
        async with sessions() as session:
            session.add(MessageSession(chat_id="chat", name="named", flow_type=15, user_id=42, tenant_id=1))
            await session.commit()
    user = SimpleNamespace(user_id=42, tenant_id=1)
    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[chat.LoginUserDep.dependency] = lambda: user
    app.dependency_overrides[chat.ShareLinkDep.dependency] = lambda: None

    # Model, FGA, Redis and worker boundaries only. Keep both question writers,
    # session/version DAOs, route dispatch, scope resolution and projection real.
    class FakeLLM:
        async def astream(self, _messages):
            yield SimpleNamespace(content="ok", additional_kwargs={})

    model = SimpleNamespace(id="727", displayName="model", visual=False)
    monkeypatch.setattr(
        "bisheng.dsh.domain.services.model_catalog.user_workbench_models", AsyncMock(return_value=[model])
    )
    monkeypatch.setattr(svc.WorkStationService, "aget_config", AsyncMock(return_value=SimpleNamespace(systemPrompt="")))
    monkeypatch.setattr(svc.LLMService, "get_bisheng_llm", AsyncMock(return_value=FakeLLM()))
    monkeypatch.setattr(svc.SensitiveWordPolicyService, "evaluate_workbench_user_text", lambda *a: None)
    monkeypatch.setattr(svc.SensitiveWordPolicyService, "is_workbench_content_safety_active", lambda *a: False)
    monkeypatch.setattr(svc.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(0, None)))
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(svc.DailyCitationScope, "load", AsyncMock())
    monkeypatch.setattr(svc, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(svc.WorkStationService, "get_chat_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "log_telemetry_events", AsyncMock())
    monkeypatch.setattr(svc, "save_message_citations", AsyncMock())
    monkeypatch.setattr(svc, "save_message_citations_sync", MagicMock())
    monkeypatch.setattr(svc, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(
        svc.KnowledgeDao, "aget_list_by_ids", AsyncMock(return_value=[SimpleNamespace(id=7, name="kb", description="")])
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.aget_file_by_filters",
        AsyncMock(return_value=[]),
    )
    prepare = AsyncMock(return_value=([], []))
    monkeypatch.setattr(svc, "_prepare_tools", prepare)
    allowed = AsyncMock(return_value=[7])
    monkeypatch.setattr(KnowledgePermissionService, "filter_knowledge_ids_by_action_async", allowed)
    tags = AsyncMock()
    monkeypatch.setattr(KnowledgeSpaceTagFilterService, "validate_selection", tags)
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.task_submit_service._consume_task_invite", AsyncMock(return_value=False)
    )
    enqueue = AsyncMock()
    monkeypatch.setattr("bisheng.linsight.domain.utils.enqueue_session_for_execution", enqueue)
    try:
        with tenant_execution_scope(1):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                yield SimpleNamespace(client=client, prepare=prepare, allowed=allowed, tags=tags, enqueue=enqueue)
    finally:
        await engine.dispose()


def selection(tag):
    return {"knowledge_space_ids": [7], "knowledge_space_tag_filters": {"7": tag}}


async def send(routes, **kwargs):
    response = await routes.client.post(
        "/chat/completions",
        json={"conversationId": "chat", "clientTimestamp": "0", "model": "727", "text": "q", **kwargs},
    )
    response.raise_for_status()
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


async def history(routes):
    return (await routes.client.get("/messages/chat/agent")).json()["data"]


async def test_question_history_and_both_regenerate_destinations(routes):
    first = await send(routes, use_knowledge_base=selection(11))
    assert first[0]["message"]["knowledge_scope_recorded"] is True
    original_id = first[0]["message"]["messageId"]
    assert (await history(routes))[0]["knowledge_scope_recorded"] is True
    regen = {"isRegenerate": True, "messageId": original_id, "use_knowledge_base": selection(22)}
    for current, tag in ((False, 11), (True, 22)):
        events = await send(routes, **regen, useCurrentMaterials=current)
        assert events[0]["message"]["messageId"] != original_id
        assert routes.prepare.await_args.kwargs["knowledge_bases_info"][0]["selected_tag_id"] == tag
        assert any(e.get("final") for e in events)
    task = await send(routes, **regen, task_mode=True)
    assert task[0]["event"] == "linsight_task_handoff", task
    version = await LinsightSessionVersionDao.get_by_id(task[0]["data"]["session_version_id"])
    assert version.knowledge_space_ids == [7] and version.knowledge_space_tag_filters == {"7": 11}
    questions = [r for r in await history(routes) if r["category"] == "question"]
    assert len(questions) == 4 and all(r["knowledge_scope_recorded"] for r in questions)
    assert questions[-1]["extra"]["linsight_session_version_id"] == version.id
    for row, tag in zip(questions, (11, 11, 22, 11), strict=True):
        saved = await ChatMessageDao.aget_message_by_id(row["message_id"])
        assert json.loads(saved.extra)["knowledge_scope"]["knowledge_space_tag_filters"] == {"7": tag}


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": 99},
        {"tenant_id": 2},
        {"chat_id": "other"},
        {"category": "answer"},
        {"is_bot": True},
        {"type": "output"},
        {"flow_id": "workflow"},
        {"extra": "{}"},
        {
            "extra": json.dumps(
                {
                    "knowledge_scope": {
                        "version": 1,
                        "recorded": True,
                        "knowledge_space_ids": [7],
                        "organization_knowledge_ids": [],
                    }
                }
            )
        },
    ],
)
async def test_unrecoverable_never_dispatches_or_inserts(routes, overrides):
    row = await ChatMessageDao.ainsert_one(
        ChatMessage(
            **{
                "user_id": 42,
                "tenant_id": 1,
                "chat_id": "chat",
                "flow_id": "",
                "category": "question",
                "is_bot": False,
                "type": "over",
                "message": '{"query":"q"}',
                "extra": json.dumps(
                    {
                        "knowledge_scope": {
                            "version": 1,
                            "recorded": True,
                            "organization_knowledge_ids": [],
                            **selection(11),
                        }
                    }
                ),
                **overrides,
            }
        )
    )
    before = await history(routes)
    for task in (False, True):
        failed = await send(
            routes, isRegenerate=True, messageId=row.id, task_mode=task, use_knowledge_base=selection(22)
        )
        assert [e["status_code"] for e in failed] == [12048]
    assert await history(routes) == before
    routes.prepare.assert_not_awaited()
    routes.enqueue.assert_not_awaited()


async def test_legacy_scope_requires_explicit_current_map_and_keeps_original(routes):
    first = await send(routes, use_knowledge_base={"knowledge_space_ids": [7]})
    question = first[0]["message"]
    assert question["knowledge_scope_recorded"] is False
    target = {"isRegenerate": True, "overrideParentMessageId": question["messageId"]}
    assert (await send(routes, **target))[0]["status_code"] == 12048
    assert (await send(routes, **target, useCurrentMaterials=True, use_knowledge_base={"knowledge_space_ids": [7]}))[0][
        "status_code"
    ] == 12048
    confirmed = await send(
        routes,
        **target,
        useCurrentMaterials=True,
        use_knowledge_base={"knowledge_space_ids": [7], "knowledge_space_tag_filters": {}},
    )
    assert confirmed[0]["message"]["knowledge_scope_recorded"] is True
    assert [r["knowledge_scope_recorded"] for r in await history(routes) if r["category"] == "question"] == [
        False,
        True,
    ]
    for invalid in (None, "user-pending", "9999999999999999999"):
        assert (await send(routes, isRegenerate=True, messageId=invalid))[0]["status_code"] == 12048
    invalid = await routes.client.post(
        "/chat/completions",
        json={
            "clientTimestamp": "0",
            "model": "727",
            "use_knowledge_base": {"knowledge_space_ids": [7], "knowledge_space_tag_filters": None},
        },
    )
    assert invalid.status_code == 422


async def test_revoked_or_deleted_tag_never_searches_or_enqueues(routes):
    from bisheng.common.errcode.tag import TagNotExistError

    original = (await send(routes, use_knowledge_base=selection(11)))[0]["message"]["messageId"]
    routes.prepare.reset_mock()
    for revoked in (True, False):
        routes.allowed.return_value = [] if revoked else [7]
        routes.tags.side_effect = None if revoked else TagNotExistError()
        for task in (False, True):
            result = await send(routes, isRegenerate=True, messageId=original, task_mode=task)
            assert result[0]["status_code"] == 12048
    routes.tags.assert_awaited_with({7: 11})
    routes.prepare.assert_not_awaited()
    routes.enqueue.assert_not_awaited()
