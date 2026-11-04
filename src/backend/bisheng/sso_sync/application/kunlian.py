"""跨模块窄协议声明。运行服务在后续任务绑定。不在此持有 ORM。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING, Protocol

from bisheng.core.config.sso_sync import KunlianConf

if TYPE_CHECKING:
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.user.application.external_identity import (
        ExternalShadowIdentity,
        ExternalShadowOperation,
        ExternalShadowReceipt,
    )

from bisheng.sso_sync.domain.schemas.kunlian import (
    KunlianActionContext,
    KunlianIdentity,
    KunlianSyncRequest,
    KunlianTenantMapping,
)


class KunlianAdmissionPort(Protocol):
    async def admit_kunlian_session(self, reference: str, action_context: KunlianActionContext) -> UserPayload: ...

    async def revoke_session(self, reference: str, reason: str) -> None: ...


class KunlianDirectoryPort(Protocol):
    async def request_directory_sync(self, request: KunlianSyncRequest) -> int: ...

    async def publish_directory(self, batch_id: str, fence: int) -> None: ...

    async def record_manual_override(
        self, identity: KunlianIdentity, disabled: bool, expected_revision: str
    ) -> None: ...


class ExternalShadowPort(Protocol):
    async def reserve_external_shadow(
        self, identity: ExternalShadowIdentity, source_revision: str
    ) -> ExternalShadowOperation: ...

    async def ensure_external_shadow(
        self, identity: ExternalShadowIdentity, expected_revision: str, *, operation: ExternalShadowOperation
    ) -> int: ...

    async def read_projection_receipt(self, operation: ExternalShadowOperation) -> ExternalShadowReceipt: ...


class ExternalMembershipPort(Protocol):
    async def ensure_external_membership(self, user_id: int, verified_mapping: KunlianTenantMapping) -> None: ...


class KunlianDirectoryApplication:
    """显式注入服务。API 与 Worker 在各自装配入口绑定。不隐式开启网络。"""

    def __init__(self, service):
        self.service = service

    async def request_directory_sync(self, request: KunlianSyncRequest) -> int:
        return await self.service.request_directory_sync(request.connection_id, request.trigger)

    async def publish_directory(self, batch_id: str, fence: int) -> None:
        await self.service.publish_directory(batch_id, fence)

    async def record_manual_override(self, identity: KunlianIdentity, disabled: bool, expected_revision: str) -> None:
        await self.service.record_manual_override(identity, disabled, expected_revision)


class KunlianManualAccountApplication:
    """持有 F118 身份锁时委托 user Owner。任何失败都不返回管理成功。"""

    def __init__(self, repository=None):
        from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository

        if repository is None:
            repository = KunlianDirectoryRepository()
        self.repository = repository

    async def set_account_status(self, user_id: int, *, disabled: bool, user_owner):
        import asyncio

        from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

        try:
            async with (
                asyncio.timeout(10),
                self.repository.manual_override_scope(user_id, disabled=disabled) as (
                    key,
                    source_active,
                    revision,
                    assert_current,
                ),
            ):
                operation = await user_owner.reserve_manual_status(
                    user_id, identity_key=key, source_revision=revision, disabled=disabled, source_active=source_active
                )
                await assert_current()
                await user_owner.set_manual_status(
                    user_id, identity_key=key, disabled=disabled, source_active=source_active, operation=operation
                )
                receipt = await user_owner.read_projection_receipt(operation)
                if receipt.user_id != user_id:
                    from bisheng.common.errcode.sso_sync import KunlianBindingConflictError

                    raise KunlianBindingConflictError()
                await assert_current()
        except TimeoutError:
            raise KunlianDependencyUnavailableError() from None


async def resolve_external_tenant_mapping(user_id: int, *, repository=None) -> KunlianTenantMapping:
    """只读当前显式映射。非昆联调用者应先由自身 Owner 判别来源。"""
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository

    with tenant_execution_scope(1):
        return await (repository or KunlianDirectoryRepository()).resolve_user_mapping(user_id)


class KunlianSessionApplication:
    """显式服务装配。只向入口暴露准入及受限协议。不输出存储事实或外部令牌。"""

    def __init__(self, service):
        self.service = service

    async def admit_kunlian_session(self, reference: str, action_context: KunlianActionContext) -> UserPayload:
        return await self.service.admit_kunlian_session(reference, action_context)

    async def revoke_session(self, reference: str, reason: str) -> None:
        await self.service.revoke_session(reference, reason)

    async def derive_csrf(self, reference: str) -> str:
        return await self.service.derive_csrf(reference)

    async def verify_csrf(self, reference: str, csrf: str, *, origin: str) -> None:
        await self.service.verify_csrf(reference, csrf, origin=origin)


class KunlianLoginApplication:
    def __init__(self, service):
        self.service = service

    async def login(self, raw_body: bytes, *, method: str, path: str, headers, source_allowed: bool):
        return await self.service.login(
            raw_body, method=method, path=path, headers=headers, source_allowed=source_allowed
        )


class KunlianLogoutApplication:
    """受限协议不能作为业务身份端口。仅接受已验证本地引用及绑定。"""

    def __init__(self, service):
        self.service = service

    async def validate_local_subject(self, reference, subject, browser_binding_hash):
        await self.service.validate_local_subject(reference, subject, browser_binding_hash)

    async def csrf(self, reference):
        return await self.service.csrf(reference)

    async def logout(self, reference, browser_binding_hash, *, csrf, origin):
        return await self.service.logout(reference, browser_binding_hash, csrf=csrf, origin=origin)

    async def redeem(self, raw_body, **kwargs):
        return await self.service.redeem(raw_body, **kwargs)


@dataclass(frozen=True)
class KunlianApiBindings:
    """由服务端装配入口注入。缺失时拒绝。不通过请求数据构造。"""

    config: KunlianConf
    login: KunlianLoginApplication | None
    management: KunlianManagementApplication | None = None
    protocol: KunlianLogoutApplication | None = None

    def allows_gateway_peer(self, host: str | None) -> bool:
        if not host or not self.config.trusted_gateway_networks:
            return False
        try:
            address = ip_address(host)
            networks = [ip_network(value, strict=True) for value in self.config.trusted_gateway_networks]
        except ValueError:
            return False
        return any(address in network for network in networks)


class KunlianManagementApplication:
    """控制面只接受服务端认证主体。每次重读当前资格。不信请求或缓存超管标记。"""

    def __init__(self, service, *, user_owner, tenant_owner, multi_tenant_enabled: bool):
        self.service = service
        self.user_owner = user_owner
        self.tenant_owner = tenant_owner
        self.multi_tenant_enabled = multi_tenant_enabled

    async def _dispatch(self, user, operation):
        from loguru import logger

        from bisheng.common.errcode.sso_sync import (
            KunlianDependencyUnavailableError,
            KunlianError,
            KunlianIdentityUnavailableError,
        )
        from bisheng.core.context.tenant import tenant_execution_scope
        from bisheng.sso_sync.domain.services.kunlian_directory import KunlianControlActor

        if type(user.user_id) is not int or user.user_id <= 0:
            raise KunlianIdentityUnavailableError()
        actor = KunlianControlActor(user.user_id, getattr(user, "tenant_id", None) or 1)
        try:
            with tenant_execution_scope(1):
                async with asyncio.timeout(10):
                    await self.user_owner.require_current_global_super(actor.user_id)
                    return await operation(actor)
        except KunlianError:
            raise
        except Exception:
            # 当前资格或审计依赖失败不能返回成功。只记录稳定原因以防泄密。
            logger.error("Kunlian management rejected: DEPENDENCY_UNAVAILABLE")
            raise KunlianDependencyUnavailableError() from None

    async def status(self, user):
        async def run(actor):
            return await self.service.management_status(multi_tenant_enabled=self.multi_tenant_enabled)

        return await self._dispatch(user, run)

    async def get_binding(self, user, external_tenant_id: str):
        async def run(actor):
            return await self.service.management_get_binding(external_tenant_id)

        return await self._dispatch(user, run)

    async def put_binding(
        self, user, external_tenant_id: str, *, local_tenant_id: int, expected_revision: int | None, enabled: bool
    ):
        async def run(actor):
            verified_id = await self.tenant_owner.validate_external_mapping_target(local_tenant_id)
            return await self.service.management_put_binding(
                external_tenant_id,
                local_tenant_id=verified_id,
                expected_revision=expected_revision,
                enabled=enabled,
                actor=actor,
            )

        return await self._dispatch(user, run)

    async def request_sync(self, user):
        async def run(actor):
            return await self.service.management_request_sync(actor=actor)

        return await self._dispatch(user, run)
