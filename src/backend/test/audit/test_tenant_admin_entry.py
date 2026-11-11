"""Audit entry uses the live tenant-admin identity, not an RBAC role id."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.database.models.org_snapshot import AuditDeptScope


@pytest.mark.parametrize(
    "admin,expected",
    [
        (True, AuditDeptScope.restricted(admin_paths=["/95/313/"])),
        (False, AuditDeptScope.restricted()),
    ],
)
async def test_live_tenant_admin_and_plain_menu_role(monkeypatch, audit_identity, admin, expected):
    checker = AsyncMock(return_value=admin)
    monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", checker)
    monkeypatch.setattr(
        "bisheng.department.domain.repositories.audit_dept_repository.AuditDeptRepository.root_paths",
        AsyncMock(return_value=["/95/313/"]),
    )
    audit_identity.menu = True
    user = SimpleNamespace(user_id=8, is_global_super=False, is_admin=lambda: False)
    assert await AuditLogService._resolve_dept_scope(user, 60) == expected
    checker.assert_awaited_once_with(8, 60)


async def test_scope_stays_in_callers_tenant(monkeypatch):
    monkeypatch.setattr("bisheng.api.services.audit_log.get_current_tenant_id", lambda: 60)
    user = SimpleNamespace(is_global_super=False)
    assert AuditLogService._get_audit_tenant_scope(user) == 60
    from bisheng.common.errcode.http_error import UnAuthorizedError

    with pytest.raises(UnAuthorizedError):
        AuditLogService._resolve_tenant_scope(user, 1)
