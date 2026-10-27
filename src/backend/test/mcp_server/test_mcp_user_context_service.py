import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.core.context.tenant import (
    _admin_scope_tenant_id,
    _bypass_tenant_filter,
    _is_management_api,
    _strict_tenant_filter,
    current_tenant_id,
    visible_tenant_ids,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.identity import McpIdentityRequest
from bisheng.mcp_server.domain.services.auth_service import McpAuthService
from bisheng.mcp_server.domain.services.user_context_service import McpUserContextService


class UnAuthorizedError(BaseErrorCode):
    Code = 403
    Msg = "No permission to operate"


@pytest.fixture(autouse=True)
def real_error_boundary(monkeypatch):
    # 全局 import 预桩将历史 http_error 替换为 MagicMock。局部恢复错误类型边界。
    monkeypatch.setattr("bisheng.mcp_server.domain.services.user_context_service.UnAuthorizedError", UnAuthorizedError)


def principal():
    return DeveloperTokenPrincipal(
        token_id=9, tenant_id=7, user=UserPayload(user_id=7, user_name="token", user_role=[1], tenant_id=7)
    )


def dependencies(*, enabled=True):
    candidate = SimpleNamespace(user_id=8, external_id="0008", user_name="target", token_version=3, delete=0)
    users = SimpleNamespace(list_active_by_external_id=AsyncMock(return_value=[candidate]))
    tenants = SimpleNamespace(
        list_current_by_user=AsyncMock(return_value=[SimpleNamespace(tenant_id=8, status="active", is_active=1)]),
        find_tenant=AsyncMock(return_value=SimpleNamespace(id=8 if enabled else 1, status="active")),
    )

    async def load(**kwargs):
        assert _bypass_tenant_filter.get()
        return UserPayload(user_role=[2], **kwargs)

    loader = AsyncMock(side_effect=load)
    return (
        McpUserContextService(users, tenants, multi_tenant_enabled=enabled, user_loader=loader),
        users,
        tenants,
        loader,
    )


@pytest.mark.parametrize("enabled", [True, False])
async def test_target_identity_is_exact_and_restores_all_context(enabled):
    """AC-03, AC-04, AC-05, AC-06, AC-08: 目标身份独立于 Token。完整恢复污染上下文。"""
    service, users, tenants, loader = dependencies(enabled=enabled)
    values = (
        (current_tenant_id, 999),
        (visible_tenant_ids, frozenset({999})),
        (_admin_scope_tenant_id, 999),
        (_bypass_tenant_filter, True),
        (_is_management_api, True),
        (_strict_tenant_filter, True),
    )
    tokens = [(var, var.set(value)) for var, value in values]
    try:
        bound = principal()
        identity = await service.resolve(bound, " 0008 ")
        users.list_active_by_external_id.assert_awaited_once_with("0008")
        assert identity.user.user_id == 8 and identity.user.user_role == [2]
        assert identity.tenant_id == (8 if enabled else 1)
        assert bound.user.user_id == 7 and bound.tenant_id == 7
        assert identity.token_user_id == 7 and identity.token_tenant_id == 7 and identity.token_id == 9
        if not enabled:
            tenants.list_current_by_user.assert_not_called()
        with McpAuthService.use_identity(identity):
            assert current_tenant_id.get() == identity.tenant_id
            assert visible_tenant_ids.get() == frozenset({identity.tenant_id})
            assert not _bypass_tenant_filter.get() and _admin_scope_tenant_id.get() is None
            assert not _is_management_api.get() and not _strict_tenant_filter.get()
        assert all(var.get() == value for var, value in values)
        assert loader.await_args.kwargs["token_version"] == 3
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@pytest.mark.parametrize(
    "kind",
    [
        "absent",
        "duplicate",
        "case",
        "trailing",
        "disabled",
        "no_current",
        "two_current",
        "disabled_current",
        "missing_tenant",
        "disabled_tenant",
    ],
)
async def test_unavailable_identity_denies_without_loading_roles(kind, caplog):
    """AC-03, AC-05, AC-09: 不通过角色或有效关系猜选重复账号。"""
    service, users, tenants, loader = dependencies()
    candidate = users.list_active_by_external_id.return_value[0]
    if kind == "absent":
        users.list_active_by_external_id.return_value = []
    elif kind == "duplicate":
        users.list_active_by_external_id.return_value = [candidate, candidate]
    elif kind in {"case", "trailing"}:
        candidate.external_id = "0008X" if kind == "case" else "0008 "
    elif kind == "disabled":
        candidate.delete = 1
    elif kind == "no_current":
        tenants.list_current_by_user.return_value = []
    elif kind == "two_current":
        tenants.list_current_by_user.return_value.append(SimpleNamespace(tenant_id=99, status="disabled", is_active=1))
    elif kind == "disabled_current":
        tenants.list_current_by_user.return_value[0].status = "disabled"
    elif kind == "missing_tenant":
        tenants.find_tenant.return_value = None
    elif kind == "disabled_tenant":
        tenants.find_tenant.return_value.status = "disabled"
    before = _bypass_tenant_filter.get()
    with pytest.raises(UnAuthorizedError) as error:
        await service.resolve(principal(), "0008")
    assert error.value.kwargs["mcp_identity_denied"]
    loader.assert_not_called()
    assert _bypass_tenant_filter.get() == before
    assert "0008" not in caplog.text


@pytest.mark.parametrize("failure", [RuntimeError("private role database"), asyncio.CancelledError()])
async def test_role_failure_and_cancellation_do_not_fallback(failure):
    """AC-04, AC-08: 加载失败/取消不能变成 Token 或空角色身份。"""
    service, _, _, loader = dependencies()
    loader.side_effect = failure
    before = (_bypass_tenant_filter.get(), visible_tenant_ids.get())
    with pytest.raises(type(failure)):
        await service.resolve(principal(), "0008")
    assert (_bypass_tenant_filter.get(), visible_tenant_ids.get()) == before


@pytest.mark.parametrize("value", [None, 8, True, "", "   ", "x" * 256])
def test_external_account_is_strict(value):
    """AC-01, AC-03: 数字及空账号不被隐式转换。"""
    with pytest.raises(ValidationError):
        McpIdentityRequest(external_id=value)
