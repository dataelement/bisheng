"""全轮目录编排。只有完整发布后才报告成功。账号投影独立恢复。"""

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256

from loguru import logger
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianDirectorySyncError,
    KunlianSyncConflictError,
)
from bisheng.core.config.settings import decrypt_token, encrypt_token
from bisheng.core.config.sso_sync import KunlianConf
from bisheng.sso_sync.domain.clients.kunlian import KunlianDirectoryClient, KunlianDirectoryRequestError


@dataclass(frozen=True)
class DirectoryCredential:
    version: str
    secret: SecretStr = field(repr=False)


@dataclass(frozen=True)
class DirectorySyncOutcome:
    batch_id: str | None
    directory_status: str
    projection_status: str
    member_count: int
    unmapped_count: int


@dataclass(frozen=True)
class KunlianControlActor:
    user_id: int
    tenant_id: int


class KunlianDirectoryService:
    def __init__(
        self,
        repository,
        config: KunlianConf,
        *,
        credential_resolver,
        client_factory=KunlianDirectoryClient,
        encrypt_cursor=encrypt_token,
        decrypt_cursor=decrypt_token,
        readiness_probe=None,
    ):
        self.repository = repository
        self.config = config
        self.credential_resolver = credential_resolver
        self.client_factory = client_factory
        self.encrypt_cursor = encrypt_cursor
        self.decrypt_cursor = decrypt_cursor
        self.readiness_probe = readiness_probe

    def _check(self, connection_id):
        if not self.config.directory_enabled or connection_id != self.config.connection_id:
            raise KunlianDirectoryNotReadyError()

    async def management_status(self, *, multi_tenant_enabled: bool) -> dict:
        reasons = list(self.config.readiness_reasons(multi_tenant_enabled=multi_tenant_enabled))
        if self.readiness_probe is not None:
            reasons.extend(self.readiness_probe())
        try:
            credential = self.credential_resolver(self.config.sync_key_reference)
            if (
                not isinstance(credential, DirectoryCredential)
                or not credential.version
                or not credential.secret.get_secret_value()
            ):
                reasons.append("DIRECTORY_CREDENTIAL_UNAVAILABLE")
        except (LookupError, ValueError):
            reasons.append("DIRECTORY_CREDENTIAL_UNAVAILABLE")
        try:
            data = await self.repository.get_status(self.config.connection_id)
        except KunlianDirectoryNotReadyError:
            data = {
                "connection_id": self.config.connection_id,
                "directory_status": "UNINITIALIZED",
                "projection_status": "PENDING",
                "active_batch_id": None,
                "running_batch_id": None,
                "last_published_at": None,
                "member_count": None,
                "unmapped_count": None,
                "projection_pending": None,
                "projection_failed": None,
                "last_reason_code": None,
                "last_request_id": None,
                "last_run_at": None,
            }
            reasons.append("CONNECTION_NOT_REGISTERED")
        if data.get("enabled") is not True:
            reasons.append("CONNECTION_DISABLED")
        if data.get("policy_revision") != self.config.policy_revision:
            reasons.append("POLICY_NOT_CURRENT")
        published = data.get("last_published_at")
        age = max(0, (self.repository.clock() - published).total_seconds()) if published else None
        if age is None:
            reasons.append("DIRECTORY_NOT_PUBLISHED")
            for key in ("member_count", "unmapped_count", "projection_pending", "projection_failed"):
                data[key] = None
        elif self.config.max_directory_age_seconds is None or age > self.config.max_directory_age_seconds:
            reasons.append("DIRECTORY_STALE")
        if data["projection_status"] != "SUCCEEDED":
            reasons.append("PROJECTION_NOT_READY")
        data.update(directory_age_seconds=age, ready=not reasons, reasons=tuple(dict.fromkeys(reasons)))
        return data

    async def management_get_binding(self, external_tenant_id: str) -> dict:
        if not external_tenant_id or len(external_tenant_id) > 64:
            raise KunlianBindingConflictError()
        row = await self.repository.get_tenant_binding(self.config.connection_id, external_tenant_id)
        if row is None:
            return {
                "external_tenant_id": external_tenant_id,
                "local_tenant_id": None,
                "revision": None,
                "enabled": False,
                "materialized": False,
            }
        return {
            "external_tenant_id": row.external_tenant_id,
            "local_tenant_id": row.local_tenant_id,
            "revision": row.revision,
            "enabled": row.enabled,
            "materialized": row.materialized,
        }

    async def management_put_binding(
        self, external_tenant_id: str, *, local_tenant_id: int, expected_revision: int | None, enabled: bool, actor
    ) -> dict:
        if not self.config.connection_id:
            raise KunlianDirectoryNotReadyError()
        await self.repository.apply_connection_policy(
            self.config.connection_id, enabled=self.config.login_enabled, policy_revision=self.config.policy_revision
        )
        revision = await self.repository.bind_tenant(
            self.config.connection_id,
            external_tenant_id,
            verified_local_tenant_id=local_tenant_id,
            expected_revision=expected_revision,
            enabled=enabled,
            actor=actor,
        )
        # 返回本次已提交的修订。不用另一次读取将并发写入伪装成本次结果。
        return {
            "external_tenant_id": external_tenant_id,
            "local_tenant_id": local_tenant_id,
            "revision": revision,
            "enabled": enabled,
        }

    async def management_request_sync(self, *, actor) -> dict:
        self._check(self.config.connection_id)
        await self.repository.apply_connection_policy(
            self.config.connection_id, enabled=self.config.login_enabled, policy_revision=self.config.policy_revision
        )
        version = await self.repository.request_manual_sync(self.config.connection_id, actor=actor)
        return {"connection_id": self.config.connection_id, "requested_version": version, "status": "REQUESTED"}

    async def request_directory_sync(self, connection_id: str, trigger: str) -> int:
        self._check(connection_id)
        if trigger not in {"LOGIN_MISSING", "MANUAL", "BEAT", "RECOVERY"}:
            raise KunlianDirectorySyncError()
        await self.repository.apply_connection_policy(
            connection_id, enabled=self.config.login_enabled, policy_revision=self.config.policy_revision
        )
        return await self.repository.request_sync(connection_id)

    async def _failed(self, lease, reason):
        try:
            await self.repository.mark_failed(lease, reason)
        except KunlianSyncConflictError:
            # 已丢失租约。不能为记录失败而覆盖新执行者的状态。
            logger.warning("kunlian sync failure receipt fenced out batch={} reason={}", lease.batch_id, reason)

    async def run_sync(self, connection_id: str, owner: str) -> DirectorySyncOutcome:
        self._check(connection_id)
        config = self.config.model_copy(deep=True)
        if not config.issuer or not config.sync_key_reference:
            raise KunlianDirectoryNotReadyError()
        await self.repository.apply_connection_policy(
            connection_id, enabled=config.login_enabled, policy_revision=config.policy_revision
        )
        try:
            credential = self.credential_resolver(config.sync_key_reference)
        except (LookupError, ValueError):
            raise KunlianDependencyUnavailableError() from None
        if (
            not isinstance(credential, DirectoryCredential)
            or not credential.version
            or not credential.secret.get_secret_value()
        ):
            raise KunlianDirectoryNotReadyError()
        ttl = min(900, max(60, config.sync_timeout_seconds + 10))
        lease = await self.repository.claim_or_renew_lease(
            connection_id, owner, key_version=credential.version, page_size=config.page_size, ttl_seconds=ttl
        )
        if lease is None:
            status = await self.repository.get_status(connection_id)
            return DirectorySyncOutcome(
                status["running_batch_id"],
                "FETCHING",
                status["projection_status"],
                status["member_count"],
                status["unmapped_count"],
            )
        try:
            async with asyncio.timeout(config.sync_timeout_seconds):
                async with self.client_factory(config, api_key=credential.secret) as client:
                    page_token, cursor_ciphertext = None, None
                    seen_cursors = set()
                    while True:
                        page = await client.list_users(page_token=page_token)
                        if page.next_page_token:
                            digest = sha256(page.next_page_token.encode()).hexdigest()
                            if digest in seen_cursors:
                                raise KunlianDirectoryRequestError(400, "INVALID_ARGUMENT")
                            seen_cursors.add(digest)
                        await self.repository.claim_or_renew_lease(
                            connection_id,
                            owner,
                            key_version=credential.version,
                            page_size=config.page_size,
                            lease=lease,
                            ttl_seconds=ttl,
                        )
                        next_ciphertext = None
                        if page.next_page_token:
                            try:
                                next_ciphertext = self.encrypt_cursor(page.next_page_token)
                                if isinstance(next_ciphertext, bytes):
                                    next_ciphertext = next_ciphertext.decode("ascii")
                                if (
                                    not isinstance(next_ciphertext, str)
                                    or not next_ciphertext
                                    or next_ciphertext == page.next_page_token
                                ):
                                    raise ValueError("Invalid cursor encryption result")
                            except (ValueError, TypeError, UnicodeError):
                                raise KunlianDependencyUnavailableError() from None
                        await self.repository.stage_page(
                            lease,
                            tenants=[user.staged_tenant() for user in page.items],
                            members=[user.staged_member() for user in page.items],
                            expected_cursor_ciphertext=cursor_ciphertext,
                            next_cursor_ciphertext=next_ciphertext,
                            key_version=credential.version,
                            page_size=config.page_size,
                            request_id=page.request_id,
                        )
                        if not page.next_page_token:
                            break
                        page_token, cursor_ciphertext = page.next_page_token, next_ciphertext
                    await self.repository.publish_directory(lease, issuer=config.issuer)
        except KunlianDependencyUnavailableError:
            await self._failed(lease, "SYNC_FAILED")
            raise
        except TimeoutError:
            await self._failed(lease, "SYNC_TIMEOUT")
            raise KunlianDirectorySyncError() from None
        except (KunlianDirectorySyncError, KunlianBindingConflictError) as exc:
            reason = "DIRECTORY_INVALID"
            if isinstance(exc, KunlianDirectoryRequestError):
                reason = (
                    "UPSTREAM_UNAVAILABLE"
                    if exc.retryable
                    else "CREDENTIAL_INVALID"
                    if exc.upstream_status == 401
                    else "NETWORK_ACCESS_DENIED"
                    if exc.upstream_status == 403 and exc.upstream_code == "PROTOCOL_ERROR"
                    else "ACCESS_DENIED"
                    if exc.upstream_status == 403
                    else "CURSOR_INVALID"
                    if exc.upstream_code == "INVALID_ARGUMENT"
                    else "DIRECTORY_INVALID"
                )
            await self._failed(lease, reason)
            raise
        status = await self.repository.get_status(connection_id)
        return DirectorySyncOutcome(
            lease.batch_id, "PUBLISHED", status["projection_status"], status["member_count"], status["unmapped_count"]
        )

    async def publish_directory(self, batch_id: str, fence: int) -> None:
        lease = await self.repository.get_lease(batch_id, fence)
        self._check(lease.connection_id)
        await self.repository.publish_directory(lease, issuer=self.config.issuer)

    async def record_manual_override(self, identity, disabled: bool, expected_revision: str) -> None:
        # 手工停用在目录受控关闭时也必须可记录。
        if identity.connection_id != self.config.connection_id:
            raise KunlianBindingConflictError()
        key = self.repository.identity_key(identity.issuer, identity.external_tenant_id, identity.subject)
        binding = await self.repository.get_binding(key)
        if binding is None or (
            binding.connection_id,
            binding.issuer,
            binding.external_tenant_id,
            binding.subject,
            binding.member_id,
        ) != (
            identity.connection_id,
            identity.issuer,
            identity.external_tenant_id,
            identity.subject,
            identity.member_id,
        ):
            raise KunlianBindingConflictError()
        await self.repository.record_manual_override(key, disabled, expected_revision=expected_revision)
