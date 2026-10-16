"""Bounded local capture; no persistence ACK on the model execution path."""

import json

from loguru import logger

from bisheng.dsh.domain.schemas.model_audit_events import AuditEvent, ChannelExpectation
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope, encode_chunks
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


class AuditCapture:
    def __init__(
        self,
        metadata,
        queue,
        *,
        now,
        chunk_bytes,
        request_budget_bytes,
        evidence_queue=None,
        activity=None,
        digest_key=None,
        key_version=None,
        annotation_queue=None,
        message_sources=None,
        message_sources_status="NOT_PROVIDED",
    ):
        self.metadata, self.queue, self.now = dict(metadata), queue, now
        self.mode = self.metadata["effective_mode"]
        self.chunk_bytes, self.request_budget = chunk_bytes, request_budget_bytes
        self.evidence_queue, self.activity = evidence_queue, activity
        self.channels = {"input": ChannelExpectation(), "output": ChannelExpectation()}
        self.input_complete = False
        self.digest_key = digest_key
        self.metadata["key_version"] = key_version
        self.capture_failed = self.mode == "CONTENT" and (not isinstance(digest_key, bytes) or len(digest_key) != 32)
        self.started = False
        self.annotation_queue = annotation_queue
        self.message_sources = message_sources if self.mode == "CONTENT" else None
        self.sources_result = message_sources_status
        self.metadata["message_sources_status"] = (
            "NOT_CAPTURED"
            if self.mode != "CONTENT"
            else "PENDING"
            if self.message_sources is not None
            else message_sources_status
        )
        self.finished = False
        self.used_bytes = 0
        self.input_units = self.metadata.get("input_units", 0) if self.mode == "METADATA" else 0
        self.output_units = 0

    def _event(self, kind, **kwargs):
        kwargs["metadata"] = {**self.metadata, **kwargs.get("metadata", {})}
        return AuditEvent(self.metadata["request_id"], self.metadata["tenant_id"], kind, self.now(), **kwargs)

    def _put(self, event, queue=None, *, critical=True):
        try:
            if not (self.queue if queue is None else queue).put(event):
                if event.kind == "annotation":
                    record_audit_metric("annotation_enqueue_failed", tenant_id=event.tenant_id)
                if critical:
                    self.capture_failed = True
                logger.warning("DSH audit buffer rejected an event")
        except Exception as error:
            # Audit observer failure is explicitly non-critical; never expose payloads.
            if critical:
                self.capture_failed = True
            logger.warning("DSH audit observer unavailable ({})", type(error).__name__)

    def entered(self, input_units):
        if self.mode == "OFF" or self.started:
            return
        self.started = True
        if self.mode == "CONTENT" and self.sources_result != "NOT_PROVIDED":
            record_audit_metric("annotation_received", tenant_id=self.metadata["tenant_id"])
            if self.sources_result in {"PARTIAL", "INVALID"}:
                record_audit_metric(
                    "annotation_truncated" if self.sources_result == "PARTIAL" else "annotation_rejected",
                    tenant_id=self.metadata["tenant_id"],
                )
        self._put(self._event("entered", metadata=dict(self.metadata)))
        if self.evidence_queue is not None:
            self._put(
                self._event(
                    "evidence",
                    metadata={
                        "event_type": "MODEL_ENTERED",
                        "user_id": self.metadata["user_id"],
                        "effective_mode": self.mode,
                    },
                ),
                self.evidence_queue,
                critical=False,
            )
        if self.activity is not None:
            try:
                self.activity.started(self.metadata["request_id"])
            except Exception as error:
                logger.warning("DSH audit activity unavailable ({})", type(error).__name__)
        if self.mode == "CONTENT":
            try:
                for unit in input_units:
                    self._body("input", self.input_units, unit)
                    self.input_units += 1
                    if self.capture_failed:
                        break
                self.input_complete = not self.capture_failed
            except Exception as error:
                self.capture_failed = True
                logger.warning("DSH audit input encoding failed ({})", type(error).__name__)
            if self.message_sources is not None and self.annotation_queue is not None:
                # Provenance is independently bounded; rejection cannot mark model bodies incomplete.
                self._put(
                    self._event(
                        "annotation",
                        body=json.dumps(self.message_sources, ensure_ascii=False, separators=(",", ":")).encode("utf8"),
                        metadata={"sources_result": self.sources_result},
                    ),
                    self.annotation_queue,
                    critical=False,
                )
                self.message_sources = None

    def _body(self, channel, unit_index, value):
        if self.capture_failed:
            return
        for block in encode_chunks(value, self.chunk_bytes):
            if self.used_bytes + len(block) > self.request_budget:
                self.capture_failed = True
                logger.warning("DSH audit request budget exhausted")
                return
            self.used_bytes += len(block)
            scope = AuditScope(
                self.metadata["tenant_id"],
                self.metadata["user_id"],
                "CONVERSATION" if self.metadata.get("conversation_id") is not None else "REQUEST",
                self.metadata["conversation_id"]
                if self.metadata.get("conversation_id") is not None
                else self.metadata["request_id"],
            )
            digest = EncryptedAuditStorage._digest(self.digest_key, scope, block)
            sequence = self.channels[channel].observe_digest(len(block), digest)
            self._put(self._event("body", channel=channel, sequence=sequence, unit_index=unit_index, body=block))
            if self.capture_failed:
                return

    def output(self, value):
        if not self.started or self.finished or self.mode != "CONTENT" or self.capture_failed:
            return
        try:
            self._body("output", self.output_units, value)
            self.output_units += 1
        except Exception as error:
            self.capture_failed = True
            logger.warning("DSH audit output encoding failed ({})", type(error).__name__)

    def terminal(self, model_result):
        if not self.started or self.finished:
            return
        self.finished = True
        if self.capture_failed:
            record_audit_metric("capture_incomplete", tenant_id=self.metadata["tenant_id"])
        self._put(
            self._event(
                "terminal",
                metadata={
                    "model_result": model_result,
                    "input_complete": self.input_complete,
                    "capture_failed": self.capture_failed,
                    "input_units": self.input_units,
                    "channels": {name: state.snapshot() for name, state in self.channels.items()},
                },
            )
        )
        if self.activity is not None:
            try:
                self.activity.finished(self.metadata["request_id"])
            except Exception as error:
                logger.warning("DSH audit activity finish unavailable ({})", type(error).__name__)

    def response(self, result):
        if self.started:
            self._put(self._event("response", metadata={"response_result": result}))

    def usage(self, result):
        if self.started:
            self._put(self._event("usage", metadata={"usage_settlement": result}))
