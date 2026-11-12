"""每次业务动作的当前资格与在线内省。协议辅助不返回业务身份。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest, new

from loguru import logger
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianDirectoryNotReadyError,
    KunlianIdentityUnavailableError,
    KunlianSessionExpiredError,
    KunlianTrustRejectedError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.sso_sync.domain.clients.kunlian import KunlianTokenBinding
from bisheng.sso_sync.domain.schemas.kunlian import KunlianTenantMapping


@dataclass(frozen=True)
class KunlianProtocolContext:
    session_hash: str
    csrf_epoch: int
    browser_binding_hash: str
    hard_expires_at: datetime


class KunlianSessionService:
    def __init__(
        self,
        repository,
        config,
        *,
        idp_client,
        user_owner,
        tenant_owner,
        multi_tenant_enabled: bool,
        csrf_secret: SecretStr | None = None,
        clock=None,
        onboarding=None,
    ):
        self.repository = repository
        self.config = config
        self.idp_client = idp_client
        self.user_owner = user_owner
        self.tenant_owner = tenant_owner
        self.multi_tenant_enabled = multi_tenant_enabled
        self.csrf_secret = csrf_secret
        self.clock = clock or repository.clock
        self.onboarding = onboarding

    def _policy(self, facts):
        if self.config.readiness_reasons(multi_tenant_enabled=self.multi_tenant_enabled):
            raise KunlianDependencyUnavailableError()
        if facts.connection is None or facts.connection.policy_revision != self.config.policy_revision:
            raise KunlianDependencyUnavailableError()
        batch = facts.published_batch
        if (
            facts.binding.connection_id != self.config.connection_id
            or batch is None
            or batch.status != "PUBLISHED"
            or facts.connection is None
            or batch.batch_id != facts.connection.active_batch_id
            or batch.completed_at is None
            or batch.completed_at > self.clock()
            or (self.clock() - batch.completed_at).total_seconds() > self.config.max_directory_age_seconds
        ):
            raise KunlianDirectoryNotReadyError()
        if (
            facts.binding.issuer != self.config.issuer
            or facts.session.client_id != self.config.client_id
            or not self.config.allows_scope(facts.binding.external_tenant_id, facts.session.workspace_id)
            or facts.mapping is None
            or not facts.mapping.materialized
        ):
            raise KunlianIdentityUnavailableError()

    async def admit_kunlian_session(self, reference, action_context):
        # 所有入口使用同一应用协议。传入动作上下文不提供业务授权。
        if action_context.transport not in ("HTTP", "WEBSOCKET"):
            raise KunlianTrustRejectedError()
        if self.config.readiness_reasons(multi_tenant_enabled=self.multi_tenant_enabled):
            raise KunlianDependencyUnavailableError()
        try:
            with tenant_execution_scope(1):
                facts = await self.repository.load_admission_facts(reference)
                self._policy(facts)
                user = await self._current_user(facts)
                version = facts.signing_context.get("token_version")
                if (
                    type(version) is not int
                    or version != user.token_version
                    or facts.signing_context.get("user_id") != user.user_id
                    or facts.signing_context.get("tenant_id") != facts.mapping.local_tenant_id
                ):
                    raise KunlianSessionExpiredError()
                mapping = KunlianTenantMapping(
                    connection_id=facts.mapping.connection_id,
                    external_tenant_id=facts.mapping.external_tenant_id,
                    local_tenant_id=facts.mapping.local_tenant_id,
                    revision=facts.mapping.revision,
                )
                with tenant_execution_scope(mapping.local_tenant_id):
                    tenant_id = await self.tenant_owner.read_current_tenant(user.user_id, mapping)
                if tenant_id != mapping.local_tenant_id:
                    raise KunlianIdentityUnavailableError()
                expected = KunlianTokenBinding(
                    facts.binding.issuer,
                    facts.session.client_id,
                    facts.binding.subject,
                    facts.binding.external_tenant_id,
                    facts.session.workspace_id,
                    facts.session.sid,
                )
                active = await self.idp_client.introspect(facts.access_token, expected=expected)
                if type(active.expires_at) is not int or active.expires_at <= int(
                    self.clock().replace(tzinfo=UTC).timestamp()
                ):
                    raise KunlianSessionExpiredError()
                # 网络往返后复核当前控制面。不能把旧 SQL 快照作为允许缓存。
                latest = await self.repository.load_admission_facts(reference)
                self._policy(latest)
                if (latest.binding.source_revision, latest.binding.auth_epoch) != (
                    facts.binding.source_revision,
                    facts.binding.auth_epoch,
                ):
                    raise KunlianDirectoryNotReadyError()
                user = await self._current_user(latest)
                if user.token_version != version or latest.signing_context != facts.signing_context:
                    raise KunlianSessionExpiredError()
                with tenant_execution_scope(mapping.local_tenant_id):
                    current_tenant = await self.tenant_owner.read_current_tenant(user.user_id, mapping)
                if current_tenant != tenant_id:
                    raise KunlianIdentityUnavailableError()
                if self.onboarding is not None:
                    from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError

                    try:
                        await self.user_owner.require_login_access(user, local_tenant_id=tenant_id)
                    except (UserNoRoleForLoginError, UserNoWebMenuForLoginError):
                        raise KunlianIdentityUnavailableError() from None
                principal = await self.user_owner.build_admitted_payload(user, local_tenant_id=tenant_id)
                raw_reference = reference.get_secret_value() if isinstance(reference, SecretStr) else reference
                principal._runtime_credential_reference = {
                    "kind": "kunlian_session",
                    "reference": raw_reference,
                    "user_id": user.user_id,
                    "tenant_id": tenant_id,
                    "token_version": user.token_version,
                    "binding_id": facts.binding.identity_key,
                    "session_hash": facts.session.session_hash,
                    "expires_at": facts.session.hard_expires_at.isoformat(),
                }
                return principal
        except KunlianSessionExpiredError:
            try:
                await self._store_transition(self.repository.mark_reauthentication_required, reference)
            except KunlianSessionExpiredError:
                # 已拒绝不存在的引用。没有可持久更新的会话。不解释为允许。
                logger.debug("Kunlian rejected session has no current reauthentication target")
            raise
        except KunlianIdentityUnavailableError:
            await self._store_transition(self.repository.revoke_session, reference, "IDENTITY_CHANGED")
            raise
        except (KunlianDirectoryNotReadyError, KunlianDependencyUnavailableError, KunlianTrustRejectedError):
            raise
        except (SQLAlchemyError, BaseErrorCode):
            raise KunlianDependencyUnavailableError() from None

    async def _current_user(self, facts):
        if self.onboarding is not None:
            return await self.onboarding.current_qualification(facts.binding)
        return await self.user_owner.read_current_qualification(
            facts.binding.local_user_id, identity_key=facts.binding.identity_key
        )

    async def _store_transition(self, operation, *args, **kwargs):
        try:
            with tenant_execution_scope(1):
                return await operation(*args, **kwargs)
        except SQLAlchemyError:
            raise KunlianDependencyUnavailableError() from None

    async def revoke_session(self, reference, reason: str):
        await self._store_transition(self.repository.revoke_session, reference, reason)

    async def local_protocol_context(self, reference) -> KunlianProtocolContext:
        facts = await self._store_transition(self.repository.load_admission_facts, reference, protocol_only=True)
        return KunlianProtocolContext(
            facts.session.session_hash,
            facts.session.csrf_epoch,
            facts.session.browser_binding_hash,
            facts.session.hard_expires_at,
        )

    async def derive_csrf(self, reference) -> str:
        if self.csrf_secret is None or not self.csrf_secret.get_secret_value() or not self.config.public_origin:
            raise KunlianDependencyUnavailableError()
        context = await self.local_protocol_context(reference)
        message = "\n".join(
            (
                "kunlian-csrf-v1",
                context.session_hash,
                str(context.csrf_epoch),
                context.browser_binding_hash,
                self.config.public_origin,
            )
        ).encode()
        return new(self.csrf_secret.get_secret_value().encode(), message, sha256).hexdigest()

    async def verify_csrf(self, reference, csrf: str, *, origin: str):
        if (
            origin != self.config.public_origin
            or not isinstance(csrf, str)
            or len(csrf) != 64
            or any(c not in "0123456789abcdef" for c in csrf)
        ):
            raise KunlianTrustRejectedError()
        if not compare_digest(await self.derive_csrf(reference), csrf):
            raise KunlianTrustRejectedError()
