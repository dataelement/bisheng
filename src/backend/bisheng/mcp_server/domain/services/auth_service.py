from collections.abc import Iterator
from contextlib import contextmanager

from bisheng.core.context.tenant import (
    _admin_scope_tenant_id,
    _bypass_tenant_filter,
    _is_management_api,
    _strict_tenant_filter,
    current_tenant_id,
    visible_tenant_ids,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.mcp_server.domain.schemas.identity import McpExecutionIdentity


class McpAuthService:
    @staticmethod
    async def authenticate(
        raw_token: str | None,
        *,
        request_ip: str | None,
        user_agent: str | None,
        method: str,
    ) -> DeveloperTokenPrincipal:
        principal = await DeveloperTokenService.authenticate_principal(
            raw_token,
            request_ip=request_ip,
            user_agent=user_agent,
            endpoint_key=f"{method} /mcp",
            request_method=method,
            route_path="/mcp",
        )
        # The SDK executes tools in a different task; never carry reset tokens across tasks.
        DeveloperTokenService.reset_auth_context(principal.user)
        return principal

    @staticmethod
    @contextmanager
    def use_identity(identity: McpExecutionIdentity) -> Iterator[None]:
        values = (
            (current_tenant_id, identity.tenant_id),
            (visible_tenant_ids, frozenset({identity.tenant_id})),
            (_admin_scope_tenant_id, None),
            (_bypass_tenant_filter, False),
            (_is_management_api, False),
            (_strict_tenant_filter, False),
        )
        tokens = [(var, var.set(value)) for var, value in values]
        try:
            yield
        finally:
            for var, token in reversed(tokens):
                var.reset(token)
