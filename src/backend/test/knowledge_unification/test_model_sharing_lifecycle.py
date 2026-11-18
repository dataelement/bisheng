"""Actual SQL plans, projection journals, intent, and receiving visibility."""

import pytest
import sqlalchemy as sa

from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.unified_policy import ModelVisibility
from bisheng.llm.application.model_sharing_status import ModelSharingStatusService
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.models.model_sharing_intent import ModelSharingInitialization, ModelSharingIntent
from bisheng.llm.domain.schemas import LLMModelCreateReq
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification.test_model_provider_sharing_writers import install_sharing

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


async def policies(factory):
    async with factory() as session:
        with bypass_tenant_filter():
            return {
                (row.tenant_id, row.model_id): row.everyone
                for row in (await session.execute(sa.select(ModelVisibility))).scalars()
            }


async def test_unknown_is_not_on_and_no_children_still_persists_explicit_intent(business, monkeypatch):
    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    status = ModelSharingStatusService(share)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        assert (await status.aget(identity=user, server_id=2))["enabled"] is None
        async with factory() as session:
            async with session.begin():
                await session.execute(sa.update(Tenant).where(Tenant.id.in_((101, 202))).values(status="disabled"))
        assert await share.aset_sharing(identity=user, server_id=2, enabled=True) == []
        state = await status.aget(identity=user, server_id=2)
        assert state["enabled"] is True and state["expected_child_ids"] == [] and state["version"] == 1
        assert await share.aset_sharing(identity=user, server_id=2, enabled=False) == []
        assert (await status.aget(identity=user, server_id=2))["enabled"] is False


async def test_new_receiver_initializes_only_new_delta_and_never_historical_missing_rules(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert await policies(factory) == {(202, 22): True}
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert await policies(factory) == {(202, 22): True}
        async with factory() as session:
            with bypass_tenant_filter():
                receipts = (await session.execute(sa.select(ModelSharingInitialization))).scalars().all()
                assert [row.child_ids for row in receipts] == [[202], []]


async def test_finalization_retry_preserves_admin_restriction_and_original_frozen_receipt(business, monkeypatch):
    from bisheng.dsh.domain.services import shared_model_visibility as receiver

    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    original = receiver.initialize_shared_model_visibility

    async def unavailable(*args, **kwargs):
        raise ConnectionError("receiver unavailable after projection")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", unavailable)
        with pytest.raises(ConnectionError):
            await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert len(client.rows) == 2
        async with factory() as session:
            async with session.begin():
                assert (await session.execute(sa.select(ModelSharingIntent))).scalars().all() == []
                session.add(
                    ModelVisibility(tenant_id=101, model_id=22, everyone=False, subjects=[], version=2, updated_by=7)
                )
        with pytest.raises(ConnectionError, match="receiver unavailable"):
            await share.aset_sharing(identity=user, server_id=2, enabled=False)
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", original)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert await policies(factory) == {(101, 22): False, (202, 22): True}
        assert (await ModelSharingStatusService(share).aget(identity=user, server_id=2))["enabled"] is True


async def test_child_join_after_freeze_is_queryable_gap_then_original_command_repairs(business, monkeypatch):
    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    original = share._permission
    injected = False

    async def permission(*args, **kwargs):
        app = await original(*args, **kwargs)
        execute = app.aexecute

        async def add_child(prepared):
            nonlocal injected
            await execute(prepared)
            if not injected:
                injected = True
                async with factory() as session:
                    async with session.begin():
                        await session.execute(
                            sa.update(Tenant).where(Tenant.id == 202).values(parent_tenant_id=1, status="active")
                        )

        app.aexecute = add_child
        return app

    async with factory() as session:
        async with session.begin():
            await session.execute(sa.update(Tenant).where(Tenant.id == 202).values(status="disabled"))
    monkeypatch.setattr(share, "_permission", permission)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert state["missing_child_ids"] == [202]
        assert await policies(factory) == {(101, 22): True}
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert (await ModelSharingStatusService(share).aget(identity=user, server_id=2))["missing_child_ids"] == []
        assert await policies(factory) == {(101, 22): True, (202, 22): True}


async def test_existing_receivers_get_new_dialogue_only_and_restriction_is_retained(business, monkeypatch):
    factory, deletion, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    sa.update(ModelVisibility)
                    .where(ModelVisibility.tenant_id == 101, ModelVisibility.model_id == 22)
                    .values(everyone=False)
                )
        async with factory() as session:
            async with session.begin():
                session.add(LLMModel(id=23, server_id=2, tenant_id=1, model_name="removed-speech", model_type="asr"))
        command = actual.request(retained=(22,), server_id=2)
        command.share_to_children = True
        command.models = [
            command.models[0],
            LLMModelCreateReq(name="new-chat", model_name="new-chat", model_type="llm"),
            LLMModelCreateReq(name="new-vector", model_name="new-vector", model_type="embedding"),
        ]
        result = await deletion.aupdate_server(identity=user, server=command)
        new_chat = next(row.id for row in result.models if row.model_name == "new-chat")
        new_vector = next(row.id for row in result.models if row.model_name == "new-vector")
        rows = await policies(factory)
        assert rows[(101, 22)] is False
        assert rows[(101, new_chat)] is True and rows[(202, new_chat)] is True
        assert (101, new_vector) not in rows and (202, new_vector) not in rows
        async with factory() as session:
            with bypass_tenant_filter():
                assert await session.get(LLMModel, new_chat) is not None


