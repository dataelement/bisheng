"""Real Channel/Knowledge/R2 CRUD is one SQL unit.

覆盖 AC: AC-71, AC-87, AC-88, AC-89, AC-91, AC-92. Permission transports,
quota and optional notifications are test boundaries; business/target/index SQL
and the registered target verifier are real. No external services are used.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession
from test.knowledge_unification import test_ch_repository as fixtures

from bisheng.channel.domain.models import channel_knowledge_sync as sync_module
from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest, UpdateChannelRequest
from bisheng.channel.domain.services import channel_service as service_module
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ChannelCreationRequestConflictError, ChannelNotFoundError
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.common.models import space_channel_member as member_module
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
    SpaceChannelMemberRepositoryImpl,
)
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
async def business(store, monkeypatch):
    async with store.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.create(conn))
        await connection.run_sync(lambda conn: KnowledgeFile.__table__.create(conn))
        for model in (
            KnowledgeSpaceDeleteJob,
            BusinessReferenceSet,
            BusinessResourceReference,
            ResourceReferenceTombstone,
        ):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn))

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(store, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        for ident in (10, 20):
            session.add(Knowledge(id=ident, tenant_id=101, user_id=7, name=f"space-{ident}", type=3))
            session.add(
                SpaceChannelMember(business_id=str(ident), business_type="space", user_id=7, user_role="creator")
            )
        session.add(KnowledgeFile(id=30, tenant_id=101, knowledge_id=10, file_name="folder", file_type=0))

    owner = KnowledgeReferenceTargetOwner()
    verifier = ReferenceTargetVerifier({"knowledge_space": owner, "knowledge_file": owner})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    adapter = SimpleNamespace(
        authorize_created=AsyncMock(),
        load_permission_record=AsyncMock(return_value=object()),
        project_delete=AsyncMock(),
        cleanup_deleted=AsyncMock(),
        remove_ordinary_sources=AsyncMock(),
    )
    monkeypatch.setattr(service_module, "get_async_db_session", sessions, raising=False)
    monkeypatch.setattr(sync_module, "get_async_db_session", sessions)
    monkeypatch.setattr(member_module, "get_async_db_session", sessions)
    monkeypatch.setattr(service_module, "get_reference_binding_runtime", AsyncMock(return_value=runtime), raising=False)
    monkeypatch.setattr(service_module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
    monkeypatch.setattr(service_module, "require_business_action", AsyncMock())
    # F009 policy loading is upstream of these native reference transactions.
    monkeypatch.setattr(ChannelService, "_assert_channel_creation_quota", AsyncMock())
    monkeypatch.setattr(
        service_module, "resolve_permission_actor", AsyncMock(return_value=PermissionActor(tenant_id=101, user_id=7))
    )
    monkeypatch.setattr(service_module.QuotaService, "get_effective_quota", AsyncMock(return_value=-1))
    monkeypatch.setattr(service_module.QuotaService, "check_info_source_subscribe_limit", AsyncMock())
    async with sessions() as legacy:
        service = ChannelService(
            ChannelRepositoryImpl(legacy),
            SpaceChannelMemberRepositoryImpl(legacy),
            AsyncMock(),
            article_es_service=MagicMock(),
        )
        service._best_effort_sync_channel_info_source_metadata = AsyncMock()
        service._send_channel_event_notification = AsyncMock()
        service.update_channels_latest_article_time = AsyncMock()
        context = SimpleNamespace(
            engine=store,
            sessions=sessions,
            service=service,
            runtime=runtime,
            adapter=adapter,
            user=UserPayload(user_id=7, tenant_id=101, user_role=[]),
        )
        yield context


def config(*spaces, enabled=True, folder=None, sub=None):
    selected = [{"knowledge_space_id": str(value), "folder_id": folder} for value in spaces]
    return {
        "main": {"enabled": enabled, "spaces": selected if sub is None else []},
        "subs": [] if sub is None else [{"sub_channel_name": sub, "enabled": enabled, "spaces": selected}],
    }


async def create(context, *, sync=None, key=None, name="created"):
    return await context.service.create_channel(
        CreateChannelRequest(
            name=name, visibility="public", knowledge_sync=config(10) if sync is None else sync, creation_request_id=key
        ),
        context.user,
    )


async def state(context):
    async with context.engine.connect() as conn:
        result = {}
        for model in (
            Channel,
            ChannelKnowledgeSync,
            SpaceChannelMember,
            BusinessReferenceSet,
            BusinessResourceReference,
        ):
            result[model.__tablename__] = (
                (await conn.execute(sa.select(model.__table__).order_by(model.__table__.c.id))).mappings().all()
            )
        return result


async def source_rows(context, channel_id):
    value = await state(context)
    return [row for row in value["business_resource_reference"] if row["source_id"] == channel_id]


async def test_create_contains_root_creator_complete_source_and_targets(business):
    root = await create(business, sync=config(10, folder="30"))
    value = await state(business)
    assert {(row["slot_key"], row["target_id"]) for row in await source_rows(business, root.id)} == {
        ("main.space", "10"),
        ("main.folder", "30"),
    }
    assert len([row for row in value["space_channel_member"] if row["business_id"] == root.id]) == 1
    assert len([row for row in value["business_reference_set"] if row["source_id"] == root.id]) == 2


async def test_binding_failure_leaves_no_channel_creator_or_configuration(business, monkeypatch):
    before = await state(business)
    monkeypatch.setattr(
        business.runtime, "aapply_source_bindings", AsyncMock(side_effect=RuntimeError("binding failed"))
    )
    with pytest.raises(RuntimeError, match="binding failed"):
        await create(business)
    assert await state(business) == before


async def test_zero_source_is_indexed_and_missing_existing_index_is_not_bootstrapped(business):
    root = await create(business, sync=config())
    value = await state(business)
    assert any(
        row["source_id"] == root.id and row["source_version"] == "current" and row["ready"]
        for row in value["business_reference_set"]
    )
    with pytest.raises(ReferenceCoverageNotReadyError):
        await business.service.update_channel("own", UpdateChannelRequest(name="cannot bootstrap"), business.user)


async def test_existing_legacy_placeholder_can_be_manually_rebound_without_accepting_new_ones(business):
    root = await create(business, sync=config(10))
    async with business.sessions() as session, session.begin():
        await session.execute(
            sa.update(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.channel_id == root.id)
            .values(folder_id="new-folder-1730000000000")
        )
    before = await state(business)
    with pytest.raises(ResourceReferenceInvalidError):
        await business.service.update_channel(
            root.id, UpdateChannelRequest(knowledge_sync=config(10, folder="new-folder-1730000000000")), business.user
        )
    assert await state(business) == before
    with pytest.raises(ResourceReferenceInvalidError):
        await create(business, sync=config(10, folder="new-folder-1730000000001"))
    assert await state(business) == before
    await business.service.update_channel(
        root.id, UpdateChannelRequest(knowledge_sync=config(10, folder="30")), business.user
    )
    changed = [row for row in (await state(business))["channel_knowledge_sync"] if row["channel_id"] == root.id]
    assert len(changed) == 1 and changed[0]["folder_id"] == "30"
    assert {row.target_id for row in await source_rows(business, root.id)} == {"10", "30"}


async def test_pause_retains_targets_and_replacement_uuids_do_not_duplicate_refs(business):
    root = await create(business)
    original = (await state(business))["channel_knowledge_sync"]
    await business.service.update_channel(
        root.id, UpdateChannelRequest(knowledge_sync=config(10, enabled=False)), business.user
    )
    assert len(await source_rows(business, root.id)) == 1
    changed = [row for row in (await state(business))["channel_knowledge_sync"] if row["channel_id"] == root.id]
    assert not changed[0]["is_enabled"] and changed[0]["id"] not in {row["id"] for row in original}
    await business.service.update_channel(
        root.id, UpdateChannelRequest(knowledge_sync=config(10, enabled=False)), business.user
    )
    assert len(await source_rows(business, root.id)) == 1


async def test_explicit_remove_releases_but_filter_rule_change_keeps_selection(business):
    root = await create(business, sync=config(10, sub="old"))
    await business.service.update_channel(root.id, UpdateChannelRequest(filter_rules=[]), business.user)
    assert len(await source_rows(business, root.id)) == 1
    await business.service.update_channel(root.id, UpdateChannelRequest(knowledge_sync=config()), business.user)
    assert await source_rows(business, root.id) == []


async def deleted_space(context):
    async with context.sessions() as session, session.begin():
        await session.delete(await session.get(Knowledge, 10))
        session.add(
            ResourceReferenceTombstone(
                tenant_id=101,
                target_type="knowledge_space",
                target_id="10",
                target_tenant_id=101,
                operation_id="force-space10",
                operation_type="force_delete",
                stage="deleted",
                actor_type="user",
                actor_id="7",
            )
        )


async def test_old_invalid_retains_and_partial_repair_new_slot_cannot_borrow_it(business):
    root = await create(business)
    await deleted_space(business)
    await business.service.update_channel(root.id, UpdateChannelRequest(knowledge_sync=config(10, 20)), business.user)
    assert {row["target_id"] for row in await source_rows(business, root.id)} == {"10", "20"}
    before = await state(business)
    with pytest.raises(ResourceReferenceInvalidError):
        await business.service.update_channel(
            root.id, UpdateChannelRequest(knowledge_sync=config(10, sub="new")), business.user
        )
    assert await state(business) == before
    await business.service.update_channel(root.id, UpdateChannelRequest(knowledge_sync=config(20)), business.user)
    assert {row["target_id"] for row in await source_rows(business, root.id)} == {"20"}


async def test_configuration_drift_is_not_saved_as_a_repair(business):
    root = await create(business)
    async with business.sessions() as session, session.begin():
        await session.execute(
            sa.update(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.channel_id == root.id)
            .values(knowledge_space_id="20")
        )
    before = await state(business)
    with pytest.raises(ReferenceCoverageNotReadyError):
        await business.service.update_channel(root.id, UpdateChannelRequest(knowledge_sync=config(10)), business.user)
    assert await state(business) == before


async def test_dismiss_projection_failure_preserves_every_sql_row_then_success_removes_refs(business):
    root = await create(business)
    before = await state(business)
    business.adapter.project_delete.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await business.service.dismiss_channel(root.id, business.user)
    assert await state(business) == before
    business.adapter.project_delete.side_effect = None
    assert await business.service.dismiss_channel(root.id, business.user)
    value = await state(business)
    assert not any(row["id"] == root.id for row in value["channel"])
    assert not any(row["channel_id"] == root.id for row in value["channel_knowledge_sync"])
    assert not any(row["business_id"] == root.id for row in value["space_channel_member"])
    assert await source_rows(business, root.id) == []


async def test_create_request_retry_preserves_root_and_conflict_still_rejects(business):
    first = await create(business, key="request-1")
    again = await create(business, key="request-1")
    assert again.id == first.id and len(await source_rows(business, first.id)) == 1
    with pytest.raises(ChannelCreationRequestConflictError):
        await create(business, key="request-1", name="different")


async def test_creation_permission_failure_rolls_back_and_cross_tenant_update_rejects(business):
    before = await state(business)
    business.adapter.authorize_created.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await create(business)
    assert await state(business) == before
    with pytest.raises(ChannelNotFoundError):
        await business.service.update_channel("foreign", UpdateChannelRequest(knowledge_sync=config(10)), business.user)
