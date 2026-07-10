"""Tests for the resource-retaining admin migration script."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import migrate_admin_to_department as script


def _plan(primary_department_id: int | None = 5) -> script.MigrationPlan:
    return script.MigrationPlan(
        user=SimpleNamespace(user_id=1, user_name="admin"),
        target_department=SimpleNamespace(id=10, dept_id="BS@target", name="Target"),
        current_primary_department_id=primary_department_id,
        current_leaf_tenant_id=1,
        target_leaf_tenant_id=3,
        secondary_department_count=2,
        retained_resource_count=4,
    )


def test_parser_requires_exactly_one_identifier_and_rejects_receiver_flag() -> None:
    parser = script.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--dept-id", "BS@target"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--user-id",
                "1",
                "--username",
                "admin",
                "--dept-id",
                "BS@target",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--user-id",
                "1",
                "--dept-id",
                "BS@target",
                "--transfer-to-user-id",
                "2",
            ]
        )


def test_dry_run_summary_reports_retained_resources() -> None:
    summary = _plan().summary()
    assert summary["retained_resource_count"] == 4
    assert summary["mode"] == "maintenance_force_retain_resources"
    assert "receiver_user_id" not in summary


async def test_apply_uses_maintenance_only_force_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force_migrate = AsyncMock(return_value={"changed": True, "leaf_tenant_id": 3})
    monkeypatch.setattr(
        script.UserDepartmentService,
        "force_change_primary_department_for_maintenance",
        force_migrate,
    )

    result = await script.apply_plan(_plan())

    force_migrate.assert_awaited_once_with(1, 10)
    assert result["changed"] is True


async def test_run_dry_run_never_calls_apply_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    apply = AsyncMock()
    monkeypatch.setattr(script, "build_plan", AsyncMock(return_value=_plan()))
    monkeypatch.setattr(script, "apply_plan", apply)
    args = SimpleNamespace(
        user_id=1,
        username=None,
        department_id=None,
        dept_id="BS@target",
        apply=False,
    )

    assert await script.run(args) == 0
    apply.assert_not_awaited()