async def test_reenabled_tenant_consumes_only_explicit_on_and_retries_after_status_commit(business, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.tenant.domain.schemas.tenant_schema import TenantStatusUpdate
    from bisheng.tenant.domain.services import tenant_service

    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    monkeypatch.setattr(tenant_service, "get_redis_client", AsyncMock(return_value=AsyncMock()))
    async with factory() as session:
        async with session.begin():
            await session.execute(sa.update(Tenant).where(Tenant.id == 202).values(status="disabled"))
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert state["shared_child_ids"] == [101]
        await tenant_service.TenantService.aupdate_tenant_status(202, TenantStatusUpdate(status="active"), user)
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert state["shared_child_ids"] == [101, 202] and state["missing_child_ids"] == []
        assert await policies(factory) == {(101, 22): True, (202, 22): True}
        # A repeated status command is a supported recovery route, preserving
        # all old local restrictions and skipping already-shared missing rows.
        await tenant_service.TenantService.aupdate_tenant_status(202, TenantStatusUpdate(status="active"), user)
        assert await policies(factory) == {(101, 22): True, (202, 22): True}


async def test_additive_legacy_writer_consumes_on_under_provider_transaction(business, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.llm.domain.models import llm_server as model_module
    from bisheng.llm.domain.models.llm_server import LLMDao, LLMServer

    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    monkeypatch.setattr(model_module, "_check_is_global_super", AsyncMock(return_value=True))
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        async with factory() as session:
            provider = await session.get(LLMServer, 2)
            old = await session.get(LLMModel, 22)
        new = LLMModel(model_name="additive-chat", model_type="llm", tenant_id=1, user_id=7, server_id=2)
        await LLMDao.update_server_with_models(provider, [old, new], operator=user)
        rows = await policies(factory)
        assert rows[(101, new.id)] is True and rows[(202, new.id)] is True


async def test_original_reserved_without_receipt_resumes_without_historical_default_backfill(business, monkeypatch):
    from bisheng.dsh.domain.services import shared_model_visibility as receiver

    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    original = receiver.initialize_shared_model_visibility

    async def unavailable(*args, **kwargs):
        raise ConnectionError("interrupt finalization")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", unavailable)
        with pytest.raises(ConnectionError):
            await share.aset_sharing(identity=user, server_id=2, enabled=True)
        async with factory() as session:
            async with session.begin():
                await session.execute(sa.delete(ModelSharingInitialization))
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", original)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        assert await policies(factory) == {}
        assert (await ModelSharingStatusService(share).aget(identity=user, server_id=2))["enabled"] is True


async def test_new_model_refuses_stale_recipient_pin_when_child_share_completes_between_phases(business, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
    from bisheng.llm.application import model_sharing_lifecycle as lifecycle
    from bisheng.llm.domain.models import llm_server as model_module
    from bisheng.llm.domain.models.llm_server import LLMDao, LLMServer

    factory, _, _, _, _ = business
    share = await install_sharing(business, monkeypatch)
    monkeypatch.setattr(model_module, "_check_is_global_super", AsyncMock(return_value=True))
    async with factory() as session:
        async with session.begin():
            await session.execute(sa.update(Tenant).where(Tenant.id == 202).values(status="disabled"))
    original = lifecycle.prepare_added_provider_models
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        async with factory() as session:
            provider = await session.get(LLMServer, 2)
            old = await session.get(LLMModel, 22)

        async def interleaved(**kwargs):
            snapshot = await original(**kwargs)
            async with factory() as session:
                async with session.begin():
                    await session.execute(sa.update(Tenant).where(Tenant.id == 202).values(status="active"))
            await share.aset_sharing(identity=user, server_id=2, enabled=True, child_id=202)
            return snapshot

        monkeypatch.setattr(lifecycle, "prepare_added_provider_models", interleaved)
        new = LLMModel(model_name="racing-chat", model_type="llm", tenant_id=1, user_id=7, server_id=2)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await LLMDao.update_server_with_models(provider, [old, new], operator=user)
        async with factory() as session:
            assert (
                not (await session.execute(sa.select(LLMModel).where(LLMModel.model_name == "racing-chat")))
                .scalars()
                .all()
            )
        monkeypatch.setattr(lifecycle, "prepare_added_provider_models", original)
        new = LLMModel(model_name="racing-chat", model_type="llm", tenant_id=1, user_id=7, server_id=2)
        await LLMDao.update_server_with_models(provider, [old, new], operator=user)
        rows = await policies(factory)
        assert rows[(101, new.id)] is True and rows[(202, new.id)] is True
