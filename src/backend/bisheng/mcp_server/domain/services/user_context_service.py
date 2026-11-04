from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.identity import McpExecutionIdentity

IDENTITY_DENIED_MESSAGE = "Token 绑定用户或租户不可用"
IDENTITY_TIMEOUT_SECONDS = 30


class McpUserContextService:
    async def resolve(self, principal: DeveloperTokenPrincipal) -> McpExecutionIdentity:
        if principal.user.tenant_id != principal.tenant_id:
            raise UnAuthorizedError(msg=IDENTITY_DENIED_MESSAGE, mcp_identity_denied=True)
        return McpExecutionIdentity(
            user=principal.user,
            tenant_id=principal.tenant_id,
            token_id=principal.token_id,
            token_user_id=principal.user.user_id,
            token_tenant_id=principal.tenant_id,
        )
