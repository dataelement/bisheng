"""Actual SPACE creation/removal preserves one SQL/R2 transaction and tombstones.

覆盖 AC: AC-68, AC-71, AC-79, AC-87, AC-88, AC-89, AC-91, AC-92.
SQLite and original business methods are real; FGA/index/storage transports are
isolated. This does not exercise the pending full R3 deletion coordinator.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa

from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync, ChannelKnowledgeSyncDao
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.application.model_reference import KnowledgeModelReferenceApplication as App
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, QAKnowledge
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services import knowledge_space_service as module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.llm.domain.models.llm_server import LLMModel
from test.knowledge_unification import test_kn_model_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


@pytest.fixture
async def consumer(business, monkeypatch):
    for model in (SpaceChannelMember, KnowledgeFile, QAKnowledge, ChannelKnowledgeSync):
        model.__table__.create(business.sync)
    monkeypatch.setattr(module, "get_async_db_session", business.sessions)
    monkeypatch.setattr(KnowledgeService, "create_knowledge_base", Mock(side_effect=AssertionError("old library path")))
    for name in ("async_delete_knowledge", "aquery_by_id"):
        monkeypatch.setattr(module.KnowledgeDao, name, AsyncMock(side_effect=AssertionError("separate DAO Session")))
    monkeypatch.setattr(
        module.SpaceChannelMemberDao,
        "async_insert_member",
        AsyncMock(side_effect=AssertionError("separate creator commit")),
    )
    monkeypatch.setattr(
        module.LLMService,
        "get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id=11))),
    )
    monkeypatch.setattr(KnowledgeService, "_init_knowledge_indices_sync", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_vector", Mock())
    monkeypatch.setattr(KnowledgeService, "delete_knowledge_file_in_minio", Mock())
    for name in ("audit_create_knowledge_space", "audit_delete_knowledge_space"):
        monkeypatch.setattr(module.KnowledgeAuditTelemetryService, name, AsyncMock())
    monkeypatch.setattr(module.KnowledgeAuditTelemetryService, "telemetry_delete_knowledge", Mock())
    monkeypatch.setattr(module.KnowledgeSpaceTagLibraryDao, "adelete_private_for_knowledge", AsyncMock())
    monkeypatch.setattr(module.SpaceChannelMemberDao, "clean_space_member", AsyncMock())
    monkeypatch.setattr(module.SpaceChannelMemberDao, "async_get_members_by_space", AsyncMock(return_value=[]))
    adapter = SimpleNamespace(
        authorize_created=AsyncMock(),
        load_permission_record=AsyncMock(return_value=object()),
        project_delete=AsyncMock(),
    )
    service = KnowledgeSpaceService(request=None, login_user=business.user)
    service._resource_adapter = AsyncMock(return_value=adapter)
    service._permission_actor = AsyncMock(return_value=object())
    service._existing_creation = AsyncMock(return_value=None)
    service._assert_space_creation_quota = AsyncMock()
    service._is_auto_tag_feature_visible = AsyncMock(return_value=False)
    service._require_action = AsyncMock()
    service._list_space_child_resources = AsyncMock(return_value=[])
    service._load_resource_permission_records = AsyncMock(return_value=[])
    service._project_resource_deletes = AsyncMock()
    service._authorized_space_user_ids = AsyncMock(return_value=[])
    service._send_space_event_notification = AsyncMock()
    service._dispatch_knowledge_chat_rehome = Mock()
    return business, service, adapter


def state(context):
    result = fixtures.state(context)
    with context.sync.connect() as connection:
        for model in (SpaceChannelMember, KnowledgeFile, QAKnowledge, ChannelKnowledgeSync):
            result[model.__tablename__] = (
                connection.execute(sa.select(model.__table__).order_by(model.id)).mappings().all()
            )
    return result


async def seed(context):
    async with context.sessions() as session:
        row = Knowledge(
            id=40,
            tenant_id=101,
            user_id=7,
            name="space",
            type=3,
            model="11",
            index_name="index40",
            collection_name="index40",
        )
        await App.acreate(session, row, login_user=context.user, project_created=AsyncMock())
        session.add_all(
            [
                KnowledgeFile(id=501, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0),
                KnowledgeFile(id=502, tenant_id=202, knowledge_id=40, file_name="foreign"),
                QAKnowledge(id=501, tenant_id=101, knowledge_id=40, questions=["q"], answers="a"),
                ChannelKnowledgeSync(channel_id="channel", knowledge_space_id="40", folder_id="501", user_id=7),
            ]
        )
        await session.commit()


async def test_actual_space_creation_commits_space_creator_and_reference_before_indices(consumer):
    context, service, adapter = consumer
    context.user.tenant_id = 1  # home identity must not replace selected tenant101

    def index_after_commit(user_id, actual):
        facts = state(context)
        assert any(row["id"] == actual.id and row["tenant_id"] == 101 for row in facts["knowledge"])
        assert any(row["source_id"] == str(actual.id) for row in facts["business_resource_reference"])
        member = next(row for row in facts["space_channel_member"] if row["business_id"] == str(actual.id))
        assert member["business_type"] == BusinessTypeEnum.SPACE and member["user_id"] == 7
        assert member["user_role"] == UserRoleEnum.CREATOR and member["status"] == MembershipStatusEnum.ACTIVE
        assert user_id == 7

    KnowledgeService._init_knowledge_indices_sync.side_effect = index_after_commit
    result = await service.create_knowledge_space(name="new space")
    assert result.tenant_id == 101 and result.user_id == 7 and context.user.tenant_id == 1
    adapter.authorize_created.assert_awaited_once()
    record = adapter.authorize_created.call_args.kwargs["record"]
    assert record.resource_type == "knowledge_space" and record.resource_id == str(result.id)
    assert record.tenant_id == 101
    KnowledgeService._init_knowledge_indices_sync.assert_called_once()


@pytest.mark.parametrize("failure", ["projection", "membership", "bindings"])
async def test_space_create_failure_rolls_back_actual_resource_creator_and_bindings(consumer, monkeypatch, failure):
    context, service, adapter = consumer
    before = state(context)
    if failure == "projection":
        adapter.authorize_created.side_effect = RuntimeError("projection failed")
    elif failure == "membership":
        monkeypatch.setattr(
            KnowledgeModelReferenceRepository,
            "aadd_space_creator",
            AsyncMock(side_effect=RuntimeError("membership failed")),
            raising=False,
        )
    else:
        monkeypatch.setattr(
            context.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("bindings failed"))
        )
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await service.create_knowledge_space(name="cancelled")
    assert state(context) == before
    KnowledgeService._init_knowledge_indices_sync.assert_not_called()


@pytest.mark.parametrize("clear", [False, True])
async def test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids(consumer, clear):
    context, service, adapter = consumer
    await seed(context)
    before = state(context)
    order = []
    service._project_resource_deletes.side_effect = lambda records: order.append("children")
    adapter.project_delete.side_effect = lambda **kwargs: order.append("space")

    def cleanup(actual):
        assert order == (["children"] if clear else ["children", "space"])
        assert state(context) == before
        order.append("vectors")

    KnowledgeService.delete_knowledge_file_in_vector.side_effect = cleanup
    await (service.clear_space(40) if clear else service.delete_space(40))
    after = state(context)
    assert after["channel_knowledge_sync"] == before["channel_knowledge_sync"]
    assert [row["tenant_id"] for row in after["knowledgefile"]] == [202]
    assert not after["qaknowledge"]
    if clear:
        assert after["business_resource_reference"] == before["business_resource_reference"]
        assert after["business_reference_set"] == before["business_reference_set"]
        assert any(row["id"] == 40 and row["model"] == "11" for row in after["knowledge"])
    else:
        assert all(row["id"] != 40 for row in after["knowledge"])
        assert not after["business_resource_reference"]
        source = next(
            row
            for row in after["business_reference_set"]
            if row["source_id"] == "40" and row["record_kind"] == "source"
        )
        assert not source["effective"] and source["ready"]


async def test_space_projection_failure_keeps_business_refs_and_does_not_purge(consumer):
    context, service, adapter = consumer
    await seed(context)
    before = state(context)
    adapter.project_delete.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await service.delete_space(40)
    assert state(context) == before
    KnowledgeService.delete_knowledge_file_in_vector.assert_not_called()


async def test_clear_does_not_require_deleted_model_execution_or_release_model_binding(consumer):
    context, service, _ = consumer
    await seed(context)
    async with context.sessions() as session, session.begin():
        await session.execute(sa.delete(LLMModel).where(LLMModel.id == 11, LLMModel.tenant_id == 101))
    before = state(context)
    await service.clear_space(40)
    assert state(context)["business_resource_reference"] == before["business_resource_reference"]


@pytest.mark.parametrize("batch", [False, True])
async def test_folder_delete_does_not_silently_unbind_retained_channel_configuration(consumer, monkeypatch, batch):
    context, service, _ = consumer
    await seed(context)
    folder = KnowledgeFile(id=501, tenant_id=101, knowledge_id=40, file_name="folder", file_type=0)
    module.KnowledgeDao.aquery_by_id.side_effect = None
    module.KnowledgeDao.aquery_by_id.return_value = Knowledge(id=40, tenant_id=101, type=3)
    service._get_folder_for_action = AsyncMock(return_value=folder)
    service._ensure_space_async_task_tenant_consistency = Mock()
    service._delete_formal_resource = AsyncMock(return_value={"folder_ids": [501], "file_ids": [], "fga_resources": []})
    service.update_folder_update_time = AsyncMock()
    service._require_read_permission = AsyncMock()
    service._normalize_batch_delete_inputs = AsyncMock(return_value=([], [501]))
    monkeypatch.setattr(module.KnowledgeDao, "async_update_knowledge_update_time_by_id", AsyncMock())
    cleanup = AsyncMock(side_effect=AssertionError("retained config must not be deleted"))
    monkeypatch.setattr(ChannelKnowledgeSyncDao, "adelete_by_folder_ids", cleanup)
    before = state(context)["channel_knowledge_sync"]
    await (service.batch_delete(40, [], [501]) if batch else service.delete_folder(40, 501))
    cleanup.assert_not_called()
    assert state(context)["channel_knowledge_sync"] == before
