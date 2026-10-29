"""Audit entry uses the live tenant-admin identity, not an RBAC role id."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.audit_log import AuditLogService


@pytest.mark.parametrize("admin,expected", [(True, True), (False, False)])
async def test_live_tenant_admin_and_plain_user(monkeypatch, admin, expected):
    checker = AsyncMock(return_value=admin)
    monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", checker)
    monkeypatch.setattr("bisheng.api.services.audit_log.get_current_tenant_id", lambda: 60)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr("bisheng.api.services.audit_log.UserDao.aget_user", lookup)
    assert await AuditLogService._user_has_log_web_menu(SimpleNamespace(user_id=8)) is expected
    checker.assert_awaited_once_with(8, 60)
    if admin:
        lookup.assert_not_awaited()


async def test_scope_stays_in_callers_tenant(monkeypatch):
    monkeypatch.setattr("bisheng.api.services.audit_log.get_current_tenant_id", lambda: 60)
    user = SimpleNamespace(is_global_super=False)
    assert AuditLogService._get_audit_tenant_scope(user) == 60
    from bisheng.common.errcode.http_error import UnAuthorizedError

    with pytest.raises(UnAuthorizedError):
        AuditLogService._resolve_tenant_scope(user, 1)
