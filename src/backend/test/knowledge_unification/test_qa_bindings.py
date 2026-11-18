"""Native QA consumers retain their original type and model-slot lifecycle.

覆盖 AC: AC-55, AC-65, AC-70, AC-71, AC-74, AC-87, AC-88, AC-89.
SQL, original identity, business and R2 are real; provider/projection/object
transports are isolated. SQLite does not prove production locks or E2E.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeNoEmbeddingError
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeCreate
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain import share_fallback
from test.knowledge_unification import test_kn_model_bindings as bindings
from test.knowledge_unification import test_kn_model_creation as consumers

store = bindings.store
tenant = bindings.tenant
business = bindings.business
creation = consumers.creation


@pytest.fixture
async def qa_service(creation, monkeypatch):
    context, _ = creation
    for model in (KnowledgeFile, QAKnowledge):
        model.__table__.create(context.sync)
    events = []
    monkeypatch.setattr(
        KnowledgeService,
        "_project_library_deletion",
        AsyncMock(side_effect=lambda *a, **k: events.append("projection")),
    )
    monkeypatch.setattr(
        KnowledgeService, "delete_knowledge_file_in_vector", Mock(side_effect=lambda *a: events.append("vectors"))
    )
    monkeypatch.setattr(
        KnowledgeService, "delete_knowledge_file_in_minio", Mock(side_effect=lambda *a: events.append("objects"))
    )
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_hook", Mock())
    monkeypatch.setattr(KnowledgeService.audit_telemetry_service, "telemetry_delete_knowledge", Mock())
    context.cleanup_events = events
    async with context.sessions() as session:
        await App.acreate(
            session,
            Knowledge(id=40, tenant_id=101, user_id=7, name="native QA", type=1, model="11"),
            login_user=context.user,
            project_created=AsyncMock(),
        )
        session.add_all(
            [
                KnowledgeFile(id=ident, tenant_id=owner, knowledge_id=40, file_name=f"file{ident}")
                for ident, owner in ((401, 101), (402, 202))
            ]
        )
        session.add_all(
            [
                QAKnowledge(id=ident, tenant_id=owner, knowledge_id=40, questions=["q"], answers="a")
                for ident, owner in ((401, 101), (402, 202))
            ]
        )
        await session.commit()
    return context


def state(context):
    facts = bindings.state(context)
    with context.sync.connect() as connection:
        for model in (KnowledgeFile, QAKnowledge):
            facts[model.__tablename__] = (
                connection.execute(sa.select(model.__table__).order_by(model.id)).mappings().all()
            )
    return facts


async def remove(context, *, only_clear):
    return await asyncio.to_thread(
        KnowledgeService.delete_knowledge,
        request=None,
        login_user=context.user,
        knowledge_id=40,
        only_clear=only_clear,
    )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("wrapper", [False, True])
async def test_original_qa_creation_consumers_bind_actual_embedding(creation, monkeypatch, asynchronous, wrapper):
    context, projection = creation
    if wrapper:
        monkeypatch.setattr(
            consumers.module.KnowledgeDao,
            "get_knowledge_by_name",
            Mock(return_value=None),
        )
        monkeypatch.setattr(consumers.module.KnowledgeDao, "aget_knowledge_by_name", AsyncMock(return_value=None))
        monkeypatch.setattr(
            share_fallback,
            "get_model_by_id_with_share_fallback",
            Mock(return_value=SimpleNamespace(model_type="embedding")),
        )
        monkeypatch.setattr(
            share_fallback,
            "aget_model_by_id_with_share_fallback",
            AsyncMock(return_value=SimpleNamespace(model_type="embedding")),
        )
        payload = KnowledgeCreate(name="QA wrapper", type=1, model="11")
        if asynchronous:
            row = await KnowledgeService.acreate_knowledge(None, context.user, payload)
        else:
            row = await asyncio.to_thread(KnowledgeService.create_knowledge, None, context.user, payload)
    else:
        row, _ = await consumers.create(context, asynchronous=asynchronous, kind=1)
    facts = bindings.state(context)
    actual = next(value for value in facts["knowledge"] if value["id"] == row.id)
    assert (actual["type"], actual["model"], actual["tenant_id"]) == (1, "11", 101)
    references = [value for value in facts["business_resource_reference"] if value["source_id"] == str(row.id)]
    assert [(value["slot_key"], value["target_id"]) for value in references] == [("model", "11")]
    projection.assert_awaited_once_with(context.user, row)
    if asynchronous:
        consumers.module.KnowledgeRag.init_knowledge_milvus_vectorstore.assert_not_called()
    else:
        KnowledgeService._init_knowledge_indices_sync.assert_called_once()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_qa_creation_without_embedding_keeps_original_rejection_and_no_rows(creation, asynchronous):
    context, projection = creation
    before = bindings.state(context)
    with pytest.raises(KnowledgeNoEmbeddingError):
        await consumers.create(context, asynchronous=asynchronous, kind=1, model=None)
    assert bindings.state(context) == before
    projection.assert_not_called()


@pytest.mark.parametrize("only_clear", [False, True])
async def test_clear_qa_removes_qa_rows(qa_service, only_clear):
    context = qa_service
    before = state(context)
    assert await remove(context, only_clear=only_clear) is True
    after = state(context)
    assert [value["tenant_id"] for value in after["knowledgefile"]] == [202]
    assert [value["tenant_id"] for value in after["qaknowledge"]] == [202]
    assert context.cleanup_events == ["projection", "vectors", "objects"]
    if only_clear:
        for key in ("knowledge", "business_resource_reference", "business_reference_set"):
            assert after[key] == before[key]
        KnowledgeService.delete_knowledge_hook.assert_not_called()
    else:
        assert all(value["id"] != 40 for value in after["knowledge"])
        assert not after["business_resource_reference"]
        source = next(
            value
            for value in after["business_reference_set"]
            if value["source_id"] == "40" and value["record_kind"] == "source"
        )
        assert source["ready"] and not source["effective"]


async def test_clear_normal_kb_skips_qa_rows(qa_service):
    context = qa_service
    with Session(context.sync) as session, session.begin():
        session.execute(sa.update(Knowledge).where(Knowledge.id == 40).values(type=0))
    before = state(context)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    sa.event.listen(context.sync, "before_cursor_execute", capture)
    try:
        await remove(context, only_clear=True)
    finally:
        sa.event.remove(context.sync, "before_cursor_execute", capture)
    assert not any("delete from qaknowledge" in value for value in statements)
    assert state(context)["qaknowledge"] == before["qaknowledge"]


@pytest.mark.parametrize("failure", ["projection", "objects", "references"])
async def test_qa_actual_consumer_failure_keeps_business_and_references(qa_service, monkeypatch, failure):
    context = qa_service
    before = state(context)
    if failure == "projection":
        KnowledgeService._project_library_deletion.side_effect = RuntimeError("transport failed")
    elif failure == "objects":
        KnowledgeService.delete_knowledge_file_in_minio.side_effect = RuntimeError("transport failed")
    else:
        monkeypatch.setattr(
            context.runtime, "apply_source_bindings", Mock(side_effect=RuntimeError("transport failed"))
        )
    with pytest.raises(RuntimeError, match="transport failed"):
        await remove(context, only_clear=False)
    assert state(context) == before


async def test_actual_qa_model_change_keeps_old_and_pending_slots_and_qa_dispatch(qa_service, monkeypatch):
    context = qa_service
    dispatch = Mock()
    monkeypatch.setattr(KnowledgeService, "_dispatch_model_rebuild", dispatch)
    row = await asyncio.to_thread(
        KnowledgeService.update_knowledge_model,
        login_user=context.user,
        knowledge_id=40,
        model_id=12,
    )
    assert row.type == 1 and row.model == "11"
    assert row.model_transition["pending_model_id"] == "12"
    refs = state(context)["business_resource_reference"]
    assert {(value["slot_key"], value["target_id"]) for value in refs} == {
        ("model", "11"),
        ("model_transition.pending_model_id", "12"),
    }
    command = dispatch.call_args.args[0]
    assert (command.type, command.tenant_id, command.knowledge_id) == (1, 101, 40)
