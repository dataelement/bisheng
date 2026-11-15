"""Original compensation/finalize cannot overwrite a newer revocation."""

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee, ResourcePermissionMode
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot, GrantSnapshot
from bisheng.permission.domain.services.projection_plan import ProjectionOutcome, ProjectionTupleDelta
from test.permission.test_f048_projection_sql_runtime import (
    _plan,
    _seed_projecting_state,
)
from test.permission.test_f048_projection_sql_runtime import (
    session_factory as session_factory,
)
from test.permission.test_f048_projection_sql_runtime import (
    tenant_context as tenant_context,
)


@pytest.mark.parametrize("callback", ["owner_finalize", "owner_compensation", "grant_finalize"])
async def test_stale_callbacks_leave_later_revocation_unchanged(session_factory, monkeypatch, callback):
    monkeypatch.setattr(control_state, "get_async_db_session", session_factory)
    operation = await _seed_projecting_state(session_factory)
    with bypass_tenant_filter():
        async with session_factory() as session, session.begin():
            await session.exec(
                sa.update(ResourcePermissionMode).values(
                    version=5, operation_id=operation + 1, projection_state="CURRENT"
                )
            )
            await session.exec(sa.update(PermissionGrant).values(state="INACTIVE", projection_state="CURRENT"))
            await session.exec(sa.update(PermissionGrantAssignee).values(state="INACTIVE"))
    grant = GrantSnapshot(
        grant_id="original",
        tenant_id=7,
        resource_type="folder",
        resource_id="42",
        model=GrantModelSnapshot("viewer", True, ("download",), 1),
        active=True,
        version=1,
        sources=(),
    )
    context = SimpleNamespace(
        target=VerifiedPermissionTarget.from_business_service(
            tenant_id=7, resource_type="folder", resource_id="42", resource_version=3, context_version="original"
        ),
        copy_grants=(),
        creation_grants=(),
        idempotency_key="mode-switch-7",
        store_id="store",
        model_id="model",
        operation_type="MODE_SWITCH",
    )
    state = SqlPermissionControlState()
    outcome = ProjectionOutcome(operation, 4, "FINALIZED", "checksum")
    with pytest.raises(PermissionVersionConflictError):
        if callback == "owner_finalize":
            await state.finalize_owner(context, grant, None, outcome)
        elif callback == "owner_compensation":
            await state.mark_owner_compensation(context, RuntimeError("late failure"))
        else:
            await state.finalize_grants(context, (grant,), None, outcome)
    with bypass_tenant_filter():
        async with session_factory() as session:
            mode = (await session.exec(select(ResourcePermissionMode))).one()
            assert (mode.version, mode.operation_id, mode.projection_state) == (5, operation + 1, "CURRENT")
            assert (await session.exec(select(PermissionGrant))).one().state == "INACTIVE"
            assert {row.state for row in (await session.exec(select(PermissionGrantAssignee))).all()} == {"INACTIVE"}


async def test_original_ledger_grant_recovers_failed_closed_without_adopting_unowned_grants(session_factory):
    from dataclasses import replace

    operation = await _seed_projecting_state(session_factory, projection_state="FAILED_CLOSED")
    with bypass_tenant_filter():
        async with session_factory() as session, session.begin():
            await session.exec(sa.update(PermissionGrant).values(projection_state="FAILED_CLOSED"))
            session.add(
                PermissionGrant(
                    tenant_id=7,
                    resource_type="folder",
                    resource_id="42",
                    model_key="unowned",
                    state="PENDING",
                    projection_state="FAILED_CLOSED",
                )
            )
    key = sql_runtime.stable_grant_key(tenant_id=7, resource_type="folder", resource_id="42", model_key="viewer")
    plan = _plan()
    plan = replace(
        plan,
        deltas=(
            *plan.deltas,
            ProjectionTupleDelta(
                "STAGE", 2, "WRITE", "tenant:7#member", "ordinary_assignee", "permission_grant:" + key
            ),
        ),
    )
    await sql_runtime.SqlProjectionFinalizer().finalize(plan, operation)
    with bypass_tenant_filter():
        async with session_factory() as session:
            grants = {row.model_key: row for row in (await session.exec(select(PermissionGrant))).all()}
            assert (grants["viewer"].state, grants["viewer"].projection_state) == ("ACTIVE", "CURRENT")
            assert (grants["unowned"].state, grants["unowned"].projection_state) == ("PENDING", "FAILED_CLOSED")
