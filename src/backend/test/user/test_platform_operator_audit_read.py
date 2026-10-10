"""平台管理员可读当前租户审计, 不依赖 WEB_MENU 里的 log, 也不因此变成管理员."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import langchain.docstore.document  # noqa: F401
except ModuleNotFoundError:
    # 本地 langchain 已拆掉 docstore, schemas 仍从旧路径导入. 只补测试导入, 不改业务代码.
    from langchain_core.documents import Document

    docstore = types.ModuleType("langchain.docstore")
    document_mod = types.ModuleType("langchain.docstore.document")
    document_mod.Document = Document
    sys.modules["langchain.docstore"] = docstore
    sys.modules["langchain.docstore.document"] = document_mod

import pytest

from bisheng.api.services.audit_log import AuditLogService


def _user(*, role_names: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=7,
        is_global_super=False,
        role_names=role_names,
        is_admin=lambda: False,
    )


@pytest.mark.asyncio
async def test_platform_operator_reads_requested_audit_groups() -> None:
    """运营岗不持有 log 菜单时, 系统操作列表仍按请求的用户组查询, 不改查所管组."""
    operator = _user(role_names=["平台管理员"])
    with (
        patch.object(AuditLogService, "_user_has_log_web_menu", new=AsyncMock(return_value=False)),
        patch.object(AuditLogService, "_get_audit_tenant_scope", return_value=3),
        patch(
            "bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group",
            new=AsyncMock(),
        ) as admin_groups,
        patch(
            "bisheng.api.services.audit_log.AuditLogDao.get_audit_logs",
            new=AsyncMock(return_value=([], 0)),
        ) as get_logs,
    ):
        first = await AuditLogService.get_audit_log(
            operator, ["9"], [], None, None, None, None, 1, 20,
        )
        second = await AuditLogService.get_audit_log(
            operator, ["9"], [], None, None, None, None, 1, 20,
        )
    admin_groups.assert_not_called()
    assert get_logs.await_count == 2
    assert get_logs.await_args_list[0].args[0] == ["9"]
    assert get_logs.await_args_list[1].args[0] == ["9"]
    assert get_logs.await_args_list[0].kwargs["tenant_scope"] == 3
    assert first.status_code == 200
    assert second.data["total"] == 0


@pytest.mark.asyncio
async def test_non_operator_without_managed_group_cannot_read_audit() -> None:
    """没有审计菜单, 也不是平台管理员, 且不管任何用户组时, 两次请求都不查审计表."""
    user = _user(role_names=["内部员工"])
    with (
        patch.object(AuditLogService, "_user_has_log_web_menu", new=AsyncMock(return_value=False)),
        patch(
            "bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.api.services.audit_log.AuditLogDao.get_audit_logs",
            new=AsyncMock(return_value=([], 0)),
        ) as get_logs,
    ):
        first = await AuditLogService.get_audit_log(
            user, ["9"], [], None, None, None, None, 1, 20,
        )
        second = await AuditLogService.get_audit_log(
            user, ["9"], [], None, None, None, None, 1, 20,
        )
    get_logs.assert_not_called()
    assert first is not None
    assert second is not None


@pytest.mark.asyncio
async def test_platform_operator_session_list_skips_managed_group_limit() -> None:
    """应用使用列表与管理员相同: 不按所管用户组裁剪."""
    operator = _user(role_names=[" 平台管理员 "])
    with (
        patch.object(AuditLogService, "_user_has_log_web_menu", new=AsyncMock(return_value=False)),
        patch.object(AuditLogService, "_get_audit_tenant_scope", return_value=3),
        patch(
            "bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group",
            new=AsyncMock(),
        ) as admin_groups,
        patch(
            "bisheng.api.services.audit_log.MessageSessionDao.get_statement_results",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.api.services.audit_log.MessageSessionDao.get_statement_count",
            new=AsyncMock(return_value=0),
        ),
    ):
        rows, total = await AuditLogService.get_session_list(
            operator, [], [], [], None, None, None, None, 1, 20,
        )
    admin_groups.assert_not_called()
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_audit_read_matches_exact_platform_operator_name_only() -> None:
    """子串角色名不能读审计; 精确名可以. 不依赖 WEB_MENU."""
    with patch.object(AuditLogService, "_user_has_log_web_menu", new=AsyncMock(return_value=False)):
        assert await AuditLogService._can_read_tenant_audit(_user(role_names=["平台管理员"])) is True
        assert await AuditLogService._can_read_tenant_audit(_user(role_names=[" 平台管理员 "])) is True
        assert await AuditLogService._can_read_tenant_audit(_user(role_names=["xx平台管理员"])) is False
        assert await AuditLogService._can_read_tenant_audit(_user(role_names=["内部员工"])) is False
