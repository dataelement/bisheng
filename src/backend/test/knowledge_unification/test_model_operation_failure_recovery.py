"""Failed model edits release or recover their actual SQL/FGA fence."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError, KnowledgeProcessingConflictError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.application.model_operation_recovery import ModelSharingPreparation, release_failed_sharing
from bisheng.llm.application.model_sharing_status import ModelSharingStatusService
from bisheng.llm.domain.models.llm_server import LLMDao
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.models import PermissionProjectionOperation
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business
from test.knowledge_unification.test_model_provider_sharing_writers import install_sharing
from test.knowledge_unification.test_model_sharing_projection import reserved

business = native_business.business
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


@contextmanager
def root_user(user_id=7, *, super_admin=True):
    user = actual.web(UserPayload(user_id=user_id, tenant_id=101, user_role=[]))
    token = set_current_permission_actor(
        PermissionActor(
            user_id=user_id,
            tenant_id=101,
            super_admin=super_admin,
        )
    )
    try:
        with management_tenant_scope(1):
            yield user
    finally:
        reset_current_permission_actor(token)


async def rows(factory, model=KnowledgeOperationPlan):
    async with factory() as session:
        with bypass_tenant_filter():
            return (await session.execute(sa.select(model).order_by(model.id))).scalars().all()


@pytest.mark.parametrize("failure", [ConnectionError, asyncio.CancelledError])
async def test_failed_read_releases_immediately_and_another_admin_can_change_command(business, monkeypatch, failure):
    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original = app._permission

    async def broken(*args, **kwargs):
        raise failure("permission runtime unavailable")

    monkeypatch.setattr(app, "_permission", broken)
    with root_user() as user:
        with pytest.raises(failure):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
        assert (await rows(factory))[0].model_execution_state == "ABANDONED"
        # Mechanical cleanup must work even when resolving the FGA runtime fails.
        await LLMDao.aupdate_model_online(22, False)
    monkeypatch.setattr(app, "_permission", original)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    assert sorted(row.model_execution_state for row in await rows(factory)) == ["COMPLETED", "SUPERSEDED"]
    assert not client.writes


@pytest.mark.parametrize("phase", ["prepared", "bound"])
async def test_prepared_journals_close_atomically_and_late_execution_cannot_write(business, monkeypatch, phase):
    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original, captured = app._permission, []

    async def permission(*args, **kwargs):
        value = await original(*args, **kwargs)
        prepare, require = value.aprepare, value.arequire_before

        async def fail_prepare(**parameters):
            prepared = await prepare(**parameters)
            captured.append((value, prepared))
            if phase == "prepared":
                raise ConnectionError("interrupted after journal insert")
            return prepared

        async def fail_bound(prepared):
            await require(prepared)
            raise ConnectionError("interrupted after binding")

        value.aprepare, value.arequire_before = fail_prepare, fail_bound
        return value

    monkeypatch.setattr(app, "_permission", permission)
    with root_user() as user:
        with pytest.raises(ConnectionError):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
        assert (await rows(factory))[0].model_execution_state == "ABANDONED"
        assert {row.status for row in await rows(factory, PermissionProjectionOperation)} == {"FAILED_CLOSED"}
        permission_app, prepared = captured[0]
        with pytest.raises(PermissionProjectionFailedError):
            await permission_app.service.reconcile_operation(prepared.batches[0].operation_id)
        with pytest.raises(PermissionPublishNotReadyError):
            await permission_app.aexecute(prepared)
        assert not client.writes
    monkeypatch.setattr(app, "_permission", original)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    assert not client.rows


async def test_historical_unsigned_expiry_is_retired_without_resigning_and_form_remains_readable(business, monkeypatch):
    factory, _, references, plans, client = business
    app = await install_sharing(business, monkeypatch)
    with root_user() as user:
        _, old, _ = await reserved(factory, references, plans, user)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    sa.update(KnowledgeOperationPlan)
                    .where(KnowledgeOperationPlan.id == old.id)
                    .values(expires_at=old.expires_at + timedelta(seconds=1))
                )
        state = await ModelSharingStatusService(app).aget(identity=user, server_id=2, include_coverage=False)
        assert state["active_plan"]["id"] == old.id
    plans.clock = lambda: actual.NOW + timedelta(minutes=6)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    retired = next(row for row in await rows(factory) if row.id == old.id)
    assert retired.model_execution_state == "SUPERSEDED"
    assert retired.plan_digest == old.plan_digest and retired.request_hash == old.request_hash
    assert retired.expires_at == old.expires_at + timedelta(seconds=1)
    assert retired.actor_user_id == 7 and retired.model_execution_metadata["ack"]["cancel_actor_user_id"] == 8
    assert not client.writes


async def test_live_preparation_is_not_cancelled_by_a_competing_command(business, monkeypatch):
    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original, entered, proceed = app._permission, asyncio.Event(), asyncio.Event()

    async def paused(*args, **kwargs):
        entered.set()
        await proceed.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(app, "_permission", paused)
    with root_user() as user:
        first = asyncio.create_task(app.aset_sharing(identity=user, server_id=2, enabled=True))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            with pytest.raises(KnowledgeProcessingConflictError):
                await app.aset_sharing(identity=user, server_id=2, enabled=False)
            assert (await rows(factory))[0].model_execution_state == "PREPARING"
        finally:
            proceed.set()
            await first
    assert len(await rows(factory)) == 1 and len(client.rows) == 2


async def test_started_projection_recovers_before_opposite_command_by_new_admin(business, monkeypatch):
    from bisheng.dsh.domain.services import shared_model_visibility as receiver

    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original = receiver.initialize_shared_model_visibility

    async def unavailable(*args, **kwargs):
        raise ConnectionError("SQL receiving policy unavailable")

    monkeypatch.setattr(receiver, "initialize_shared_model_visibility", unavailable)
    with root_user() as user:
        with pytest.raises(ConnectionError):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
    pending = (await rows(factory))[0]
    assert pending.model_execution_state == "RESERVED"
    assert pending.model_execution_metadata["ack"]["status"] == "retryable_failure"
    assert len(client.rows) == 2
    monkeypatch.setattr(receiver, "initialize_shared_model_visibility", original)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    assert not client.rows and len(client.writes) == 2
    previous = next(row for row in await rows(factory) if row.id == pending.id)
    assert previous.actor_user_id == 7
    assert previous.model_execution_metadata["ack"]["recovered_by"] == 8
    assert all(row.model_execution_state == "COMPLETED" for row in await rows(factory))


async def test_failed_closed_partial_projection_is_corrected_before_new_edit(business, monkeypatch):
    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original = client.write_tuples

    async def partial(*, writes, deletes):
        await original(writes=writes[:1], deletes=deletes)

    monkeypatch.setattr(client, "write_tuples", partial)
    with root_user() as user:
        with pytest.raises(PermissionProjectionFailedError):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
    assert (await rows(factory))[0].model_execution_state == "FAILED_CLOSED"
    monkeypatch.setattr(client, "write_tuples", original)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    assert not client.rows
    assert all(row.model_execution_state == "COMPLETED" for row in await rows(factory))


async def test_unauthorized_user_cannot_cancel_stale_preparation(business, monkeypatch):
    factory, _, references, plans, client = business
    app = await install_sharing(business, monkeypatch)
    with root_user() as user:
        await reserved(factory, references, plans, user)
    plans.clock = lambda: actual.NOW + timedelta(minutes=6)
    with root_user(8, super_admin=False) as user:
        with pytest.raises(LLMModelSharedReadonlyError) as denial:
            await app.aset_sharing(identity=user, server_id=2, enabled=False)
        assert denial.value.Code == 19801
    assert (await rows(factory))[0].model_execution_state == "PREPARING" and not client.writes


async def test_cleanup_requires_the_original_native_preparation_receipt(business, monkeypatch):
    factory, _, references, plans, client = business
    app = await install_sharing(business, monkeypatch)
    with root_user() as user:
        _, detached, _ = await reserved(factory, references, plans, user)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            ModelSharingPreparation.from_plan(detached)
        with pytest.raises(KnowledgeOperationPlanChangedError):
            await release_failed_sharing(detached, session_factory=factory, providers=app.providers)
    assert (await rows(factory))[0].model_execution_state == "PREPARING" and not client.writes


async def test_unknown_commit_is_verified_before_new_command_without_repeating_old_write(business, monkeypatch):
    factory, _, _, _, client = business
    app = await install_sharing(business, monkeypatch)
    original, write = client.read_tuples, client.write_tuples
    client.unknown = True

    async def unavailable(**kwargs):
        raise ConnectionError("cannot classify lost acknowledgement")

    async def lost_ack(**kwargs):
        monkeypatch.setattr(client, "read_tuples", unavailable)
        await write(**kwargs)

    monkeypatch.setattr(client, "write_tuples", lost_ack)
    with root_user() as user:
        with pytest.raises(ConnectionError):
            await app.aset_sharing(identity=user, server_id=2, enabled=True)
    assert (await rows(factory))[0].model_execution_state == "RESERVED"
    assert (await rows(factory, PermissionProjectionOperation))[0].status == "COMMIT_UNKNOWN"
    assert len(client.writes) == 1 and len(client.rows) == 2
    monkeypatch.setattr(client, "read_tuples", original)
    monkeypatch.setattr(client, "write_tuples", write)
    with root_user(8) as user:
        await app.aset_sharing(identity=user, server_id=2, enabled=False)
    assert len(client.writes) == 2 and not client.rows
    assert all(row.model_execution_state == "COMPLETED" for row in await rows(factory))


async def test_original_info_put_info_recovers_old_fence_and_saves_new_configuration(business, monkeypatch):
    """Failure recovery: original public API reads and saves after a stale preparation."""
    from bisheng.llm.application import model_sharing_status as status_module
    from bisheng.llm.domain.models import llm_server as model_module
    from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
    from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
    from bisheng.llm.domain.services import llm as llm_module
    from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
    from test.knowledge_unification.test_model_deletion_http import http_application
    from test.knowledge_unification.test_model_deletion_put import install

    factory, _, references, plans, _ = business
    await install(monkeypatch, business)
    app = await install_sharing(business, monkeypatch)
    status_class = status_module.ModelSharingStatusService
    monkeypatch.setattr(status_module, "ModelSharingStatusService", lambda: status_class(app))
    monkeypatch.setattr(llm_module, "_check_is_global_super", AsyncMock(return_value=True))
    monkeypatch.setattr(model_module, "_check_is_global_super", AsyncMock(return_value=True))
    monkeypatch.setattr(ResourceShareService, "list_sharing_children", AsyncMock(return_value=[]))
    with root_user() as user:
        _, old, _ = await reserved(factory, references, plans, user)
    plans.clock = lambda: actual.NOW + timedelta(minutes=6)
    with root_user(8) as user:
        async with factory() as session:
            provider = await session.get(LLMServer, 2)
            models = (await session.execute(sa.select(LLMModel).where(LLMModel.server_id == 2))).scalars().all()
            body = LLMServerCreateReq(
                **provider.model_dump(exclude={"user_id", "tenant_id", "create_time", "update_time"}),
                models=[LLMModelCreateReq.model_validate(row.model_dump()) for row in models],
            )
        body.description = "e2e-model-recovery-new-configuration"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=http_application(user)), base_url="http://test"
        ) as client:
            before = (await client.get("/api/v1/llm/info", params={"server_id": 2})).json()
            assert before["status_code"] == 200 and before["data"]["is_root_shared_readonly"] is False
            result = (await client.put("/api/v1/llm", json=body.model_dump(mode="json"))).json()
            assert result.get("status_code") == 200, result
            after = (await client.get("/api/v1/llm/info", params={"server_id": 2})).json()
            assert after["status_code"] == 200 and after["data"]["description"] == body.description
            assert actual.SECRET not in str(after)
    assert next(row for row in await rows(factory) if row.id == old.id).model_execution_state == "SUPERSEDED"
