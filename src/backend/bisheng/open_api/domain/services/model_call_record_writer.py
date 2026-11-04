"""Write-behind writer for ``model_call_record`` (F051, design D9 / D14).

Larger batches than the audit writer because this face produces exactly one
small row per request while the audit path also covers rejected calls.

The credential mask is hydrated here rather than on the request path:
``OpenApiPrincipal`` does not carry one, and looking it up per call would add a
database read to the hot path for a cosmetic column. One ``IN`` query per batch
instead, with the tenant filter bypassed — a batch legitimately spans tenants
and this task has no request ContextVar.
"""

from __future__ import annotations

from loguru import logger

from bisheng.common.services.metric_log import emit_metric
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
from bisheng.open_api.domain.repositories.model_call_record_repository import ModelCallRecordRepository
from bisheng.open_api.domain.services.batched_writer import BatchedRecordWriter

RECORD_QUEUE_MAX_SIZE = 5000
RECORD_BATCH_SIZE = 200
RECORD_FLUSH_INTERVAL_SECONDS = 1.0


class ModelCallRecordWriter(BatchedRecordWriter[ModelCallRecord]):
    def __init__(
        self,
        *,
        max_queue_size: int = RECORD_QUEUE_MAX_SIZE,
        batch_size: int = RECORD_BATCH_SIZE,
        flush_interval_seconds: float = RECORD_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(
            name="model-call-record-flusher",
            write_batch=self._write_record_batch,
            max_queue_size=max_queue_size,
            batch_size=batch_size,
            flush_interval_seconds=flush_interval_seconds,
            log_event="open_api.model_call_record.write_failed",
        )

    async def _write_record_batch(self, batch: list[ModelCallRecord]) -> None:
        await self._hydrate_credential_masks(batch)
        await ModelCallRecordRepository.ainsert_batch(batch)
        emit_metric("model_call_record", status="written", batch_size=len(batch))

    @staticmethod
    async def _hydrate_credential_masks(batch: list[ModelCallRecord]) -> None:
        pending = {row.credential_id for row in batch if not row.credential_mask and row.credential_id}
        if not pending:
            return
        from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository

        try:
            with bypass_tenant_filter():
                credentials = await CredentialRepository.get_by_ids(sorted(pending))
        except Exception:
            # A cosmetic column is not worth losing the batch over; the rows
            # still land, with the mask empty, and the failure is on record.
            logger.opt(exception=True).warning(
                "open_api.model_call_record.mask_hydration_failed | credentials={}",
                len(pending),
            )
            return
        masks = {credential.id: credential.key_mask for credential in credentials}
        for row in batch:
            if not row.credential_mask:
                row.credential_mask = masks.get(row.credential_id)

    def _on_drop(self, count: int) -> None:
        emit_metric("model_call_record", status="dropped", batch_size=count)


model_call_record_writer = ModelCallRecordWriter()


__all__ = [
    "RECORD_BATCH_SIZE",
    "RECORD_FLUSH_INTERVAL_SECONDS",
    "RECORD_QUEUE_MAX_SIZE",
    "ModelCallRecordWriter",
    "model_call_record_writer",
]
