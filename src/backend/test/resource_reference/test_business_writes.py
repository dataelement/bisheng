"""AC-07/08/13: actual assistant and workflow writes commit without reverse-index writes."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlmodel import select

from bisheng.api.services import assistant as assistant_service
from bisheng.api.services import flow as flow_service
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.database.models.assistant import Assistant
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_as_bindings as assistant_fixtures
from test.knowledge_unification import test_wf_create as workflow_fixtures
from test.knowledge_unification import test_wf_save as workflow_save
from test.knowledge_unification.test_wf_extract import graph, node

assistant_business, assistant_tenant = assistant_fixtures.assistant_business, assistant_fixtures.assistant_tenant
bindings, store, tenant = workflow_fixtures.bindings, workflow_fixtures.store, workflow_fixtures.tenant
saved = workflow_save.saved


async def test_assistant_repairs_original_legacy_name_without_retention_marker(assistant_business, monkeypatch):
    ctx = assistant_business
    async with ctx.sessions() as session, session.begin():
        session.add(Assistant(id="assistant-a", tenant_id=101, user_id=7, name="legacy", model_name="old name"))
    notify = AsyncMock()
    monkeypatch.setattr(assistant_service, "notify_reference_sync", notify)
    await assistant_service.AssistantService._persist_assistant_changes(
        "assistant-a", ctx.user, changes={"prompt": "changed"}
    )
    with pytest.raises(ResourceReferenceInvalidError):
        await assistant_service.AssistantService._persist_assistant_changes(
            "assistant-a", ctx.user, changes={"model_name": "another name"}
        )
    await assistant_service.AssistantService._persist_assistant_changes(
        "assistant-a", ctx.user, changes={"model_name": "2"}
    )
    async with ctx.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).model_name == "2"
        assert not (await session.exec(select(BusinessResourceReference))).all()
    assert notify.await_count == 2


async def test_workflow_save_ignores_missing_index_and_notifies_after_commit(saved, monkeypatch):
    ctx = saved
    async with ctx.session_factory() as session, session.begin():
        await session.execute(delete(BusinessReferenceSet).where(BusinessReferenceSet.tenant_id == 101))
    notified = []

    async def observe(*args):
        assert json.loads(workflow_fixtures.rows(ctx, "flowversion")[1]["data"]) == graph(
            node("llm", "llm", model_id=7)
        )
        notified.append(args)

    monkeypatch.setattr(flow_service, "notify_reference_sync", observe)
    result = await workflow_save.save(ctx, 2, graph(node("llm", "llm", model_id=7)))
    assert result.status_code == 200 and len(notified) == 1
    assert not workflow_fixtures.rows(ctx, "business_resource_reference")


async def test_business_commit_failure_never_schedules_reference_sync(assistant_business, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel.ext.asyncio.session import AsyncSession

    ctx = assistant_business
    async with ctx.sessions() as session, session.begin():
        session.add(Assistant(id="assistant-a", tenant_id=101, user_id=7, name="original", prompt="before"))
    notify = AsyncMock()
    monkeypatch.setattr(assistant_service, "notify_reference_sync", notify)
    monkeypatch.setattr(AsyncSession, "commit", AsyncMock(side_effect=SQLAlchemyError("commit failed")))
    with pytest.raises(SQLAlchemyError):
        await assistant_service.AssistantService._persist_assistant_changes(
            "assistant-a", ctx.user, changes={"prompt": "after"}
        )
    notify.assert_not_awaited()
    async with ctx.sessions() as session:
        assert (await session.get(Assistant, "assistant-a")).prompt == "before"
