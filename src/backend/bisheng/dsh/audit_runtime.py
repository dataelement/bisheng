"""Lazy audit composition; absent encryption keys cannot break model execution."""

import asyncio
from datetime import UTC, datetime

from loguru import logger

from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.model_audit_context import AuditContext
from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent
from bisheng.dsh.domain.services.model_audit_capture import AuditCapture
from bisheng.dsh.domain.services.model_audit_setting import DshModelAuditSettingService
from bisheng.dsh.domain.services.model_audit_writer import DshModelAuditWriter
from bisheng.dsh.domain.services.model_display import model_display_name
from bisheng.dsh.infrastructure.model_audit_activity import RedisAuditActivity
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_queue import BoundedAuditQueue
from bisheng.dsh.infrastructure.model_audit_storage import BishengMinioAuditObjects, EncryptedAuditStorage
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric
from bisheng.dsh.operations_runtime import repository_scope


class ModelAuditRuntime:
    def __init__(self, settings, redis):
        self.settings = settings
        self.writer = DshModelAuditWriter(
            lambda: repository_scope(DshModelAuditWriteRepository), self.storage, attempts=settings.audit_write_attempts
        )
        self.queue = BoundedAuditQueue(
            max_events=settings.audit_queue_max_events,
            max_bytes=settings.audit_queue_budget_bytes,
            consumer=self.writer.write,
        )
        self.evidence_queue = BoundedAuditQueue(
            max_events=settings.audit_queue_max_events,
            max_bytes=min(settings.audit_queue_budget_bytes, 4 * 1024 * 1024),
            consumer=self.writer.write,
        )
        self.activity = RedisAuditActivity(
            redis,
            interval=settings.audit_activity_interval_seconds,
            maximum=settings.audit_queue_max_events,
            observation_window=settings.audit_observation_window_seconds,
        )
        self.modes = DshModelAuditSettingService(
            self.read_mode, timeout_seconds=settings.audit_mode_read_timeout_seconds
        )

    def storage(self):
        return EncryptedAuditStorage(
            BishengMinioAuditObjects(),
            AuditKeyRing.from_environment(active_id=self.settings.audit_active_key_id),
            max_block_bytes=self.settings.audit_chunk_bytes,
            timeout_seconds=self.settings.audit_store_timeout_seconds,
        )

    async def read_mode(self):
        def read():
            with repository_scope(DshModelAuditSettingRepository) as repository:
                return repository.read()

        return await run_audit_blocking(read)

    async def capture(self, principal, request, request_id, started, model, server, audit_context=None):
        mode = await self.modes.read_effective()
        if mode.read_failed:
            record_audit_metric("mode_read_failed", tenant_id=int(principal.tenant_id))
            self.evidence_queue.put(
                AuditEvent(
                    request_id,
                    int(principal.tenant_id),
                    "evidence",
                    datetime.now(UTC),
                    metadata={"event_type": "MODE_READ_FAILED", "reason": mode.reason},
                )
            )
        context = audit_context or AuditContext()
        digest_key = None
        if mode.mode == "CONTENT":
            try:
                digest_key = AuditKeyRing.from_environment(active_id=self.settings.audit_active_key_id).resolve(
                    self.settings.audit_active_key_id
                )
            except Exception as error:
                # Missing audit keys only prevent original capture, never the model call.
                logger.warning("DSH audit key unavailable ({})", type(error).__name__)
        metadata = {
            "request_id": request_id,
            "tenant_id": int(principal.tenant_id),
            "user_id": int(principal.user_id),
            "session_id": principal.session_id,
            "model_id": model.id,
            "model_name": model_display_name(model, server),
            "provider_name": getattr(server, "name", "") or "",
            "effective_mode": mode.mode,
            "conversation_id": context.conversation_id,
            "request_kind": context.request_kind,
            "context_invalid": context.invalid,
            "started_at": started,
            "input_units": len(request.messages) + 1,
        }
        return AuditCapture(
            metadata,
            self.queue,
            now=lambda: datetime.now(UTC),
            chunk_bytes=self.settings.audit_chunk_bytes,
            request_budget_bytes=self.settings.audit_request_budget_bytes,
            evidence_queue=self.evidence_queue,
            activity=self.activity,
            digest_key=digest_key,
            key_version=self.settings.audit_active_key_id,
        )

    async def close(self):
        await self.activity.close()
        await asyncio.gather(
            self.queue.close(self.settings.audit_shutdown_seconds),
            self.evidence_queue.close(self.settings.audit_shutdown_seconds),
        )
