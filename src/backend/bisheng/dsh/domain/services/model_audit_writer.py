"""One bounded consumer writes independently of model calls."""

import asyncio
from datetime import UTC
from itertools import islice
from time import perf_counter

from loguru import logger

from bisheng.dsh.domain.schemas.model_audit_status import refresh_audit_status
from bisheng.dsh.domain.services.model_audit_integrity import verify_content
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


class DshModelAuditWriter:
    def __init__(self, repository_scope, storage_factory, *, attempts=3):
        self.repository_scope, self.storage_factory = repository_scope, storage_factory
        self.attempts = attempts
        self.written = self.failed = 0

    async def write_body_batch(self, buffer):
        """At most four object operations and 32 references per SQL transaction."""
        events = iter(buffer.events())
        while group := list(islice(events, 32)):
            verified = []
            for offset in range(0, len(group), 4):
                results = await asyncio.gather(*(self._verify_body(event) for event in group[offset : offset + 4]))
                verified.extend(result for result in results if result is not None)
            if not verified:
                continue
            for attempt in range(self.attempts):
                try:
                    await run_audit_blocking(self._persist_bodies, verified)
                    self.written += len(verified)
                    record_audit_metric("body_batch_written", tenant_id=group[0].tenant_id)
                    break
                except Exception as error:
                    logger.warning(
                        "DSH audit body SQL batch failed ({}, attempt {})", type(error).__name__, attempt + 1
                    )
                    if attempt + 1 < self.attempts:
                        await asyncio.sleep(min(0.05 * 2**attempt, 0.5))
            else:
                self.failed += len(verified)
                record_audit_metric("write_exhausted", tenant_id=group[0].tenant_id, kind="body")

    async def _verify_body(self, event):
        from bisheng.dsh.infrastructure.model_audit_codec import AuditScope

        data = event.metadata
        scope = AuditScope(
            event.tenant_id,
            data["user_id"],
            "CONVERSATION" if data.get("conversation_id") is not None else "REQUEST",
            data["conversation_id"] if data.get("conversation_id") is not None else event.request_id,
        )
        for attempt in range(self.attempts):
            try:
                reference = await self.storage_factory().put_verified_block(
                    scope, event.body, key_version=data.get("key_version")
                )
                return event, reference
            except Exception as error:
                logger.warning("DSH audit body storage failed ({}, attempt {})", type(error).__name__, attempt + 1)
                if attempt + 1 < self.attempts:
                    await asyncio.sleep(min(0.05 * 2**attempt, 0.5))
        self.failed += 1
        record_audit_metric("write_exhausted", tenant_id=event.tenant_id, kind="body")
        return None

    def _persist_bodies(self, verified):
        event = verified[-1][0]
        with profile_scope(event.tenant_id), self.repository_scope() as repository:
            row = repository.upsert_request(event)
            for body_event, reference in verified:
                repository.append_occurrence(row, body_event, reference)
            self._refresh(repository, row, event)

    async def write(self, event):
        started = perf_counter()
        for attempt in range(self.attempts):
            try:
                reference = None
                if event.kind in {"body", "annotation"}:
                    from bisheng.dsh.infrastructure.model_audit_codec import AuditScope

                    data = event.metadata
                    scope = AuditScope(
                        event.tenant_id,
                        data["user_id"],
                        "CONVERSATION" if data.get("conversation_id") is not None else "REQUEST",
                        data["conversation_id"] if data.get("conversation_id") is not None else event.request_id,
                    )
                    storage = self.storage_factory()
                    if event.kind == "annotation":
                        from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage

                        scope = AuditScope(event.tenant_id, data["user_id"], "REQUEST", event.request_id, 2)
                        storage = EncryptedAuditStorage(
                            storage.objects,
                            storage.keys,
                            max_block_bytes=16384,
                            timeout_seconds=storage.timeout_seconds,
                        )
                    reference = await storage.put_verified_block(
                        scope, event.body, key_version=event.metadata.get("key_version")
                    )
                await run_audit_blocking(self._persist, event, reference)
                self.written += 1
                record_audit_metric(
                    "written", tenant_id=event.tenant_id, kind=event.kind, duration_ms=(perf_counter() - started) * 1000
                )
                return True
            except Exception as error:
                # Audit failure is non-critical and must not leak input, keys, or provider errors.
                logger.warning("DSH audit write failed ({}, attempt {})", type(error).__name__, attempt + 1)
                if attempt + 1 < self.attempts:
                    await asyncio.sleep(min(0.05 * 2**attempt, 0.5))
        self.failed += 1
        if event.kind == "annotation":
            record_audit_metric("annotation_write_failed", tenant_id=event.tenant_id)
        record_audit_metric("write_exhausted", tenant_id=event.tenant_id, kind=event.kind)
        return False

    def _persist(self, event, reference):
        with profile_scope(event.tenant_id), self.repository_scope() as repository:
            if event.kind == "evidence":
                repository.evidence(event)
                return
            row = repository.upsert_request(event)
            if event.kind == "body":
                repository.append_occurrence(row, event, reference)
            elif event.kind == "annotation":
                repository.save_annotation(row, event, reference)
            elif event.kind == "terminal":
                repository.save_manifest(row, event)
                if row.model_result in {"RUNNING", "UNKNOWN"}:
                    row.model_result, row.model_observed_at = event.metadata["model_result"], event.observed_at
                row.input_units = event.metadata["input_units"]
                row.capture_failed |= event.metadata["capture_failed"]
            elif event.kind in {"response", "usage"}:
                axis = "response_result" if event.kind == "response" else "usage_settlement"
                previous = "RUNNING" if event.kind == "response" else "PENDING"
                if getattr(row, axis) in {previous, "UNKNOWN", "UNCERTAIN"}:
                    setattr(row, axis, event.metadata[axis])
                    setattr(
                        row,
                        "response_observed_at" if event.kind == "response" else "usage_observed_at",
                        event.observed_at,
                    )
            self._refresh(repository, row, event)

    @staticmethod
    def _refresh(repository, row, event):
        manifest = repository.manifest(row.request_id)
        if row.effective_mode == "METADATA":
            row.content_status = "NOT_CAPTURED"
        elif row.capture_failed:
            row.content_status = "PARTIAL"
        elif manifest is None:
            row.content_status = "PENDING"
        elif row.content_status != "COMPLETE":
            expected_bytes = sum(channel.get("byte_length", 0) for channel in manifest.channels.values())
            if row.input_bytes + row.output_bytes == expected_bytes:
                manifest, occurrences, contents = repository.facts(row.request_id)
                row.content_status = verify_content(row, manifest, occurrences, contents)
            else:
                row.content_status = "PARTIAL"
        # Body and control consumers can finish in either order.
        if row.last_write_at is None or event.observed_at.replace(tzinfo=UTC) >= row.last_write_at.replace(tzinfo=UTC):
            row.last_write_at = event.observed_at
        refresh_audit_status(row)
        row.state_version += 1
        repository.session.add(row)
