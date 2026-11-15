"""Actual R2 hard deletion must remain a supported formal M2/M4 input."""

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession
from test.knowledge_unification.permission_publication_native import complete as complete
from test.knowledge_unification.permission_publication_native import native as native
from test.knowledge_unification.permission_publication_native import published_input as published_factory
from test.knowledge_unification.permission_publication_native import raw_resource_native as raw_resource_native
from test.knowledge_unification.permission_publication_native import resource_native as resource_native
from test.knowledge_unification.permission_publication_native import transport as transport
from test.knowledge_unification.test_permission_publication_application import app

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import model_reference as model_app
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(
        socket.socket, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no network"))
    )


async def real_r2_create_delete(database):
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(LLMServer(id=88, tenant_id=101, name="own", type="openai"))
        session.add(
            LLMModel(
                id=88, tenant_id=101, server_id=88, model_name="own embedding", model_type="embedding", online=True
            )
        )
    verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7))
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(model_app, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
            mp.setattr(model_app, "require_business_action", AsyncMock())
            async with AsyncSession(database.engine) as session, session.begin():
                row = Knowledge(id=50, tenant_id=101, user_id=7, name="created then deleted", type=0, model="88")
                await model_app.KnowledgeModelReferenceApplication.acreate(
                    session, row, login_user=user, project_created=AsyncMock()
                )
            async with AsyncSession(database.engine) as session, session.begin():
                prepared = await model_app.KnowledgeModelReferenceApplication.aprepare_removal(
                    session, 50, login_user=user
                )
                await model_app.KnowledgeModelReferenceApplication.aapply_removal(session, prepared)
            async with AsyncSession(database.engine) as session, session.begin():
                assert await session.get(Knowledge, 50) is None
                rows = (
                    (
                        await session.execute(
                            sa.select(BusinessReferenceSet.__table__).where(BusinessReferenceSet.source_id == "50")
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(rows) == 2
                head = next(row for row in rows if row["record_kind"] == "source")
                assert head["ready"] and not head["effective"] and head["source_revision"] == 2
                assert not (
                    await session.execute(
                        sa.select(BusinessResourceReference.id).where(BusinessResourceReference.source_id == "50")
                    )
                ).all()
                print(
                    "ACTUAL_R2_AFTER_DELETE",
                    [(row["record_kind"], row["source_revision"], row["effective"], row["ready"]) for row in rows],
                )
    finally:
        reset_current_permission_actor(token)


async def freeze(complete, transport, monkeypatch, seed=None):
    request = SimpleNamespace(param={"reference_seed": seed}, node=SimpleNamespace(callspec=None))
    return await published_factory.__wrapped__(complete, transport, monkeypatch, request)


async def test_real_deleted_source_is_frozen_and_only_its_empty_index_is_retired(complete, transport, monkeypatch):
    value = await freeze(complete, transport, monkeypatch, real_r2_create_delete)
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    async with value.sessions() as session, session.begin():
        assert not (
            await session.execute(sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.source_id == "50"))
        ).all()
    assert await app(value).arun_references(**value.input, operator_id=7) == result


async def test_absent_residual_control_still_completes(complete, transport, monkeypatch):
    value = await freeze(complete, transport, monkeypatch)
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete


async def unreferenced_model_deletion(database, *, finalize=False):
    from bisheng.resource_reference.application.contracts import TargetKey
    from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

    verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    actor = PermissionActor(tenant_id=101, user_id=7)
    token = set_current_permission_actor(actor)
    try:
        async with AsyncSession(database.engine) as session, session.begin():
            session.add(LLMServer(id=88, tenant_id=101, name="own", type="openai"))
            session.add(LLMModel(id=88, tenant_id=101, server_id=88, model_name="unreferenced", model_type="embedding"))
        async with AsyncSession(database.engine) as session, session.begin():
            receipts = await verifier.averify_owner_targets(session, (TargetKey("model", "88"),))
            arguments = {
                "receipts": receipts,
                "operation_id": "real-unreferenced-model-delete",
                "operation_type": "model_delete_server",
                "actor": actor,
            }
            assert await runtime.aprepare_target_deletion(session, **arguments) == 1
            if finalize:
                await session.execute(sa.delete(LLMModel).where(LLMModel.id == 88))
                assert await runtime.afinalize_target_deletion(session, **arguments) == 1
            assert not (
                await session.execute(
                    sa.select(BusinessResourceReference.id).where(
                        BusinessResourceReference.target_type == "model", BusinessResourceReference.target_id == "88"
                    )
                )
            ).all()
            assert (await session.execute(sa.select(ResourceReferenceTombstone.stage))).scalar_one() == (
                "deleted" if finalize else "deleting"
            )
    finally:
        reset_current_permission_actor(token)


async def test_actual_unreferenced_model_deleting_blocks_formal_m2(complete, transport, monkeypatch):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await freeze(complete, transport, monkeypatch, unreferenced_model_deletion)


async def test_actual_unreferenced_model_deleted_does_not_block_m4(complete, transport, monkeypatch):
    async def deleted(database):
        await unreferenced_model_deletion(database, finalize=True)

    value = await freeze(complete, transport, monkeypatch, deleted)
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete


async def unknown_active(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(
            sa.update(BusinessReferenceSet.__table__)
            .where(BusinessReferenceSet.source_id == "50", BusinessReferenceSet.record_kind == "source")
            .values(effective=True)
        )


async def half_bundle(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session, session.begin():
        await session.execute(
            sa.delete(BusinessReferenceSet.__table__).where(
                BusinessReferenceSet.source_id == "50", BusinessReferenceSet.record_kind == "source"
            )
        )


async def hidden_binding(database):
    await real_r2_create_delete(database)
    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="knowledge",
                source_id="50",
                source_version="current",
                slot_key="model",
                target_type="model",
                target_id="88",
                target_tenant_id=101,
                source_revision=2,
            )
        )


@pytest.mark.parametrize("seed", [unknown_active, half_bundle, hidden_binding])
async def test_unknown_active_half_or_nonempty_residuals_block_before_freeze(complete, transport, monkeypatch, seed):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await freeze(complete, transport, monkeypatch, seed)


async def real_channel_create_delete(database):
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from test.knowledge_unification.test_ch_bindings import config

    from bisheng.channel.domain.models import channel_knowledge_sync as sync_module
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
    from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
    from bisheng.channel.domain.services import channel_service as channel_module
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.common.models import space_channel_member as member_module
    from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
        SpaceChannelMemberRepositoryImpl,
    )
    from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(database.engine, expire_on_commit=False) as session:
            yield session

    verifier = ReferenceTargetVerifier(
        {"knowledge_space": KnowledgeReferenceTargetOwner(), "knowledge_file": KnowledgeReferenceTargetOwner()}
    )
    runtime = ReferenceBindingRuntime(ReferenceRepository(verifier=verifier), verifier)
    adapter = SimpleNamespace(
        authorize_created=AsyncMock(),
        load_permission_record=AsyncMock(return_value=object()),
        project_delete=AsyncMock(),
        cleanup_deleted=AsyncMock(),
    )
    with pytest.MonkeyPatch.context() as mp:
        for module in (channel_module, sync_module, member_module):
            mp.setattr(module, "get_async_db_session", sessions)
        mp.setattr(channel_module, "get_reference_binding_runtime", AsyncMock(return_value=runtime))
        mp.setattr(channel_module, "get_f048_resource_adapter", AsyncMock(return_value=adapter))
        mp.setattr(channel_module, "require_business_action", AsyncMock())
        mp.setattr(
            channel_module,
            "resolve_permission_actor",
            AsyncMock(return_value=PermissionActor(tenant_id=101, user_id=7)),
        )
        # This test owns source lifecycle/M2/M4. Keep the current public quota
        # boundary isolated too; the former get_effective_quota hook is no
        # longer the creation admission and leaked into the live DB factory.
        mp.setattr(channel_module.QuotaService, "check_quota", AsyncMock())
        mp.setattr(channel_module.QuotaService, "check_info_source_subscribe_limit", AsyncMock())
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
            user = UserPayload(user_id=7, tenant_id=101, user_role=[])
            root = await service.create_channel(
                CreateChannelRequest(name="real deleted channel", visibility="public", knowledge_sync=config()), user
            )
            assert await service.dismiss_channel(root.id, user)


async def test_real_deleted_channel_is_supported_through_formal_m2_and_m4(complete, transport, monkeypatch):
    value = await freeze(complete, transport, monkeypatch, real_channel_create_delete)
    result = await app(value).arun_references(**value.input, operator_id=7)
    assert result.complete
    async with value.sessions() as session, session.begin():
        assert not (
            await session.execute(
                sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.source_type == "channel_sync")
            )
        ).all()


async def insert_prepared(database):
    from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob

    async with AsyncSession(database.engine) as session, session.begin():
        session.add(
            KnowledgeSpaceDeleteJob(
                tenant_id=101,
                space_id=9000,
                applicant_user_id=7,
                operation_type="knowledge_space_delete",
                business_phase="prepared",
                manifest={},
            )
        )


async def test_fresh_and_existing_freeze_both_check_actual_prepared_tasks(complete, transport, monkeypatch):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await freeze(complete, transport, monkeypatch, insert_prepared)


async def test_existing_frozen_entry_cannot_borrow_an_old_task_free_snapshot(complete, transport, monkeypatch):
    value = await freeze(complete, transport, monkeypatch)
    await insert_prepared(complete)
    from test.knowledge_unification import test_migration_inventory_application as m2

    from bisheng.knowledge.application import unification_inventory

    current = m2.application(unification_inventory, transport)
    async with value.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await current.arun(session, **value.input)
        assert caught.value.kwargs["reason"] == "migration_tasks_business_delete_not_finalized"


async def test_m3_rechecks_after_artifact_io_before_first_owned_write(complete, transport, monkeypatch):
    value = await freeze(complete, transport, monkeypatch)
    application = app(value)
    original = application._plan

    async def changed(*args, **kwargs):
        result = await original(*args, **kwargs)
        await insert_prepared(complete)
        return result

    monkeypatch.setattr(application, "_plan", changed)
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await application.arun(**value.input)
    assert caught.value.kwargs["reason"] == "migration_tasks_business_delete_not_finalized"
    async with value.sessions() as session, session.begin():
        assert (await session.get(Knowledge, 9000)).type == 0


async def test_epoch_signing_checks_tasks_before_allocating_any_epoch(complete, transport, monkeypatch):
    from bisheng.knowledge.application.unification_coverage import certify_migration
    from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun

    value = await freeze(complete, transport, monkeypatch)
    await insert_prepared(complete)
    async with value.sessions() as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await certify_migration(session, frozen=value.frozen, proofs={})
        assert caught.value.kwargs["reason"] == "migration_tasks_business_delete_not_finalized"
        assert not (
            await session.execute(
                sa.select(KnowledgeUnificationRun.id).where(KnowledgeUnificationRun.coverage_epoch.is_not(None))
            )
        ).all()


async def test_empty_index_clear_and_retired_checkpoint_recover_after_actual_commit_ack_loss(
    complete, transport, monkeypatch
):
    from sqlalchemy.orm import Session

    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = await freeze(complete, transport, monkeypatch, real_r2_create_delete)
    clear = ReferenceBackfillRepository.aclear_registered_retired

    async def tagged(self, session, **kwargs):
        await clear(self, session, **kwargs)
        session.info["native_retire_ack"] = True

    monkeypatch.setattr(ReferenceBackfillRepository, "aclear_registered_retired", tagged)
    failed = False

    def lost_ack(session):
        nonlocal failed
        if session.info.get("native_retire_ack") and not failed:
            failed = True
            raise OSError("native committed retire ACK lost")

    sa.event.listen(Session, "after_commit", lost_ack)
    try:
        with pytest.raises(OSError):
            await app(value).arun_references(**value.input, operator_id=7)
    finally:
        sa.event.remove(Session, "after_commit", lost_ack)
    async with value.sessions() as session, session.begin():
        assert not (
            await session.execute(sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.source_id == "50"))
        ).all()
    monkeypatch.setattr(
        ReferenceBackfillRepository,
        "aclear_registered_retired",
        AsyncMock(side_effect=AssertionError("committed empty clear must not replay")),
    )
    assert (await app(value).arun_references(**value.input, operator_id=7)).complete


async def test_late_reference_cannot_be_silently_deleted_with_a_frozen_empty_set(complete, transport, monkeypatch):
    from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

    value = await freeze(complete, transport, monkeypatch, real_r2_create_delete)
    clear = ReferenceBackfillRepository.aclear_registered_retired

    async def changed(self, session, **kwargs):
        await session.execute(
            sa.insert(BusinessResourceReference.__table__).values(
                tenant_id=101,
                source_type="knowledge",
                source_id="50",
                source_version="current",
                slot_key="unexpected",
                target_type="model",
                target_id="88",
                target_tenant_id=101,
                source_revision=2,
            )
        )
        return await clear(self, session, **kwargs)

    monkeypatch.setattr(ReferenceBackfillRepository, "aclear_registered_retired", changed)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await app(value).arun_references(**value.input, operator_id=7)
    async with value.sessions() as session, session.begin():
        assert (
            len(
                (
                    await session.execute(
                        sa.select(BusinessReferenceSet.id).where(BusinessReferenceSet.source_id == "50")
                    )
                ).all()
            )
            == 2
        )
