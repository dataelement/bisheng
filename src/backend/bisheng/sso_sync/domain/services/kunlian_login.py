"""昆联内部交接的独立信任边界。业务登录由后续任务装配。"""

import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest, new

from loguru import logger
from pydantic import SecretStr
from redis.exceptions import RedisError

from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError

INTERNAL_PATHS = frozenset(
    {
        "/api/v1/internal/kunlian/login",
        "/api/v1/internal/kunlian/logout-ticket:redeem",
    }
)


@dataclass(frozen=True)
class TrustedHandoff:
    key_id: str
    nonce: str
    timestamp: int
    path: str
    body_digest: str


class KunlianInternalTrust:
    def __init__(
        self, *, key_id: str, secret: SecretStr, reserve_nonce: Callable[[str, int], Awaitable[bool]], clock=time.time
    ):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key_id) or not secret.get_secret_value():
            raise KunlianTrustRejectedError()
        self._key_id = key_id
        self._secret = secret
        self._reserve_nonce = reserve_nonce
        self._clock = clock
        self._window = 60

    async def verify_internal_request(
        self, method: str, path: str, raw_body: bytes, headers: Mapping[str, str], *, source_allowed: bool
    ) -> TrustedHandoff:
        if (
            source_allowed is not True
            or method != "POST"
            or path not in INTERNAL_PATHS
            or not isinstance(raw_body, bytes)
            or len(raw_body) > 65536
        ):
            raise KunlianTrustRejectedError()
        values = {}
        for name, value in headers.items():
            lowered = name.lower()
            if lowered.startswith("x-kunlian-"):
                if lowered in values or not isinstance(value, str):
                    raise KunlianTrustRejectedError()
                values[lowered] = value
        key_id = values.get("x-kunlian-key-id", "")
        timestamp = values.get("x-kunlian-timestamp", "")
        nonce = values.get("x-kunlian-nonce", "")
        provided = values.get("x-kunlian-signature", "")
        if (
            key_id != self._key_id
            or not re.fullmatch(r"[0-9]{10,12}", timestamp)
            or abs(self._clock() - int(timestamp)) > self._window
            or not re.fullmatch(r"[A-Za-z0-9_-]{22,128}", nonce)
            or not re.fullmatch(r"[0-9a-f]{64}", provided)
        ):
            raise KunlianTrustRejectedError()
        body_digest = sha256(raw_body).hexdigest()
        message = "\n".join(("v1", method, path, key_id, timestamp, nonce, body_digest)).encode("utf-8")
        expected = new(self._secret.get_secret_value().encode("utf-8"), message, sha256).hexdigest()
        if not compare_digest(expected, provided):
            raise KunlianTrustRejectedError()
        # nonce 范围覆盖未来时间戳仍可能接受的完整窗口。必须在 Redis 原子 SET NX EX。
        nonce_key = "kunlian:internal:nonce:" + sha256((key_id + "\n" + nonce).encode()).hexdigest()
        try:
            reserved = await self._reserve_nonce(nonce_key, 2 * self._window + 1)
        except (RedisError, OSError, TimeoutError):
            logger.warning("Kunlian internal request rejected: NONCE_STORE_UNAVAILABLE")
            raise KunlianTrustRejectedError() from None
        if reserved is not True:
            raise KunlianTrustRejectedError()
        return TrustedHandoff(key_id, nonce, int(timestamp), path, body_digest)


async def reserve_internal_nonce(key: str, ttl: int) -> bool:
    """生产适配器只用一次原子操作。不使用先读后写或进程内集合。"""
    from bisheng.core.cache.redis_manager import get_redis_client

    redis = await get_redis_client()
    return bool(await redis.async_connection.set(key, "1", nx=True, ex=ttl))


@dataclass(frozen=True)
class KunlianLoginResult:
    local_jwt: SecretStr = field(repr=False)
    expires_at: int
    session_reference: SecretStr = field(repr=False)
    user_id: int
    tenant_id: int

    def gateway_payload(self) -> dict:
        # 只有内部交接响应使用此方法。外部 AT 和 ID Token 永不返回。
        return {
            "local_jwt": self.local_jwt.get_secret_value(),
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
        }


