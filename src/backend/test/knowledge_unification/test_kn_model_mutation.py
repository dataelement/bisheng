"""Legacy model update/delete consumers use real business/R2 transactions.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
Projection/queue/object-store transports are doubles; actual endpoint, service,
Knowledge/QA/file/reference SQL and TargetOwner receipts are exercised.
"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlmodel import Session

from bisheng.api.v1.schemas import UpdateKnowledgeReq
from bisheng.common.errcode.knowledge import KnowledgeNoEmbeddingError
from bisheng.knowledge.api.endpoints import knowledge as api
from bisheng.knowledge.domain.services import knowledge_service as service_module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain.models.llm_server import LLMModel
from test.knowledge_unification import test_kn_model_lifecycle_transaction as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
lifecycle = fixtures.lifecycle


@pytest.fixture
def consumer(lifecycle, monkeypatch):
    context = lifecycle

    @contextmanager
    def sessions():
        with Session(context.sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(service_module, "get_sync_db_session", sessions)
    # Legacy calls must fail locally rather than use unrelated real middleware.
    monkeypatch.setattr(api.LLMDao, "get_model_by_id", Mock(return_value=SimpleNamespace(model_type="embedding")))
    for method in ("query_by_id", "update_one", "delete_knowledge"):
        monkeypatch.setattr(
            service_module.KnowledgeDao, method, Mock(side_effect=AssertionError("separate DAO transaction"))
        )
    monkeypatch.setattr(KnowledgeService, "_project_library_deletion", AsyncMock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_vector", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_minio", Mock())
    monkeypatch.setattr(KnowledgeService, "_init_knowledge_indices_sync", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_hook", Mock())
    monkeypatch.setattr(KnowledgeService.audit_telemetry_service, "telemetry_delete_knowledge", Mock())
    dispatch = Mock()
    monkeypatch.setattr(KnowledgeService, "_dispatch_model_rebuild", dispatch, raising=False)
    return context, dispatch


async def update(context, model=12, hint=None):
    request = UpdateKnowledgeReq(
        knowledge_id=40, model_id=model, model_type=hint, knowledge_name="renamed", description="new description"
    )
    return await asyncio.to_thread(api.update_knowledge_model, login_user=context.user, req_data=request)


async def test_real_legacy_endpoint_keeps_serving_model_until_worker_and_dispatches_after_commit(consumer):
    context, dispatch = consumer

    def queued(command):
        facts = fixtures.state(context)
        row = next(row for row in facts["knowledge"] if row["id"] == 40)
        assert row["model"] == "11" and row["model_transition"]["pending_model_id"] == "12"
        assert (command.knowledge_id, command.tenant_id, command.actor_user_id) == (40, 101, 7)
        assert command.expected_model_config_revision == row["model_config_revision"]
        assert command.expected_index_generation == row["index_generation"]
        assert not hasattr(command, "model_id")

    dispatch.side_effect = queued
    result = await update(context)
    assert result.status_code == 200
    dispatch.assert_called_once()
    row = next(row for row in fixtures.state(context)["knowledge"] if row["id"] == 40)
    assert row["name"] == "renamed" and row["description"] == "new description"


async def test_client_model_type_hint_does_not_override_actual_model_kind(consumer):
    context, dispatch = consumer
    before = fixtures.state(context)
    with pytest.raises(KnowledgeNoEmbeddingError):
        await update(context, model=33, hint="embedding")
    assert fixtures.state(context) == before
    dispatch.assert_not_called()


async def test_same_id_metadata_update_retains_invalid_old_model_and_does_not_rebuild(consumer):
    context, dispatch = consumer
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    before = fixtures.state(context)
    result = await update(context, model=11)
    assert result.status_code == 200
    after = fixtures.state(context)
    row = next(row for row in after["knowledge"] if row["id"] == 40)
    old = next(row for row in before["knowledge"] if row["id"] == 40)
    assert row["name"] == "renamed" and row["model"] == "11"
    assert (row["model_config_revision"], row["index_generation"], row["model_transition"]) == (
        old["model_config_revision"],
        old["index_generation"],
        old["model_transition"],
    )
    assert after["business_resource_reference"] == before["business_resource_reference"]
    assert after["business_reference_set"] == before["business_reference_set"]
    dispatch.assert_not_called()


async def test_queue_failure_keeps_committed_business_operation_without_replanning(consumer):
    context, dispatch = consumer
    dispatch.side_effect = RuntimeError("queue unavailable")
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await update(context)
    row = next(row for row in fixtures.state(context)["knowledge"] if row["id"] == 40)
    assert row["model"] == "11" and row["model_transition"]["pending_model_id"] == "12"
    assert row["model_config_revision"] == 1


@pytest.mark.parametrize("clear", [False, True])
async def test_real_legacy_delete_preserves_projection_then_cleanup_then_atomic_sql(consumer, clear):
    context, _ = consumer
    before = fixtures.state(context)
    order = []

    async def project(*args, **kwargs):
        order.append("projection")
        assert fixtures.state(context) == before

    def vectors(knowledge):
        assert order == ["projection"]
        order.append("vectors")

    KnowledgeService._project_library_deletion.side_effect = project
    KnowledgeService.delete_knowledge_file_in_vector.side_effect = vectors
    await asyncio.to_thread(KnowledgeService.delete_knowledge, None, context.user, 40, clear)
    assert order == ["projection", "vectors"]
    after = fixtures.state(context)
    assert [row["tenant_id"] for row in after["knowledgefile"]] == [202]
    assert [row["tenant_id"] for row in after["qaknowledge"]] == [202]
    if clear:
        assert after["business_reference_set"] == before["business_reference_set"]
        assert after["business_resource_reference"] == before["business_resource_reference"]
    else:
        assert not after["business_resource_reference"]
        assert all(row["id"] != 40 for row in after["knowledge"])


async def test_permission_projection_failure_cancels_all_sql_and_external_cleanup(consumer):
    context, _ = consumer
    before = fixtures.state(context)
    KnowledgeService._project_library_deletion.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await asyncio.to_thread(KnowledgeService.delete_knowledge, None, context.user, 40)
    assert fixtures.state(context) == before
    KnowledgeService.delete_knowledge_file_in_vector.assert_not_called()
    KnowledgeService.delete_knowledge_file_in_minio.assert_not_called()
