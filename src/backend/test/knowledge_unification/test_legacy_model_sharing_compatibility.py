"""Upgrade sharing keeps its old switch meaning without bypassing real grants."""

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.dsh.domain.models.unified_policy import ModelVisibility
from bisheng.llm.application.model_mount_sharing import ModelMountSharingApplication
from bisheng.llm.application.model_sharing_status import ModelSharingStatusService
from bisheng.llm.domain.models.model_sharing_intent import ModelSharingIntent
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification.test_model_provider_sharing_writers import install_sharing
from test.knowledge_unification.test_model_sharing_lifecycle import policies

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


async def test_legacy_on_is_visible_to_coverage_and_mount_without_get_backfill(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        status = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert status["enabled"] is True and status["stored_enabled"] is None
        assert status["expected_child_ids"] == [101, 202] and status["missing_child_ids"] == [202]
        assert await ModelMountSharingApplication(share).aenabled_server_ids(identity=user) == (2,)
        async with factory() as session:
            with bypass_tenant_filter():
                assert not (await session.execute(sa.select(ModelSharingIntent))).scalars().all()


async def test_legacy_mount_promotes_intent_and_initializes_only_new_child(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await ModelMountSharingApplication(share).areconcile_child(identity=user, child_id=202)
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert state["stored_enabled"] is True and state["version"] == 1
        assert state["shared_child_ids"] == [101, 202]
        assert await policies(factory) == {(202, 22): True}


async def test_never_shared_and_explicit_off_with_stale_grant_are_not_on(business, monkeypatch):
    _, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    mount = ModelMountSharingApplication(share)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        assert await mount.aenabled_server_ids(identity=user) == ()
        await share.aset_sharing(identity=user, server_id=2, enabled=False)
        client.rows = {("tenant:101", "shared_with", "llm_server:2")}
        assert await mount.aenabled_server_ids(identity=user) == ()
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await share.aset_sharing(identity=user, server_id=2, enabled=True, child_id=202)
        assert client.rows == {("tenant:101", "shared_with", "llm_server:2")}


async def test_explicit_repair_initializes_absent_history_but_keeps_restrictions(business, monkeypatch):
    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    async with factory() as session:
        async with session.begin():
            session.add(
                ModelVisibility(tenant_id=101, model_id=22, everyone=False, subjects=[], version=2, updated_by=7)
            )
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.arepair_enabled_sharing(
            identity=user,
            server_id=2,
            expected_enabled=None,
            expected_version=0,
            expected_plan_id=None,
        )
        assert await policies(factory) == {(101, 22): False, (202, 22): True}
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        writes = len(client.writes)
        await share.arepair_enabled_sharing(
            identity=user,
            server_id=2,
            expected_enabled=True,
            expected_version=state["version"],
            expected_plan_id=state["plan_id"],
        )
        assert len(client.writes) == writes
        assert await policies(factory) == {(101, 22): False, (202, 22): True}


async def test_preview_before_completed_off_cannot_reenable(business, monkeypatch):
    _, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        await share.aset_sharing(identity=user, server_id=2, enabled=True)
        before = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        await share.aset_sharing(identity=user, server_id=2, enabled=False)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await share.arepair_enabled_sharing(
                identity=user,
                server_id=2,
                expected_enabled=True,
                expected_version=before["version"],
                expected_plan_id=before["plan_id"],
            )
        assert not client.rows


async def test_legacy_additive_writer_adopts_exact_recipients_before_new_policy(business, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.llm.domain.models import llm_server as model_module
    from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer

    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    monkeypatch.setattr(model_module, "_check_is_global_super", AsyncMock(return_value=True))
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        async with factory() as session:
            provider = await session.get(LLMServer, 2)
            old = await session.get(LLMModel, 22)
        new = LLMModel(model_name="legacy-new", model_type="llm", tenant_id=1, user_id=7, server_id=2)
        await LLMDao.update_server_with_models(provider, [old, new], operator=user)
        assert client.rows == {("tenant:101", "shared_with", "llm_server:2")}
        rows = await policies(factory)
        assert rows[(101, new.id)] is True and (202, new.id) not in rows
        assert (101, 22) not in rows
        state = await ModelSharingStatusService(share).aget(identity=user, server_id=2)
        assert state["stored_enabled"] is True and state["plan_id"]


async def test_legacy_snapshot_before_off_cannot_authorize_mount(business, monkeypatch):
    _, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    original = share._permission
    raced = False

    async def permission(*args, **kwargs):
        native = await original(*args, **kwargs)
        read = native.aread

        async def snapshot(**params):
            nonlocal raced
            result = await read(**params)
            if not raced:
                raced = True
                await share.aset_sharing(identity=user, server_id=2, enabled=False)
            return result

        native.aread = snapshot
        return native

    monkeypatch.setattr(share, "_permission", permission)
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await share.aset_sharing(identity=user, server_id=2, enabled=True, child_id=202)
        assert not client.rows


async def test_repair_retry_retains_frozen_plan_and_admin_restriction(business, monkeypatch):
    from bisheng.dsh.domain.services import shared_model_visibility as receiver
    from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan

    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    initialize = receiver.initialize_shared_model_visibility

    async def unavailable(*args, **kwargs):
        raise ConnectionError("receiving policy unavailable")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", unavailable)
        with pytest.raises(ConnectionError):
            await share.arepair_enabled_sharing(
                identity=user,
                server_id=2,
                expected_enabled=None,
                expected_version=0,
                expected_plan_id=None,
            )
        async with factory() as session:
            async with session.begin():
                saved = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().one()
                confirmation_id = saved.id
                assert saved.model_execution_state == "RESERVED"
                session.add(
                    ModelVisibility(tenant_id=101, model_id=22, everyone=False, subjects=[], version=2, updated_by=7)
                )
        writes = len(client.writes)
        monkeypatch.setattr(receiver, "initialize_shared_model_visibility", initialize)
        await share.arepair_enabled_sharing(
            identity=user,
            server_id=2,
            expected_enabled=None,
            expected_version=0,
            expected_plan_id=None,
        )
        assert len(client.writes) == writes
        assert await policies(factory) == {(101, 22): False, (202, 22): True}
        async with factory() as session:
            saved = (await session.execute(sa.select(KnowledgeOperationPlan))).scalars().one()
            assert saved.id == confirmation_id and saved.model_execution_state == "COMPLETED"


async def test_legacy_adoption_then_off_does_not_initialize_new_child_policy(business, monkeypatch):
    from unittest.mock import AsyncMock

    from bisheng.llm.domain.models import llm_server as model_module
    from bisheng.llm.domain.models.llm_server import LLMDao, LLMModel, LLMServer

    factory, _, _, _, client = business
    share = await install_sharing(business, monkeypatch)
    client.rows = {("tenant:101", "shared_with", "llm_server:2")}
    original = share.arepair_enabled_sharing

    async def adopt_then_close(**kwargs):
        result = await original(**kwargs)
        await share.aset_sharing(identity=kwargs["identity"], server_id=2, enabled=False)
        return result

    monkeypatch.setattr(share, "arepair_enabled_sharing", adopt_then_close)
    monkeypatch.setattr(model_module, "_check_is_global_super", AsyncMock(return_value=True))
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        async with factory() as session:
            provider = await session.get(LLMServer, 2)
            old = await session.get(LLMModel, 22)
        new = LLMModel(model_name="after-off", model_type="llm", tenant_id=1, user_id=7, server_id=2)
        await LLMDao.update_server_with_models(provider, [old, new], operator=user)
        assert not client.rows
        assert (101, new.id) not in await policies(factory)