class KunlianLoginService:
    def __init__(
        self,
        repository,
        config,
        *,
        trust,
        idp_client,
        directory,
        user_owner,
        tenant_owner,
        signer_factory,
        multi_tenant_enabled: bool,
        allow_multi_login: bool = True,
        clock=None,
        timeout_seconds=15,
        onboarding=None,
    ):
        self.repository = repository
        self.config = config
        self.trust = trust
        self.idp_client = idp_client
        self.directory = directory
        self.user_owner = user_owner
        self.tenant_owner = tenant_owner
        self.signer_factory = signer_factory
        self.multi_tenant_enabled = multi_tenant_enabled
        self.allow_multi_login = allow_multi_login
        self.clock = clock or repository.clock
        self.timeout_seconds = timeout_seconds
        self.onboarding = onboarding

    async def _login_qualification(self, identity):
        from bisheng.common.errcode.sso_sync import (
            KunlianDependencyUnavailableError,
            KunlianDirectoryNotReadyError,
            KunlianIdentityUnavailableError,
        )
        from bisheng.core.context.tenant import tenant_execution_scope
        from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping

        facts = await self.repository.load_login_facts(
            self.config.connection_id,
            issuer=identity.issuer,
            subject=identity.subject,
            external_tenant_id=identity.tenant_id,
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
        batch = facts.published_batch
        if (
            batch is None
            or batch.status != "PUBLISHED"
            or batch.completed_at is None
            or batch.completed_at > self.clock()
            or (self.clock() - batch.completed_at).total_seconds() > self.config.max_directory_age_seconds
            or facts.binding.local_user_id is None
            or not facts.mapping.materialized
            or facts.binding.projection_status != "SUCCEEDED"
            or facts.binding.projected_revision != facts.binding.source_revision
        ):
            raise KunlianDirectoryNotReadyError()
        if self.onboarding is not None:
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
        if tenant_id != mapping.local_tenant_id:
            raise KunlianIdentityUnavailableError()
        await self.user_owner.require_login_access(current, local_tenant_id=tenant_id)
        return facts, current, tenant_id

    async def login(
        self, raw_body: bytes, *, method: str, path: str, headers, source_allowed: bool
    ) -> KunlianLoginResult:
        import asyncio

        from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._login_once(
                    raw_body, method=method, path=path, headers=headers, source_allowed=source_allowed
                )
        except TimeoutError:
            raise KunlianDependencyUnavailableError() from None

    async def _login_once(
        self, raw_body: bytes, *, method: str, path: str, headers, source_allowed: bool
    ) -> KunlianLoginResult:
        from datetime import UTC, datetime

        from pydantic import ValidationError
        from sqlalchemy.exc import SQLAlchemyError

        from bisheng.common.errcode.base import BaseErrorCode
        from bisheng.common.errcode.sso_sync import (
            KunlianDependencyUnavailableError,
            KunlianDirectoryNotReadyError,
            KunlianError,
            KunlianIdentityUnavailableError,
            KunlianLoginInvalidError,
            KunlianSessionExpiredError,
        )
        from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError
        from bisheng.core.context.tenant import tenant_execution_scope
        from bisheng.sso_sync.domain.schemas.kunlian import KunlianLoginHandoff, KunlianSyncRequest

        trusted = await self.trust.verify_internal_request(
            method, path, raw_body, headers, source_allowed=source_allowed
        )
        if trusted.path != "/api/v1/internal/kunlian/login":
            raise KunlianTrustRejectedError()
        try:
            handoff = KunlianLoginHandoff.model_validate_json(raw_body)
        except ValidationError:
            raise KunlianLoginInvalidError() from None
        if handoff.connection_id != self.config.connection_id:
            raise KunlianLoginInvalidError()
        if self.config.readiness_reasons(multi_tenant_enabled=self.multi_tenant_enabled):
            raise KunlianDependencyUnavailableError()
        try:
            with tenant_execution_scope(1):
                try:
                    identity = await self.idp_client.verify_id_token(
                        handoff.id_token, expected_nonce=handoff.expected_nonce
                    )
                    active = await self.idp_client.introspect(handoff.access_token, expected=identity)
                except (KunlianSessionExpiredError, KunlianIdentityUnavailableError):
                    raise KunlianLoginInvalidError() from None
                if (
                    identity.issuer != self.config.issuer
                    or identity.client_id != self.config.client_id
                    or not self.config.allows_scope(identity.tenant_id, identity.workspace_id)
                ):
                    raise KunlianLoginInvalidError()
                now = int(self.clock().replace(tzinfo=UTC).timestamp())
                access_expiry = min(identity.expires_at, active.expires_at, now + handoff.expires_in)
                hard_expiry = min(identity.auth_time + 28800, now + self.config.session_max_seconds)
                if access_expiry <= now or hard_expiry <= now or identity.auth_time > now + 30:
                    raise KunlianLoginInvalidError()
                try:
                    facts, current, tenant_id = await self._login_qualification(identity)
                except KunlianDirectoryNotReadyError:
                    # 只登记补同步需求。当前交接失败。不能等待同步后继续消费原授权事务。
                    await self.directory.request_directory_sync(
                        KunlianSyncRequest(connection_id=self.config.connection_id, trigger="LOGIN_MISSING")
                    )
                    raise
                issued = await self.repository.issue_or_replay_handoff(
                    self.config.connection_id,
                    handoff.handoff_id,
                    trusted.body_digest,
                    binding_id=facts.binding.identity_key,
                    expected_source_revision=facts.binding.source_revision,
                    expected_auth_epoch=facts.binding.auth_epoch,
                    expected_policy_revision=self.config.policy_revision,
                    browser_binding_hash=handoff.browser_binding_hash,
                    client_id=identity.client_id,
                    sid=identity.sid,
                    workspace_id=identity.workspace_id,
                    access_token=handoff.access_token,
                    id_token=handoff.id_token,
                    access_token_expires_at=datetime.fromtimestamp(access_expiry, UTC).replace(tzinfo=None),
                    hard_expires_at=datetime.fromtimestamp(hard_expiry, UTC).replace(tzinfo=None),
                    signing_context={
                        "user_id": current.user_id,
                        "tenant_id": tenant_id,
                        "token_version": current.token_version,
                        "user_name": current.user_name,
                    },
                    allow_multi_login=self.allow_multi_login,
                )
                local_jwt = await self.user_owner.issue_kunlian_token(
                    issued.signing_context,
                    issued.reference,
                    identity_key=facts.binding.identity_key,
                    signer=self.signer_factory(),
                )
                return KunlianLoginResult(
                    local_jwt, issued.signing_context["exp"], issued.reference, current.user_id, tenant_id
                )
        except (KunlianError, UserNoRoleForLoginError, UserNoWebMenuForLoginError):
            raise
        except (SQLAlchemyError, BaseErrorCode, TimeoutError):
            raise KunlianDependencyUnavailableError() from None
