"""F133 read-only API identity boundary; no token, browser session or onboarding writes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping

if TYPE_CHECKING:
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.config.sso_sync import KunlianConf


class KunlianIdentityPort(Protocol):
    async def resolve(self, connection_id: str, external_tenant_id: str, external_user_id: str) -> UserPayload: ...


class KunlianIdentityApplication:
    """Injected Owner read ports. Callers must independently enforce Key scope/capabilities.

    external_user_id is the OIDC subject, never directory member_id or display name.
    The temporary discovery/qualification scope is restored before returning; the
    request dependency installs the returned tenant for business execution.
    """

    def __init__(
        self,
        repository,
        config: KunlianConf,
        *,
        user_owner,
        tenant_owner,
        multi_tenant_enabled: bool,
        onboarding=None,
        timeout_seconds: float = 10,
    ):
        self.repository = repository
        self.config = config
        self.user_owner = user_owner
        self.tenant_owner = tenant_owner
        self.multi_tenant_enabled = multi_tenant_enabled
        self.onboarding = onboarding
        self.timeout_seconds = timeout_seconds

    async def resolve(self, connection_id: str, external_tenant_id: str, external_user_id: str) -> UserPayload:
        if (
            any(
                not isinstance(value, str) or not value.strip()
                for value in (connection_id, external_tenant_id, external_user_id)
            )
            or connection_id != self.config.connection_id
            or len(connection_id) > 64
            or len(external_tenant_id) > 64
            or len(external_user_id) > 128
        ):
            raise KunlianIdentityUnavailableError()
        # API authentication does not depend on browser login or OIDC secret readiness.
        if (
            not self.multi_tenant_enabled
            or not self.config.directory_enabled
            or not self.config.issuer
            or self.config.max_directory_age_seconds is None
        ):
            raise KunlianDependencyUnavailableError()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                with tenant_execution_scope(1):
                    return await self._resolve(connection_id, external_tenant_id, external_user_id)
        except TimeoutError:
            raise KunlianDependencyUnavailableError() from None

    async def _resolve(self, connection_id, external_tenant_id, external_user_id):
        facts = await self.repository.load_login_facts(
            connection_id,
            issuer=self.config.issuer,
            subject=external_user_id,
            external_tenant_id=external_tenant_id,
        )
        if not facts.connection.enabled or facts.connection.policy_revision != self.config.policy_revision:
            raise KunlianDependencyUnavailableError()
        if (
            facts.binding.admission_status != "ACTIVE"
            or facts.binding.local_override
            or (facts.mapping is not None and not facts.mapping.enabled)
        ):
            raise KunlianIdentityUnavailableError()
        if facts.mapping is None:
            raise KunlianDirectoryNotReadyError()

        if (
            facts.binding.connection_id,
            facts.binding.issuer,
            facts.binding.external_tenant_id,
            facts.binding.subject,
        ) != (connection_id, self.config.issuer, external_tenant_id, external_user_id) or (
            facts.mapping.connection_id,
            facts.mapping.external_tenant_id,
        ) != (connection_id, external_tenant_id):
            raise KunlianBindingConflictError()
        batch = facts.published_batch
        now = self.repository.clock()
        if (
            batch is None
            or batch.status != "PUBLISHED"
            or batch.completed_at is None
            or batch.completed_at > now
            or (now - batch.completed_at).total_seconds() > self.config.max_directory_age_seconds
            or facts.binding.local_user_id is None
            or not facts.mapping.materialized
            or facts.binding.projection_status != "SUCCEEDED"
            or facts.binding.projected_revision != facts.binding.source_revision
        ):
            raise KunlianDirectoryNotReadyError()
        if self.onboarding is not None:
            # Only the read-side qualification method; never run/provision/recover.
            current = await self.onboarding.current_qualification(facts.binding)
        else:
            current = await self.user_owner.read_current_qualification(
                facts.binding.local_user_id, identity_key=facts.binding.identity_key
            )
        mapping = KunlianTenantMapping(
            connection_id=facts.mapping.connection_id,
            external_tenant_id=facts.mapping.external_tenant_id,
            local_tenant_id=facts.mapping.local_tenant_id,
            revision=facts.mapping.revision,
        )
        with tenant_execution_scope(mapping.local_tenant_id):
            tenant_id = await self.tenant_owner.read_current_tenant(current.user_id, mapping)
            if tenant_id != mapping.local_tenant_id or current.user_id != facts.binding.local_user_id:
                raise KunlianIdentityUnavailableError()
            await self.user_owner.require_login_access(current, local_tenant_id=tenant_id)
            payload = await self.user_owner.build_admitted_payload(current, local_tenant_id=tenant_id)
        if payload.is_global_super is not False:
            raise KunlianIdentityUnavailableError()
        return payload


async def get_kunlian_identity_application(app) -> KunlianIdentityApplication:
    """Default assembly uses current settings and the shared runtime Owner instances.

    The provider may prepare local clients, but this boundary never calls external
    services. It intentionally does not require runtime.api_bindings().login.
    """
    from bisheng.common.services.config_service import settings
    from bisheng.sso_sync.application.runtime import get_runtime_provider

    services = await get_runtime_provider(app).worker_services()
    return KunlianIdentityApplication(
        services.projection.repository,
        services.config,
        user_owner=services.projection.user_owner,
        tenant_owner=services.projection.tenant_owner,
        multi_tenant_enabled=settings.multi_tenant.enabled,
        onboarding=services.onboarding,
    )
