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

    @staticmethod
    def _validate_inputs(connection_id: str, user_account: str) -> None:
        if (
            not isinstance(connection_id, str)
            or not connection_id.strip()
            or len(connection_id) > 64
            or not isinstance(user_account, str)
            or not user_account.strip()
            or len(user_account) > 128
        ):
            raise KunlianIdentityUnavailableError()

    @staticmethod
    def _normalize_allowed_tenants(allowed_external_tenants: tuple[str, ...] | None) -> set[str] | None:
        if allowed_external_tenants is None or "*" in allowed_external_tenants:
            return None
        allowed = {tenant.strip() for tenant in allowed_external_tenants if isinstance(tenant, str) and tenant.strip()}
        if not allowed:
            raise KunlianIdentityUnavailableError()
        return allowed

    async def _collect_scoped_candidates(
        self,
        connection_id: str,
        user_account: str,
        *,
        allowed_tenants: set[str] | None,
        preferred_external_tenant_id: str | None,
        preferred_local_tenant_id: int | None,
    ) -> list[KunlianAccount]:
        accounts = await self.repository.exact_accounts(user_account, limit=200)
        active_accounts = [acc for acc in accounts if acc.user_name == user_account and acc.deleted == 0]
        if not active_accounts:
            return []
        candidates: list[KunlianAccount] = []
        mapping_cache: dict[str, object] = {}
        for account in active_accounts:
            memberships = await self.repository.current_memberships(account.user_id, limit=200)
            active_tenants = {tid for tid in memberships if type(tid) is int and tid > 0}
            if not active_tenants:
                continue
            with tenant_execution_scope(1):
                bindings = await self.directory_repository.find_account_bindings(
                    connection_id, account.user_id, limit=200
                )
                for binding in bindings:
                    if (
                        binding.connection_id != connection_id
                        or binding.local_user_id != account.user_id
                        or not binding.external_tenant_id
                        or not binding.subject
                    ):
                        continue
                    ext_tid = binding.external_tenant_id
                    if allowed_tenants is not None and ext_tid not in allowed_tenants:
                        continue
                    if preferred_external_tenant_id is not None and ext_tid != preferred_external_tenant_id:
                        continue
                    if ext_tid not in mapping_cache:
                        mapping_cache[ext_tid] = await self.directory_repository.get_tenant_binding(
                            connection_id, ext_tid
                        )
                    mapping = mapping_cache[ext_tid]
                    if (
                        mapping is None
                        or not mapping.enabled
                        or mapping.connection_id != connection_id
                        or mapping.external_tenant_id != ext_tid
                        or mapping.local_tenant_id not in active_tenants
                    ):
                        continue
                    if preferred_local_tenant_id is not None and mapping.local_tenant_id != preferred_local_tenant_id:
                        continue
                    candidates.append(KunlianAccount(account.user_id, mapping.local_tenant_id, ext_tid, binding.subject))
        return candidates

    async def resolve_account(self, connection_id: str, user_account: str) -> KunlianAccount:
        self._validate_inputs(connection_id, user_account)
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

    async def resolve_account_scoped(
        self,
        connection_id: str,
        user_account: str,
        *,
        allowed_external_tenants: tuple[str, ...] | None = None,
        preferred_external_tenant_id: str | None = None,
        preferred_local_tenant_id: int | None = None,
    ) -> KunlianAccount:
        """Resolve an account narrowed by credential tenant scope and request disambiguation hints."""
        self._validate_inputs(connection_id, user_account)
        if preferred_external_tenant_id is not None and (
            not isinstance(preferred_external_tenant_id, str)
            or not preferred_external_tenant_id.strip()
            or len(preferred_external_tenant_id) > 64
        ):
            raise KunlianIdentityUnavailableError()
        if preferred_local_tenant_id is not None and (
            type(preferred_local_tenant_id) is not int or preferred_local_tenant_id <= 0
        ):
            raise KunlianIdentityUnavailableError()
        allowed_tenants = self._normalize_allowed_tenants(allowed_external_tenants)
        if (
            allowed_tenants is not None
            and preferred_external_tenant_id is not None
            and preferred_external_tenant_id not in allowed_tenants
        ):
            raise KunlianIdentityUnavailableError()
        candidates = await self._collect_scoped_candidates(
            connection_id,
            user_account,
            allowed_tenants=allowed_tenants,
            preferred_external_tenant_id=preferred_external_tenant_id,
            preferred_local_tenant_id=preferred_local_tenant_id,
        )
        if len(candidates) != 1:
            raise KunlianIdentityUnavailableError()
        return candidates[0]


async def get_kunlian_account_application(app) -> KunlianAccountApplication:
    """Assemble via the existing SSO runtime; no API→ORM cross-domain imports."""
    from bisheng.sso_sync.application.runtime import get_runtime_provider

    services = await get_runtime_provider(app).worker_services()
    return KunlianAccountApplication(KunlianAccountRepository(), services.projection.repository)
