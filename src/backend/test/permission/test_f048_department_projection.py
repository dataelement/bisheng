"""F048 department userset and atomic parent-mirror projection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.department.domain.services import (
    department_projection_scope,
    department_service,
)
from bisheng.department.domain.services.department_service import (
    DepartmentProjectionAuthorizationPort,
    DepartmentProjectionRecord,
)
from bisheng.permission.domain.services.department_change_handler import (
    DepartmentProjectionContext,
    F048DepartmentChangeHandler,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceService,
)


class _Projection:
    def __init__(self) -> None:
        self.plans = []

    async def execute(self, plan):
        self.plans.append(plan)
        return {"status": "FINALIZED"}


def _context(
    *,
    department_id: int = 30,
) -> DepartmentProjectionContext:
    return DepartmentProjectionContext(
        tenant_id=5,
        department_id=department_id,
        expected_version=3,
        store_id="store-live",
        model_id="model-f048",
        operator_id=7,
        idempotency_key=f"department:{department_id}:change:v4",
    )


def test_department_source_remains_a_userset_without_user_expansion() -> None:
    source = GrantSourceService().canonicalize_source(
        source_id=1,
        subject_type="department",
        subject_id="17",
        source_type="DEPARTMENT",
        include_children=True,
    )

    assert source.projected_subject == "department:17#subtree_member"
    assert source.userset_relation == "subtree_member"
    assert "user:" not in source.projected_subject


@pytest.mark.asyncio
async def test_create_projects_parent_and_child_mirror_in_one_atomic_write() -> None:
    projection = _Projection()
    handler = F048DepartmentChangeHandler(projection=projection)

    await handler.project_created(context=_context(), parent_id=10)

    plan = projection.plans[0]
    assert {delta.phase for delta in plan.deltas} == {"COMMIT"}
    assert {(delta.action, delta.user, delta.relation, delta.object) for delta in plan.deltas} == {
        ("WRITE", "department:10", "parent", "department:30"),
        ("WRITE", "department:30", "child", "department:10"),
    }


@pytest.mark.asyncio
async def test_move_replaces_parent_and_child_mirror_in_one_atomic_write() -> None:
    projection = _Projection()
    handler = F048DepartmentChangeHandler(projection=projection)
    port = DepartmentProjectionAuthorizationPort(handler)

    await port.project_moved(
        context=_context(),
        department=DepartmentProjectionRecord(
            tenant_id=5,
            department_id=30,
            parent_id=10,
            path="/1/10/30/",
            status="active",
        ),
        new_parent=DepartmentProjectionRecord(
            tenant_id=5,
            department_id=20,
            parent_id=1,
            path="/1/20/",
            status="active",
        ),
    )

    plan = projection.plans[0]
    assert len(plan.deltas) == 4
    assert {delta.phase for delta in plan.deltas} == {"COMMIT"}
    assert {(delta.action, delta.user, delta.relation, delta.object) for delta in plan.deltas} == {
        ("DELETE", "department:10", "parent", "department:30"),
        ("DELETE", "department:30", "child", "department:10"),
        ("WRITE", "department:20", "parent", "department:30"),
        ("WRITE", "department:30", "child", "department:20"),
    }


@pytest.mark.asyncio
async def test_member_exit_only_removes_department_membership_source() -> None:
    projection = _Projection()
    handler = F048DepartmentChangeHandler(projection=projection)

    await handler.project_member_removed(
        context=_context(),
        user_id=71,
    )

    plan = projection.plans[0]
    assert len(plan.deltas) == 1
    delta = plan.deltas[0]
    assert (
        delta.action,
        delta.user,
        delta.relation,
        delta.object,
    ) == ("DELETE", "user:71", "member", "department:30")
    assert "grant" not in delta.object


def test_archive_and_restore_keep_parent_child_mirror_symmetric() -> None:
    handler = F048DepartmentChangeHandler(projection=_Projection())

    archived = handler.build_archived_plan(
        context=_context(),
        parent_id=10,
    )
    restored = handler.build_restored_plan(
        context=_context(),
        parent_id=10,
    )

    assert {
        (
            delta.action,
            delta.user,
            delta.relation,
            delta.object,
        )
        for delta in archived.deltas
    } == {
        (
            "DELETE",
            "department:10",
            "parent",
            "department:30",
        ),
        (
            "DELETE",
            "department:30",
            "child",
            "department:10",
        ),
    }
    assert {
        (
            delta.action,
            delta.user,
            delta.relation,
            delta.object,
        )
        for delta in restored.deltas
    } == {
        (
            "WRITE",
            "department:10",
            "parent",
            "department:30",
        ),
        (
            "WRITE",
            "department:30",
            "child",
            "department:10",
        ),
    }


def test_system_trigger_can_prepare_department_projection() -> None:
    handler = F048DepartmentChangeHandler(projection=_Projection())
    context = DepartmentProjectionContext(
        tenant_id=5,
        department_id=30,
        expected_version=3,
        store_id="store-live",
        model_id="model-f048",
        operator_id=0,
        idempotency_key="department:30:system:v4",
    )

    plan = handler.build_members_added_plan(
        context=context,
        user_ids=(71,),
    )

    assert plan.operator_id == 0


@pytest.mark.asyncio
async def test_projecting_department_resumes_its_durable_operation(
    monkeypatch,
) -> None:
    runtime = SimpleNamespace(
        reconcile_operation=AsyncMock(
            return_value=SimpleNamespace(target_version=4),
        ),
    )
    monkeypatch.setattr(
        department_service,
        "_uses_f048_department_projection",
        lambda: True,
    )
    monkeypatch.setattr(
        department_projection_scope,
        "get_department_projection_runtime",
        lambda: runtime,
    )
    department = SimpleNamespace(
        permission_projection_state="PROJECTING",
        permission_projection_operation_id=41,
    )

    assert await department_service._resume_department_projection_if_needed(
        department,
    )
    runtime.reconcile_operation.assert_awaited_once_with(41)
    assert department.permission_projection_version == 4
    assert department.permission_projection_state == "CURRENT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("department", "new_parent"),
    (
        (
            DepartmentProjectionRecord(5, 30, 10, "/1/10/30/", "active"),
            DepartmentProjectionRecord(5, 0, 1, "/1/", "active"),
        ),
        (
            DepartmentProjectionRecord(5, 30, 10, "/1/10/30/", "active"),
            DepartmentProjectionRecord(5, 30, 1, "/1/30/", "active"),
        ),
        (
            DepartmentProjectionRecord(5, 30, 10, "/1/10/30/", "active"),
            DepartmentProjectionRecord(
                5,
                20,
                30,
                "/1/10/30/20/",
                "active",
            ),
        ),
        (
            DepartmentProjectionRecord(6, 30, 10, "/1/10/30/", "active"),
            DepartmentProjectionRecord(5, 20, 1, "/1/20/", "active"),
        ),
    ),
)
async def test_invalid_parent_or_cycle_fails_before_projection(
    department,
    new_parent,
) -> None:
    projection = _Projection()
    handler = F048DepartmentChangeHandler(projection=projection)
    port = DepartmentProjectionAuthorizationPort(handler)

    with pytest.raises(PermissionInvalidResourceError):
        await port.project_moved(
            context=_context(),
            department=department,
            new_parent=new_parent,
        )
    assert projection.plans == []
