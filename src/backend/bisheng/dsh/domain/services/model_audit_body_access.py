"""Durable authorization attempt precedes every plaintext byte; bounded NDJSON."""

import asyncio
import codecs
import json
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.dsh_audit import DshAuditAccessLogUnavailableError, DshAuditOriginalUnavailableError
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope
from bisheng.dsh.infrastructure.model_audit_storage import StoredAuditBlock
from bisheng.dsh.infrastructure.model_audit_telemetry import record_audit_metric


def frame(kind, **fields):
    return json.dumps(dict(type=kind, **fields), ensure_ascii=False, separators=(",", ":")) + "\n"


class DshModelAuditBodyAccessService:
    def __init__(self, queries, storage_factory):
        self.queries, self.storage_factory = queries, storage_factory

    async def prepare(self, actor_id, tenant_id, request_id, *, include_message_sources=False):
        tenant, (row, occurrences, contents) = await self.queries.body_facts(actor_id, tenant_id, request_id)
        storage = None
        if occurrences:
            try:
                storage = self.storage_factory()
                storage.keys.resolve(next(iter(contents.values())).key_version)
                first = contents[occurrences[0].content_id]
                reference = StoredAuditBlock(
                    **{
                        key: getattr(first, key)
                        for key in (
                            "object_key",
                            "key_version",
                            "digest",
                            "byte_length",
                            "scope_key",
                            "encoding_version",
                        )
                    }
                )
                await storage.open_verified_block(DshModelAuditWriteRepository.scope(row), reference)
            except Exception as error:
                logger.warning("DSH audit body key unavailable ({})", type(error).__name__)
                raise DshAuditOriginalUnavailableError() from None
        trace_id = str(uuid4())
        try:
            access_id = await self.queries.execute(
                tenant,
                lambda repository: repository.access_attempt(
                    actor_id=actor_id, request_id=request_id, trace_id=trace_id
                ),
            )
        except Exception as error:
            logger.warning("DSH audit body access log unavailable ({})", type(error).__name__)
            raise DshAuditAccessLogUnavailableError() from None
        return self.transfer(
            tenant, row, occurrences, contents, storage, access_id, include_message_sources=include_message_sources
        )

    async def annotations(self, row):
        state = getattr(row, "message_sources_status", "NOT_PROVIDED")
        if row.effective_mode != "CONTENT":
            state = "NOT_CAPTURED"
        reference = getattr(row, "message_sources_ref", None)
        if state not in {"AVAILABLE", "PARTIAL"} or not reference:
            return frame("annotations", message_sources_status=state, items=[])
        try:
            async with asyncio.timeout(1):
                body = await self.storage_factory().open_verified_block(
                    AuditScope(row.tenant_id, row.user_id, "REQUEST", row.request_id, 2), StoredAuditBlock(**reference)
                )
            if len(body) > 12288:
                raise ValueError("Annotation read budget exceeded")
            from bisheng.dsh.domain.schemas.model_audit_sources import normalize_message_sources

            sources, checked = normalize_message_sources(json.loads(body), max(0, row.input_units - 1))
            if sources is None or checked != state:
                raise ValueError("Annotation integrity invalid")
            return frame("annotations", message_sources_status=state, items=sources["items"])
        except Exception as error:
            # Optional provenance failure cannot block already authorized model originals.
            logger.warning("DSH audit annotation unavailable ({})", type(error).__name__)
            record_audit_metric("annotation_read_failed", tenant_id=row.tenant_id)
            return frame("annotations", message_sources_status="UNAVAILABLE", items=[])

    async def transfer(self, tenant, row, occurrences, contents, storage, access_id, *, include_message_sources=False):
        status, sequence = "INTERRUPTED", -1
        try:
            yield frame("meta", request_id=row.request_id, encoding_version=1, content_state=row.content_status)
            if include_message_sources:
                yield await self.annotations(row)
            current_unit, decoder = None, None
            next_stored = {"input": 0, "output": 0}
            for occurrence in occurrences:
                unit = (occurrence.channel, occurrence.unit_index)
                if unit != current_unit:
                    if decoder is not None:
                        tail = decoder.decode(b"", final=True)
                        if tail:
                            sequence += 1
                            yield frame(
                                "part", seq=sequence, channel=current_unit[0], unit_index=current_unit[1], fragment=tail
                            )
                    current_unit, decoder = unit, codecs.getincrementaldecoder("utf8")()
                if occurrence.sequence != next_stored[occurrence.channel]:
                    yield frame(
                        "gap",
                        channel=occurrence.channel,
                        unit_index=occurrence.unit_index,
                        stored_sequence=occurrence.sequence,
                    )
                    decoder = codecs.getincrementaldecoder("utf8")()
                next_stored[occurrence.channel] = occurrence.sequence + 1
                content = contents.get(occurrence.content_id)
                scope = DshModelAuditWriteRepository.scope(row)
                if content is None or (content.tenant_id, content.user_id, content.scope_type, content.scope_id) != (
                    row.tenant_id,
                    row.user_id,
                    scope.scope_type,
                    scope.scope_id,
                ):
                    raise ValueError("Audit content binding invalid")
                reference = StoredAuditBlock(
                    **{
                        key: getattr(content, key)
                        for key in (
                            "object_key",
                            "key_version",
                            "digest",
                            "byte_length",
                            "scope_key",
                            "encoding_version",
                        )
                    }
                )
                body = await storage.open_verified_block(scope, reference)
                if reference.digest != occurrence.digest:
                    raise ValueError("Audit occurrence integrity failed")
                fragment = decoder.decode(body)
                sequence += 1
                yield frame(
                    "part",
                    seq=sequence,
                    channel=occurrence.channel,
                    unit_index=occurrence.unit_index,
                    fragment=fragment,
                )
            if decoder is not None:
                tail = decoder.decode(b"", final=True)
                if tail:
                    sequence += 1
                    yield frame(
                        "part", seq=sequence, channel=current_unit[0], unit_index=current_unit[1], fragment=tail
                    )
            yield frame("end", last_seq=sequence, content_state=row.content_status, transfer_status="COMPLETED")
            status = "COMPLETED"
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as error:
            logger.warning("DSH audit original transfer failed ({})", type(error).__name__)
            status = "ERROR"
            yield frame("error", code="original_unavailable")
        finally:
            try:
                await asyncio.shield(
                    self.queries.execute(tenant, lambda repository: repository.finish_access(access_id, status))
                )
            except Exception as error:
                # The durable attempt already exists; completion telemetry is best effort.
                logger.warning("DSH audit transfer result unavailable ({})", type(error).__name__)
