"""Bounded, best-effort batching for per-call Open API audit records."""

from __future__ import annotations

from bisheng.database.models.audit_log import AuditLog, AuditLogDao
from bisheng.open_api.domain.services.batched_writer import (
    SHUTDOWN_TIMEOUT_SECONDS,
    BatchedRecordWriter,
)

AUDIT_QUEUE_MAX_SIZE = 1000
AUDIT_BATCH_SIZE = 100
AUDIT_FLUSH_INTERVAL_SECONDS = 1.0
AUDIT_SHUTDOWN_TIMEOUT_SECONDS = SHUTDOWN_TIMEOUT_SECONDS


class OpenApiCallAuditService(BatchedRecordWriter[AuditLog]):
    """One ``open_api.call`` row per ``/api/v2`` request, written write-behind."""

    def __init__(
        self,
        *,
        max_queue_size: int = AUDIT_QUEUE_MAX_SIZE,
        batch_size: int = AUDIT_BATCH_SIZE,
        flush_interval_seconds: float = AUDIT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(
            name="open-api-call-audit-flusher",
            write_batch=self._write_audit_batch,
            max_queue_size=max_queue_size,
            batch_size=batch_size,
            flush_interval_seconds=flush_interval_seconds,
            log_event="open_api.audit.write_failed",
        )

    @staticmethod
    async def _write_audit_batch(batch: list[AuditLog]) -> None:
        # Resolved through the module-level name on every call so a test (or a
        # future decorator) can replace the DAO method.
        await AuditLogDao.ainsert_audit_logs(batch)


open_api_call_audit_service = OpenApiCallAuditService()


__all__ = [
    "AUDIT_BATCH_SIZE",
    "AUDIT_FLUSH_INTERVAL_SECONDS",
    "AUDIT_QUEUE_MAX_SIZE",
    "AUDIT_SHUTDOWN_TIMEOUT_SECONDS",
    "OpenApiCallAuditService",
    "open_api_call_audit_service",
]
