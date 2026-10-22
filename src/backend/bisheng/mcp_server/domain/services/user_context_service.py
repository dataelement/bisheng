import logging
from collections.abc import Awaitable, Callable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter, visible_tenant_ids
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.mcp_server.domain.schemas.identity import McpExecutionIdentity, McpIdentityRequest
from bisheng.tenant.domain.repositories.interfaces.tenant_membership_repository import TenantMembershipRepository
from bisheng.user.domain.repositories.interfaces.user_repository import UserRepository

logger = logging.getLogger(__name__)
IDENTITY_DENIED_MESSAGE = "指定账号或当前租户不可用"
IDENTITY_TIMEOUT_SECONDS = 30


class McpUserContextService:
    def __init__(
        self,
        user_repository: UserRepository,
        tenant_repository: TenantMembershipRepository,
        *,
        multi_tenant_enabled: bool,
        user_loader: Callable[..., Awaitable[UserPayload]] | None = None,
    ) -> None:
        if type(multi_tenant_enabled) is not bool:
            raise ValueError("Invalid multi-tenant mode")
        self.user_repository = user_repository
        self.tenant_repository = tenant_repository
        self.multi_tenant_enabled = multi_tenant_enabled
        self.user_loader = user_loader or UserPayload.init_login_user

    @staticmethod
    def _deny(principal: DeveloperTokenPrincipal, reason: str) -> None:
        logger.warning("mcp identity denied token_id=%s reason=%s", principal.token_id, reason)
        raise UnAuthorizedError(msg=IDENTITY_DENIED_MESSAGE, mcp_identity_denied=True, reason=reason)

    async def resolve(self, principal: DeveloperTokenPrincipal, external_id: str) -> McpExecutionIdentity:
        account = McpIdentityRequest(external_id=external_id).external_id
        visible_token = visible_tenant_ids.set(None)
        try:
            # 跨范围读取仅限身份解析。业务工厂须在此作用域结束后建立。
            with bypass_tenant_filter():
                candidates = await self.user_repository.list_active_by_external_id(account)
                candidates = [row for row in candidates if row.external_id == account and row.delete == 0]
                if len(candidates) != 1:
                    self._deny(principal, "user_ambiguous" if candidates else "user_unavailable")
                candidate = candidates[0]
                tenant_id = DEFAULT_TENANT_ID
                if self.multi_tenant_enabled:
                    memberships = await self.tenant_repository.list_current_by_user(candidate.user_id)
                    if len(memberships) != 1:
                        self._deny(principal, "membership_ambiguous" if memberships else "membership_unavailable")
                    membership = memberships[0]
                    if membership.status != "active":
                        self._deny(principal, "membership_unavailable")
                    tenant_id = membership.tenant_id
                tenant = await self.tenant_repository.find_tenant(tenant_id)
                if tenant is None or tenant.status != "active":
                    self._deny(principal, "tenant_unavailable")
                user = await self.user_loader(
                    user_id=int(candidate.user_id),
                    user_name=str(candidate.user_name or ""),
                    tenant_id=int(tenant_id),
                    token_version=int(candidate.token_version or 0),
                )
                return McpExecutionIdentity(
                    user=user,
                    tenant_id=int(tenant_id),
                    token_id=principal.token_id,
                    token_user_id=principal.user.user_id,
                    token_tenant_id=principal.tenant_id,
                )
        finally:
            visible_tenant_ids.reset(visible_token)
