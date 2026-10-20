from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.services.audit_log import AuditLogService


@pytest.mark.parametrize("rows", [[(2, "historical-name"), (3, "deleted-user"), (2, "historical-name")], []])
async def test_operator_business_ids_preserve_audit_scope_and_deleted_users(rows):
    user = SimpleNamespace(is_admin=lambda: True)
    with (
        patch.object(AuditLogService, "_get_audit_tenant_scope", return_value=7),
        patch("bisheng.api.services.audit_log.AuditLogDao.get_all_operators", return_value=rows) as operators,
        patch(
            "bisheng.api.services.audit_log.UserDao.aget_user_by_ids",
            new_callable=AsyncMock,
            return_value=[SimpleNamespace(user_id=2, external_id="external-002", user_name="current-name")],
        ) as users,
    ):
        result = await AuditLogService.get_all_operators(user)

    operators.assert_called_once_with([], tenant_scope=7)
    if rows:
        users.assert_awaited_once_with([2, 3])
        assert result == [
            {"user_id": 2, "user_name": "historical-name", "external_id": "external-002"},
            {"user_id": 3, "user_name": "deleted-user", "external_id": None},
        ]
    else:
        users.assert_not_awaited()
        assert result == []
