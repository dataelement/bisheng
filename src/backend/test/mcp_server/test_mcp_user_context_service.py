from types import SimpleNamespace

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
    monkeypatch.setattr("bisheng.mcp_server.domain.services.user_context_service.UnAuthorizedError", UnAuthorizedError)


async def test_bound_identity_preserves_token_user_roles_and_restores_all_context():
    """F084 AC-02/03: 绑定身份不读取账号或当前租户, 完整恢复执行上下文。"""
    bound = DeveloperTokenPrincipal(
        token_id=9,
        tenant_id=7,
        user=UserPayload(user_id=8, user_name="bound", user_role=[2, 3], tenant_id=7),
    )
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
        identity = await McpUserContextService().resolve(bound)
        assert identity.user is bound.user
        assert identity.user.user_id == 8 and identity.user.user_role == [2, 3]
        assert (identity.tenant_id, identity.token_id, identity.token_user_id, identity.token_tenant_id) == (7, 9, 8, 7)
        with McpAuthService.use_identity(identity):
            assert current_tenant_id.get() == 7 and visible_tenant_ids.get() == frozenset({7})
            assert not _bypass_tenant_filter.get() and _admin_scope_tenant_id.get() is None
            assert not _is_management_api.get() and not _strict_tenant_filter.get()
        assert all(var.get() == value for var, value in values)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


async def test_mismatched_bound_tenant_fails_closed():
    """F084 AC-02: 内部不一致的 Token principal 不能选择另一个租户。"""
    bound = SimpleNamespace(token_id=9, tenant_id=7, user=UserPayload(user_id=8, user_name="bound", tenant_id=8))
    with pytest.raises(UnAuthorizedError):
        await McpUserContextService().resolve(bound)


@pytest.mark.parametrize("value", [None, 8, True, "", "0008"])
def test_tool_request_rejects_removed_external_account(value):
    """F084 AC-01: 不提供可选或隐藏账号切换参数。"""
    with pytest.raises(ValidationError):
        McpIdentityRequest(external_id=value)
