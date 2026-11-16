"""User Owner export for F133's local account input (never an admission shortcut)."""

from dataclasses import dataclass

from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.user.domain.repositories.kunlian_account import KunlianAccountRepository


@dataclass(frozen=True)
class KunlianAccount:
    user_id: int
    tenant_id: int
    external_tenant_id: str
    external_user_id: str


class KunlianAccountApplication:
    """Discover immutable identifiers, then caller MUST invoke SSO identity.resolve.

    This read-side port does not qualify directory age, projection or login
    capabilities. API consumers must not use its result as an admitted payload.
    """

    def __init__(self, repository, directory_repository):
        self.repository = repository
        self.directory_repository = directory_repository

    async def resolve_account(self, connection_id: str, user_account: str) -> KunlianAccount:
        if (
            not isinstance(connection_id, str)
            or not connection_id.strip()
            or len(connection_id) > 64
            or not isinstance(user_account, str)
            or not user_account.strip()
            or len(user_account) > 128
        ):
            raise KunlianIdentityUnavailableError()
        accounts = await self.repository.exact_accounts(user_account)
        if len(accounts) != 1 or accounts[0].user_name != user_account or accounts[0].deleted != 0:
            raise KunlianIdentityUnavailableError()
        user_id = accounts[0].user_id
        memberships = await self.repository.current_memberships(user_id)
        if len(memberships) != 1 or type(memberships[0]) is not int or memberships[0] <= 0:
            raise KunlianIdentityUnavailableError()
        tenant_id = memberships[0]
        # Control-plane discovery is narrowly ROOT scoped, without inherited bypass.
        with tenant_execution_scope(1):
            bindings = await self.directory_repository.find_account_bindings(connection_id, user_id)
            if len(bindings) != 1:
                raise KunlianIdentityUnavailableError()
            binding = bindings[0]
            if (
                binding.connection_id != connection_id
                or binding.local_user_id != user_id
                or not binding.external_tenant_id
                or not binding.subject
            ):
                raise KunlianIdentityUnavailableError()
            mapping = await self.directory_repository.get_tenant_binding(connection_id, binding.external_tenant_id)
            if (
                mapping is None
                or not mapping.enabled
                or mapping.connection_id != connection_id
                or mapping.external_tenant_id != binding.external_tenant_id
                or mapping.local_tenant_id != tenant_id
            ):
                raise KunlianIdentityUnavailableError()
        return KunlianAccount(user_id, tenant_id, binding.external_tenant_id, binding.subject)


async def get_kunlian_account_application(app) -> KunlianAccountApplication:
    """Assemble via the existing SSO runtime; no API→ORM cross-domain imports."""
    from bisheng.sso_sync.application.runtime import get_runtime_provider

    services = await get_runtime_provider(app).worker_services()
    return KunlianAccountApplication(KunlianAccountRepository(), services.projection.repository)
