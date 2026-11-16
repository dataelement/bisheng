"""AC-01/02/03: timestamp guards cannot hide durable projection failure."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.payloads import BatchResult, DepartmentUpsertItem
from bisheng.sso_sync.domain.services.departments_sync_service import DepartmentsSyncService


async def test_same_timestamp_recovery_runs_before_skip():
    calls = []
    existing = SimpleNamespace(permission_projection_operation_id=7, last_sync_ts=100)

    async def recover(row):
        calls.append("recover")

    async def guard(*args):
        calls.append("guard")
        from bisheng.org_sync.domain.services.ts_guard import GuardDecision

        return GuardDecision.SKIP_TS

    module = "bisheng.sso_sync.domain.services.departments_sync_service"
    with (
        patch(f"{module}.DepartmentDao.aget_by_source_external_id", AsyncMock(return_value=existing)),
        patch(f"{module}.OrgSyncTsGuard.check_and_update", guard),
        patch("bisheng.department.domain.services.department_service._resume_department_projection_if_needed", recover),
    ):
        result = BatchResult()
        await DepartmentsSyncService._apply_upsert(
            DepartmentUpsertItem(external_id="one", name="name", ts=100), 100, result
        )
    assert calls == ["recover", "guard"]
    assert result.skipped_ts_conflict == 1 and not result.errors


@pytest.mark.parametrize("rollback", [False, True])
async def test_subtree_paths_follow_parent_edges_and_rollback_atomically(monkeypatch, rollback):
    """AC-02: stale path prefixes do not hide a real descendant."""
    from bisheng.core.context.tenant import exact_tenant_filter
    from bisheng.database.models.department import Department
    from bisheng.department.domain.services import department_service as owner
    from test.permission.test_f048_department_scope_runtime import session_factory as fixture

    async for factory in fixture.__wrapped__():
        monkeypatch.setattr(owner, "get_async_db_session", factory)
        monkeypatch.setattr(owner, "_uses_f048_department_projection", lambda: False)
        monkeypatch.setattr(owner.DepartmentChangeHandler, "execute_async", AsyncMock())
        with exact_tenant_filter(7):
            async with factory() as db:
                for identity, parent, path in [
                    (1, None, "/1/"),
                    (2, 1, "/1/2/"),
                    (3, 1, "/1/3/"),
                    (11, 2, "/1/2/11/"),
                    (22, 11, "/old-stale/22/"),
                ]:
                    db.add(
                        Department(
                            id=identity,
                            tenant_id=7,
                            dept_id=f"e2e-f086-{identity}",
                            name="test",
                            source="wecom",
                            external_id=str(identity),
                            parent_id=parent,
                            path=path,
                        )
                    )
                await db.commit()
            if rollback:
                monkeypatch.setattr(
                    owner, "_bind_department_projection", AsyncMock(side_effect=RuntimeError("business rollback"))
                )
                with pytest.raises(RuntimeError, match="business rollback"):
                    await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
                        source="wecom",
                        external_id="11",
                        name="new",
                        parent_id=3,
                        parent_path="/1/3/",
                        sort_order=0,
                        last_sync_ts=101,
                        tenant_id=7,
                    )
            else:
                await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
                    source="wecom",
                    external_id="11",
                    name="new",
                    parent_id=3,
                    parent_path="/1/3/",
                    sort_order=0,
                    last_sync_ts=101,
                    tenant_id=7,
                )
            async with factory() as db:
                row = await db.get(Department, 22)
                assert row.path == ("/old-stale/22/" if rollback else "/1/3/11/22/")
                row = await db.get(Department, 11)
                assert row.parent_id == (2 if rollback else 3)


async def test_recovery_refresh_never_overwrites_a_later_binding(monkeypatch):
    from bisheng.common.errcode.permission import PermissionVersionConflictError
    from bisheng.department.domain.services import department_projection_scope as scopes
    from bisheng.department.domain.services import department_service as owner

    row = SimpleNamespace(
        tenant_id=7,
        permission_projection_state="FAILED_CLOSED",
        permission_projection_version=0,
        permission_projection_operation_id=41,
    )
    runtime = SimpleNamespace(reconcile_operation=AsyncMock(return_value=SimpleNamespace(target_version=1)))
    monkeypatch.setattr(owner, "_uses_f048_department_projection", lambda: True)
    monkeypatch.setattr(scopes, "get_department_projection_runtime", AsyncMock(return_value=runtime))

    async def refresh(row):
        row.permission_projection_version = 2
        row.permission_projection_operation_id = 99
        row.permission_projection_state = "CURRENT"

    session = SimpleNamespace(rollback=AsyncMock(), refresh=AsyncMock(side_effect=refresh))
    with pytest.raises(PermissionVersionConflictError):
        await owner._resume_department_projection_if_needed(row, session)
    assert row.permission_projection_version == 2 and row.permission_projection_operation_id == 99


async def test_locked_sync_write_does_not_regress_newer_timestamp(monkeypatch):
    from bisheng.core.context.tenant import exact_tenant_filter
    from bisheng.database.models.department import Department
    from bisheng.department.domain.services import department_service as owner
    from test.permission.test_f048_department_scope_runtime import session_factory as fixture

    async for factory in fixture.__wrapped__():
        monkeypatch.setattr(owner, "get_async_db_session", factory)
        monkeypatch.setattr(owner, "_uses_f048_department_projection", lambda: False)
        with exact_tenant_filter(7):
            async with factory() as db:
                db.add(
                    Department(
                        id=11,
                        tenant_id=7,
                        dept_id="e2e-f086-ts-race",
                        name="newer",
                        source="wecom",
                        external_id="11",
                        parent_id=3,
                        path="/1/3/11/",
                        last_sync_ts=200,
                    )
                )
                await db.commit()
            await owner.DepartmentTopologyProjectionService.aupsert_synced_department(
                source="wecom",
                external_id="11",
                name="older",
                parent_id=2,
                parent_path="/1/2/",
                sort_order=0,
                last_sync_ts=100,
                tenant_id=7,
            )
            async with factory() as db:
                row = await db.get(Department, 11)
                assert row.last_sync_ts == 200 and row.parent_id == 3 and row.name == "newer"
