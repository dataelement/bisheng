"""仅本地退出与辅助协议。不得产生业务 UserPayload 或在线允许结果。"""

import asyncio
import re
from dataclasses import dataclass, field
from hmac import compare_digest

from loguru import logger
from pydantic import Field, SecretStr, ValidationError

from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianError,
    KunlianLoginInvalidError,
    KunlianTrustRejectedError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.sso_sync.domain.schemas.kunlian import KunlianContract


class LogoutTicketRequest(KunlianContract):
    connection_id: str = Field(min_length=1, max_length=128, strict=True)
    ticket: SecretStr = Field(min_length=22, max_length=512, repr=False)
    browser_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


@dataclass(frozen=True)
class KunlianLocalLogoutResult:
    ticket: SecretStr | None = field(default=None, repr=False)

    def browser_payload(self):
        action = None
        if self.ticket is not None:
            action = {
                "kind": "kunlian_logout",
                "method": "POST",
                "url": "/api/kunlian/logout",
                "ticket": self.ticket.get_secret_value(),
            }
        return {"auth_source": "kunlian", "local_logged_out": True, "next_action": action}


class KunlianLogoutService:
    def __init__(self, repository, config, *, sessions, trust=None):
        self.repository, self.config, self.sessions, self.trust = repository, config, sessions, trust

    @classmethod
    def for_material_cleanup(cls, config):
        from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository

        return cls(KunlianDirectoryRepository(), config, sessions=None)

    async def expire_materials(self):
        async def run():
            sessions = await self.repository.expire_sessions(self.config.connection_id, limit=100)
            receipts = await self.repository.expire_handoff_material(self.config.connection_id, limit=100)
            return {
                "expired_sessions": sessions,
                "expired_receipts": receipts,
                "has_more": sessions == 100 or receipts == 100,
            }

        return await self._run(run)

    async def _run(self, operation):
        try:
            with tenant_execution_scope(1):
                async with asyncio.timeout(10):
                    return await operation()
        except KunlianError:
            raise
        except Exception:
            logger.error("Kunlian local protocol rejected: DEPENDENCY_UNAVAILABLE")
            raise KunlianDependencyUnavailableError() from None

    async def validate_local_subject(self, reference, subject: dict, browser_binding_hash: str):
        async def run():
            facts = await self.repository.load_admission_facts(reference, protocol_only=True)
            if (
                facts.binding.connection_id != self.config.connection_id
                or facts.binding.issuer != self.config.issuer
                or facts.session.client_id != self.config.client_id
                or re.fullmatch(r"[0-9a-f]{64}", browser_binding_hash) is None
                or not compare_digest(facts.session.browser_binding_hash, browser_binding_hash)
                or any(
                    subject.get(key) != facts.signing_context.get(key)
                    for key in ("user_id", "tenant_id", "token_version", "user_name")
                )
            ):
                raise KunlianTrustRejectedError()

        await self._run(run)

    async def csrf(self, reference) -> str:
        return await self._run(lambda: self.sessions.derive_csrf(reference))

    async def logout(self, reference, browser_binding_hash: str, *, csrf: str, origin: str):
        async def run():
            await self.sessions.verify_csrf(reference, csrf, origin=origin)
            # 独立持久提交撤销。之后才签票。签票失败也绝不恢复已撤销会话。
            await self.repository.revoke_session(reference, "LOGOUT")
            return KunlianLocalLogoutResult(await self.repository.issue_logout_ticket(reference, browser_binding_hash))

        return await self._run(run)

    async def redeem(self, raw_body: bytes, *, method: str, path: str, headers, source_allowed: bool):
        async def run():
            if self.trust is None:
                raise KunlianDependencyUnavailableError()
            if path != "/api/v1/internal/kunlian/logout-ticket:redeem":
                raise KunlianTrustRejectedError()
            await self.trust.verify_internal_request(method, path, raw_body, headers, source_allowed=source_allowed)
            try:
                request = LogoutTicketRequest.model_validate_json(raw_body)
            except (ValidationError, ValueError, TypeError):
                raise KunlianLoginInvalidError() from None
            if request.connection_id != self.config.connection_id:
                raise KunlianTrustRejectedError()
            material = await self.repository.redeem_logout_ticket(
                request.ticket,
                request.browser_binding_hash,
                expected_connection_id=self.config.connection_id,
                expected_client_id=self.config.client_id,
            )
            return {
                "id_token_hint": material.id_token.get_secret_value(),
                "client_id": material.client_id,
                "local_session_revoked": True,
            }

        return await self._run(run)
