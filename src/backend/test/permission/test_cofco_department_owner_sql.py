"""Reappointments cross the real SQL prepare/finalize boundary, including visibility."""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.application import control_state
from bisheng.permission.application.control_state import SqlGrantMutationState, SqlPermissionControlState
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.application.sql_runtime import SqlProjectionFinalizer
from bisheng.permission.domain.models import PermissionProjectionOperation, ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_service import GrantMutationContext, GrantService
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSourceService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.projection_plan import ProjectionOutcome, build_projection_operation
from test.permission import test_f048_projection_sql_runtime as sql_test_helpers

session_factory = sql_test_helpers.session_factory
tenant_context = sql_test_helpers.tenant_context


class SqlProjection:
    """Replace only OpenFGA transport; retain durable SQL preparation and finalization."""

    def __init__(self, sessions):
        self.sessions = sessions

    async def prepare(self, plan):
        async with self.sessions() as session:
            operation = (
                await session.exec(
                    select(PermissionProjectionOperation).where(
                        PermissionProjectionOperation.idempotency_key == plan.idempotency_key
                    )
                )
            ).first()
            if operation is None:
                operation, _ = build_projection_operation(plan, request_checksum="a" * 64)
                session.add(operation)
                await session.commit()
            return operation

    async def execute(self, plan):
        operation = await self.prepare(plan)
        await SqlProjectionFinalizer().finalize(plan, operation.id)
        async with self.sessions() as session:
            saved = await session.get(PermissionProjectionOperation, operation.id)
            saved.status = "FINALIZED"
            await session.commit()
        return ProjectionOutcome(
            operation_id=operation.id, target_version=plan.target_version, status="FINALIZED", request_checksum="a" * 64
        )


@pytest.fixture
async def sql_runtime(session_factory, monkeypatch):
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    monkeypatch.setattr(SqlPermissionControlState, "_assert_catalog_writable", AsyncMock())
    state = SqlPermissionControlState()
    sources = GrantSourceService()
    models = tuple(
        GrantModelSnapshot(model_key=key, active=True, action_codes=("view", "manage_permission"), derived_level=level)
        for key, level in [("manager", 3), ("owner", 4)]
    )
    with bypass_tenant_filter():
        async with session_factory() as session:
            session.add(
                ResourcePermissionMode(
                    tenant_id=7,
                    resource_type="knowledge_space",
                    resource_id="42",
                    mode="CUSTOM",
                    version=0,
                    projection_state="CURRENT",
                )
            )
            await session.commit()
    runtime = object.__new__(F048PermissionRuntime)
    runtime._sources = sources
    runtime._grants = GrantService(
        source_service=sources, projection=SqlProjection(session_factory), state=SqlGrantMutationState(state)
    )

    async def build_context(*, actor, target):
        return GrantMutationContext(
            target=target,
            current_catalog_release_id=12,
            store_id="store",
            model_id="model",
            operator_id=actor.user_id,
            mode="CUSTOM",
            models=models,
            grants=await state.load_grants(target=target, models=models),
            existing_visible_sources=await state.load_visible_sources(target=target),
            system_authorized=True,
            capabilities=(),
        )

    runtime.build_grant_context = build_context
    return runtime, state, sources


async def target(state):
    version, context = await state.permission_version(tenant_id=7, resource_type="knowledge_space", resource_id="42")
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="42",
        resource_version=version,
        context_version=context,
    )


async def assert_current(state, expected_owner):
    resource = await target(state)
    visible = await state.load_visible_sources(target=resource)
    assert any(row.projected_subject == f"user:{expected_owner}" and row.model_key == "owner" for row in visible)
    mode = await state.mode_for_target(resource)
    assert mode.projection_state == "CURRENT"


async def test_repeated_owner_handover_keeps_sql_and_visible_permissions_current(sql_runtime):
    runtime, state, _ = sql_runtime
    actor = PermissionActor(user_id=1, current_tenant_id=7)
    with bypass_tenant_filter():
        for owner in [18, 19, 18, 19, 18]:
            await runtime.sync_business_owner(actor=actor, target=await target(state), owner_user_id=owner)
            await assert_current(state, owner)
        before = (await target(state)).resource_version
        assert await runtime.sync_business_owner(actor=actor, target=await target(state), owner_user_id=18) is None
        assert (await target(state)).resource_version == before


async def test_revoked_membership_can_be_restored_repeatedly(sql_runtime):
    runtime, state, sources = sql_runtime
    actor = PermissionActor(user_id=1, current_tenant_id=7)
    member = sources.canonicalize_source(
        source_id=1, subject_type="user", subject_id="18", source_type="SPACE_MEMBERSHIP", source_ref="42:user:18"
    )
    with bypass_tenant_filter():
        for cycle in range(3):
            for model in ["manager", None]:
                resource = await target(state)
                await runtime.sync_business_source_model(
                    actor=actor,
                    target=resource,
                    source=member,
                    model_key=model,
                    idempotency_key=f"membership:{cycle}:{model}:{resource.resource_version}",
                )
                visible = await state.load_visible_sources(target=await target(state))
                assert any(row.projected_subject == "user:18" for row in visible) == (model is not None)
                assert (await state.mode_for_target(await target(state))).projection_state == "CURRENT"
