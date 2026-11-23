"""Preparation has no target SQL locks or executable journals before handoff."""

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanExpiredError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.permission.domain.models import PermissionProjectionOperation
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification import test_model_deletion_application as native_business

business = native_business.business
confirmation = native_business.confirmation
impact = actual.impact
model_owner_tenant = actual.model_owner_tenant
ready = actual.ready
removal_session = actual.removal_session


@pytest.mark.parametrize("failure", [ConnectionError, asyncio.CancelledError])
async def test_pre_handoff_failure_releases_only_own_preparation_and_can_bind_original_prepared_journals(
    business, monkeypatch, failure
):
    factory, app, references, plans, client = business
    client.rows = {("tenant:202", "shared_with", "llm_server:2")}
    original = app._prepare_sharing

    async def fail_after_prepare(*args, **kwargs):
        await original(*args, **kwargs)
        raise failure("all real journals prepared, no business handoff")

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        control = await confirmation(factory, references, plans, user, server_id=2)
        monkeypatch.setattr(app, "_prepare_sharing", fail_after_prepare)
        with pytest.raises(failure):
            await app.adelete_server(identity=user, server_id=2, **control)
        assert not client.writes
        async with factory() as session:
            row = await session.get(KnowledgeOperationPlan, control["confirmation_id"])
            assert row.operation_id is None and row.model_execution_state is None
            assert not (await session.execute(sa.select(ResourceReferenceTombstone))).scalars().all()
            journals = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
            assert len(journals) == 1 and journals[0].status == "PREPARED"
        await app.arequire_idle(server_id=2)
        monkeypatch.setattr(app, "_prepare_sharing", original)
        await app.adelete_server(identity=user, server_id=2, **control)
        assert len(client.writes) == 1 and not client.rows
        async with factory() as session:
            journals = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
            assert len(journals) == 1 and journals[0].status == "FINALIZED"


async def test_confirmation_expiry_during_lock_free_prepare_leaves_zero_rrt_and_zero_sharing_writes(
    business, monkeypatch
):
    factory, app, references, plans, client = business
    client.rows = {("tenant:202", "shared_with", "llm_server:2")}
    original = app._prepare_sharing

    async def expire(*args, **kwargs):
        result = await original(*args, **kwargs)
        monkeypatch.setattr(plans, "clock", lambda: actual.NOW + timedelta(seconds=301))
        return result

    with management_tenant_scope(1), actual.native.actor(super_admin=True) as user:
        actual.web(user)
        control = await confirmation(factory, references, plans, user, server_id=2)
        monkeypatch.setattr(app, "_prepare_sharing", expire)
        with pytest.raises(KnowledgeOperationPlanExpiredError):
            await app.adelete_server(identity=user, server_id=2, **control)
        await app.arequire_idle(server_id=2)
        assert not client.writes
        async with factory() as session:
            assert not (await session.execute(sa.select(ResourceReferenceTombstone))).scalars().all()
