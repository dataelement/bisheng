"""Bounded, authoritative per-request mode reads; no stale-mode fallback."""

import asyncio
from dataclasses import dataclass

from loguru import logger

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.dsh.domain.schemas.model_audit import AuditMode, AuditModeSnapshot
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking


@dataclass(frozen=True, slots=True)
class EffectiveAuditMode:
    mode: AuditMode = "OFF"
    read_failed: bool = False
    reason: str | None = None


class DshModelAuditSettingService:
    def __init__(self, read_snapshot, *, timeout_seconds: float, authorize_admin=None, repository_scope=None):
        self.read_snapshot = read_snapshot
        self.timeout_seconds = timeout_seconds
        self.authorize_admin = authorize_admin
        self.repository_scope = repository_scope

    async def read_admin(self, actor_id: int, tenant_id: int | None):
        actor, target = await self.authorize_admin(actor_id, tenant_id)
        target = target if target is not None else int(actor["tenant_id"])

        def read():
            with profile_scope(target), self.repository_scope() as repository:
                return repository.read()

        return await run_audit_blocking(read)

    async def change_admin(self, actor_id: int, tenant_id: int, command):
        actor, target = await self.authorize_admin(actor_id, tenant_id)
        if actor["scope"] != "instance" or target != tenant_id:
            raise PermissionDeniedError()

        def change():
            with profile_scope(target), self.repository_scope() as repository:
                return repository.change(command, actor_user_id=actor_id)

        return await run_audit_blocking(change)

    async def read_effective(self) -> EffectiveAuditMode:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                snapshot: AuditModeSnapshot = await self.read_snapshot()
            if snapshot.mode not in {"OFF", "METADATA", "CONTENT"}:
                raise ValueError("Invalid audit mode")
            return EffectiveAuditMode(mode=snapshot.mode)
        except Exception as error:
            # Optional audit reads must not reject a valid model call; log no payload.
            logger.warning("DSH audit mode unavailable ({})", type(error).__name__)
            return EffectiveAuditMode(
                read_failed=True, reason="TIMEOUT" if isinstance(error, TimeoutError) else "UNAVAILABLE"
            )
