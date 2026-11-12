"""Full Channel/current admission uses real SourceOwner/Core/Knowledge Owners.

覆盖 AC: AC-35, AC-71, AC-87, AC-89, AC-91, AC-92. Real SQL source indexes,
targets, identity membership and roles; only permission transport is stubbed.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.channel.application import execution_admission as admission_module
from bisheng.channel.application import reference_source_owner as owner_module
from bisheng.channel.application.automation_identity import resolve_channel_automation_identity
from bisheng.channel.application.execution_admission import ChannelSyncExecutionAdmission
from bisheng.channel.application.reference_source_owner import ChannelReferenceSourceOwner
from bisheng.channel.domain.models.channel_knowledge_sync import ChannelKnowledgeSync
from bisheng.channel.domain.schemas.channel_manager_schema import UpdateChannelRequest
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository
from test.knowledge_unification import test_ch_automation_identity as person_fixtures
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
people = person_fixtures.people


@pytest.fixture
async def admitted(business, people, monkeypatch):
    root = await fixtures.create(business, sync=fixtures.config(10, folder="30"))
    verifier = SourceReadVerifier({"channel_sync": ChannelReferenceSourceOwner()}, AuthenticatedSourceReadIdentity())
    targets = KnowledgeSourceReadTargetOwner(verifier)
    runtime = ReferenceSourceReadRuntime(
        verifier, SourceReadRepository(verifier), {"knowledge_space": targets, "knowledge_file": targets}
    )
    monkeypatch.setattr(admission_module, "get_reference_read_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(admission_module, "get_async_db_session", business.sessions)
    monkeypatch.setattr(owner_module, "require_business_action", AsyncMock())
    monkeypatch.setattr(admission_module, "require_business_action", AsyncMock())
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7))
    async with business.sessions() as session:
        row = (
            await session.exec(sa.select(ChannelKnowledgeSync.id).where(ChannelKnowledgeSync.channel_id == root.id))
        ).scalar_one()
        identity = await resolve_channel_automation_identity(session, root.id, row, tenant_id=101)
    try:
        yield SimpleNamespace(
            context=business,
            root=root,
            config_id=row,
            identity=identity,
            detected_at=int(datetime.now().timestamp()) + 60,
            runtime=runtime,
        )
    finally:
        reset_current_permission_actor(token)


async def test_real_full_runtime_preserves_identity_and_borrows_the_active_transaction(admitted):
    value = admitted
    async with value.context.sessions() as session, session.begin():
        transaction = session.get_transaction()
        prepared = await ChannelSyncExecutionAdmission.prepare(
            value.identity, value.root.id, value.config_id, value.detected_at, session=session
        )
        assert prepared.identity is value.identity
        assert prepared.config["knowledge_space_id"] == "10" and prepared.config["folder_id"] == "30"
        assert {ref.target.target_id for ref in prepared.read.snapshot.references} == {"10", "30"}
        assert session.get_transaction() is transaction and session.in_transaction()
        changed = prepared.config
        changed["knowledge_space_id"] = "999"
        assert prepared.config["knowledge_space_id"] == "10"
        admission_module.require_business_action.assert_awaited_once_with(
            value.identity, resource_type="folder", resource_id=30, action="upload_file"
        )


async def test_legacy_folder_requires_rebind_without_blocking_other_saved_options(admitted):
    value = admitted
    await value.context.service.update_channel(
        value.root.id, UpdateChannelRequest(knowledge_sync=fixtures.config(10, 20)), value.context.user
    )
    async with value.context.sessions() as session, session.begin():
        rows = (
            await session.execute(
                sa.select(ChannelKnowledgeSync.id, ChannelKnowledgeSync.knowledge_space_id).where(
                    ChannelKnowledgeSync.channel_id == value.root.id
                )
            )
        ).all()
        ids = {row.knowledge_space_id: row.id for row in rows}
        await session.execute(
            sa.update(ChannelKnowledgeSync)
            .where(ChannelKnowledgeSync.id == ids["10"])
            .values(folder_id="new-folder-1730000000000")
        )
        identities = {
            space: await resolve_channel_automation_identity(session, value.root.id, config_id, tenant_id=101)
            for space, config_id in ids.items()
        }
    with pytest.raises(ResourceReferenceInvalidError) as error:
        await ChannelSyncExecutionAdmission.prepare(identities["10"], value.root.id, ids["10"], value.detected_at)
    assert error.value.kwargs["reason"] == "channel_legacy_folder_rebind_required"
    prepared = await ChannelSyncExecutionAdmission.prepare(
        identities["20"], value.root.id, ids["20"], value.detected_at
    )
    assert prepared.config["knowledge_space_id"] == "20" and prepared.config["folder_id"] is None


async def test_one_invalid_option_blocks_the_whole_channel_even_for_another_selected_config(admitted):
    value = admitted
    await value.context.service.update_channel(
        value.root.id, fixtures.UpdateChannelRequest(knowledge_sync=fixtures.config(10, 20)), value.identity
    )
    async with value.context.sessions() as session:
        rows = (
            (
                await session.exec(
                    sa.select(ChannelKnowledgeSync).where(ChannelKnowledgeSync.channel_id == value.root.id)
                )
            )
            .scalars()
            .all()
        )
        config_id = next(row.id for row in rows if row.knowledge_space_id == "20")
        identity = await resolve_channel_automation_identity(session, value.root.id, config_id, tenant_id=101)
    await fixtures.deleted_space(value.context)
    with pytest.raises(ResourceReferenceInvalidError):
        await ChannelSyncExecutionAdmission.prepare(identity, value.root.id, config_id, value.detected_at)


@pytest.mark.parametrize("change", ["disabled", "future", "missing", "wrong_user"])
async def test_real_selected_configuration_is_required_without_old_uuid_or_disabled_fallback(admitted, change):
    value = admitted
    config_id = value.config_id
    async with value.context.sessions() as session, session.begin():
        values = (
            {"is_enabled": False}
            if change == "disabled"
            else {"update_time": datetime(2099, 1, 1)}
            if change == "future"
            else {"user_id": 99}
        )
        if change != "missing":
            await session.execute(
                sa.update(ChannelKnowledgeSync).where(ChannelKnowledgeSync.id == config_id).values(**values)
            )
        else:
            config_id = "old-uuid"
    with pytest.raises((ResourceReferenceInvalidError, PermissionDeniedError)):
        await ChannelSyncExecutionAdmission.prepare(value.identity, value.root.id, config_id, value.detected_at)


async def test_missing_index_is_not_repaired_during_delivery(admitted):
    value = admitted
    async with value.context.sessions() as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet).where(
                BusinessReferenceSet.source_id == value.root.id, BusinessReferenceSet.tenant_id == 101
            )
        )
    with pytest.raises(ReferenceCoverageNotReadyError):
        await ChannelSyncExecutionAdmission.prepare(value.identity, value.root.id, value.config_id, value.detected_at)


@pytest.mark.parametrize("values", [{"knowledge_id": 20}, {"file_type": 1}])
async def test_folder_current_kind_and_parent_are_checked_before_delivery_side_effects(admitted, values):
    value = admitted
    async with value.context.sessions() as session, session.begin():
        await session.execute(
            sa.update(KnowledgeFile).where(KnowledgeFile.id == 30, KnowledgeFile.tenant_id == 101).values(**values)
        )
    with pytest.raises((ResourceReferenceInvalidError, SpacePermissionDeniedError)):
        await ChannelSyncExecutionAdmission.prepare(value.identity, value.root.id, value.config_id, value.detected_at)


async def test_borrowed_session_is_not_reopened_or_committed(admitted, monkeypatch):
    value = admitted

    @asynccontextmanager
    async def forbidden():
        raise AssertionError("borrowed admission opened another source transaction")
        yield

    monkeypatch.setattr(admission_module, "get_async_db_session", forbidden)
    async with value.context.sessions() as session:
        with pytest.raises(ResourceReferenceInvalidError):
            await ChannelSyncExecutionAdmission.prepare(
                value.identity, value.root.id, value.config_id, value.detected_at, session=session
            )
    async with value.context.sessions() as session, session.begin():
        assert (
            await ChannelSyncExecutionAdmission.prepare(
                value.identity, value.root.id, value.config_id, value.detected_at, session=session
            )
        ).identity is value.identity
