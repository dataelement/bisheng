from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.org_sync.domain.services.reconciler import TransferMember
from bisheng.permission.domain.services.primary_department_change_coordinator import (
    PreparedDepartmentChange,
)

COORDINATOR = "bisheng.permission.domain.services.primary_department_change_coordinator"


def _prepared(source: str) -> PreparedDepartmentChange:
    return PreparedDepartmentChange(
        event_id=80,
        user_id=7,
        old_department_id=10,
        new_department_id=20,
        trigger_source=source,
        event_key=f"{source}:event",
    )


class _ExecResult:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def exec(self, _statement):
        return _ExecResult(self.rows)

    def add(self, _row):
        return None

    async def delete(self, _row):
        return None

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_user_department_service_triggers_cleanup_after_real_change():
    from bisheng.user.domain.services import user_department_service as module

    @asynccontextmanager
    async def session_factory():
        yield _Session()

    prepare = AsyncMock(return_value=_prepared("user_service"))
    activate = AsyncMock()
    with (
        patch.object(
            module.UserDepartmentDao,
            "aget_user_primary_department",
            new=AsyncMock(return_value=SimpleNamespace(department_id=10)),
        ),
        patch.object(module, "get_async_db_session", session_factory),
        patch.object(module.DepartmentChangeHandler, "execute_async", new=AsyncMock()),
        patch.object(module.UserTenantSyncService, "sync_user", new=AsyncMock()),
        patch(f"{COORDINATOR}.prepare_primary_department_change", prepare),
        patch(f"{COORDINATOR}.activate_primary_department_change", activate),
    ):
        result = await module.UserDepartmentService.change_primary_department(7, 20)

    assert result["changed"] is True
    assert prepare.await_args.kwargs["trigger_source"] == "user_service"
    activate.assert_awaited_once_with(_prepared("user_service"))


@pytest.mark.asyncio
async def test_local_department_edit_triggers_cleanup():
    from bisheng.department.domain.services import department_service as module

    old = SimpleNamespace(
        id=1,
        user_id=7,
        department_id=10,
        is_primary=1,
        source="local",
    )

    @asynccontextmanager
    async def session_factory():
        yield _Session([old])

    prepare = AsyncMock(return_value=_prepared("local"))
    activate = AsyncMock()
    with (
        patch.object(module, "get_async_db_session", session_factory),
        patch.object(module.DepartmentChangeHandler, "execute_async", new=AsyncMock()),
        patch.object(module.DepartmentAdminGrantDao, "adelete", new=AsyncMock()),
        patch(
            "bisheng.tenant.domain.services.user_tenant_sync_service.UserTenantSyncService.sync_user",
            new=AsyncMock(),
        ),
        patch(f"{COORDINATOR}.prepare_primary_department_change", prepare),
        patch(f"{COORDINATOR}.activate_primary_department_change", activate),
    ):
        await module.DepartmentService._apply_local_primary_department_change(7, 20)

    assert prepare.await_args.kwargs["trigger_source"] == "local"
    activate.assert_awaited_once_with(_prepared("local"))


@pytest.mark.asyncio
async def test_org_sync_transfer_triggers_cleanup():
    from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService

    op = TransferMember(
        user_id=7,
        new_primary_dept_external_id="D20",
        old_primary_dept_id=10,
        touch_primary=True,
    )
    config = SimpleNamespace(id=1, provider="wecom")
    prepare = AsyncMock(return_value=_prepared("org_sync"))
    activate = AsyncMock()
    with (
        patch(
            "bisheng.org_sync.domain.services.org_sync_service.DepartmentSyncRBACService."
            "arevoke_user_roles_in_department",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.org_sync.domain.services.org_sync_service.DepartmentSyncRBACService."
            "aapply_department_default_roles_for_user",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.org_sync.domain.services.org_sync_service.UserDepartmentDao.aremove_member",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.org_sync.domain.services.org_sync_service.UserDepartmentDao.aadd_member",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.org_sync.domain.services.org_sync_service.DepartmentChangeHandler.execute_async",
            new=AsyncMock(),
        ),
        patch(f"{COORDINATOR}.prepare_primary_department_change", prepare),
        patch(f"{COORDINATOR}.activate_primary_department_change", activate),
    ):
        await OrgSyncService._transfer_member(op, config, {"D20": 20})

    assert prepare.await_args.kwargs["trigger_source"] == "org_sync"
    activate.assert_awaited_once_with(_prepared("org_sync"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_path", "service_name", "method_name", "source"),
    [
        (
            "bisheng.sso_sync.domain.services.login_sync_service",
            "LoginSyncService",
            "_ensure_primary",
            "login_sync",
        ),
        (
            "bisheng.sso_sync.domain.services.sg_users_sync_service",
            "SgUsersSyncService",
            "_ensure_primary_membership",
            "sg_sync",
        ),
    ],
)
async def test_sync_primary_change_triggers_cleanup(
    module_path: str,
    service_name: str,
    method_name: str,
    source: str,
):
    module = __import__(module_path, fromlist=[service_name])
    service = getattr(module, service_name)
    prepare = AsyncMock(return_value=_prepared(source))
    activate = AsyncMock()
    patches = [
        patch.object(
            module.UserDepartmentDao,
            "aget_user_primary_department",
            new=AsyncMock(return_value=SimpleNamespace(department_id=10)),
        ),
        patch.object(
            module.UserDepartmentDao,
            "aget_membership",
            new=AsyncMock(return_value=None),
        ),
        patch.object(module.UserDepartmentDao, "aset_primary_flag", new=AsyncMock()),
        patch.object(module.UserDepartmentDao, "aadd_member", new=AsyncMock()),
        patch.object(service, "_sync_department_member_tuples", new=AsyncMock()),
        patch(f"{COORDINATOR}.prepare_primary_department_change", prepare),
        patch(f"{COORDINATOR}.activate_primary_department_change", activate),
    ]
    if source == "sg_sync":
        patches.append(patch.object(service, "_remove_department_membership", new=AsyncMock()))

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        if len(patches) > 7:
            with patches[7]:
                await getattr(service, method_name)(7, 20)
        else:
            await getattr(service, method_name)(7, 20, row_source="wecom")

    assert prepare.await_args.kwargs["trigger_source"] == source
    activate.assert_awaited_once_with(_prepared(source))
