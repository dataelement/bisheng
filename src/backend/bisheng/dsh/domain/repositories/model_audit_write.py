"""Tenant-scoped, idempotent audit facts. Caller owns the transaction."""

from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from sqlmodel import select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.model_audit_content import DshModelAuditContent, DshModelAuditOccurrence
from bisheng.dsh.domain.models.model_audit_request import (
    DshModelAuditEvidence,
    DshModelAuditManifest,
    DshModelAuditRequest,
)
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.content_safety_queries import naive_utc
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope, conversation_key


class DshModelAuditWriteRepository:
    def __init__(self, session):
        self.session = session

    def one(self, model, *conditions, lock=False):
        require_tenant()
        statement = select(model).where(*conditions)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            return self.session.exec(statement).one_or_none()

    def request(self, request_id, *, lock=False):
        return self.one(DshModelAuditRequest, DshModelAuditRequest.request_id == request_id, lock=lock)

    def upsert_request(self, event):
        if event.tenant_id != require_tenant():
            raise ValueError("Conflicting audit identity")
        data = event.metadata
        setting = DshModelAuditSettingRepository(self.session).lock_retention()
        row = self.request(event.request_id, lock=True)
        identity = (
            "user_id",
            "session_id",
            "model_id",
            "conversation_id",
            "effective_mode",
            "request_kind",
            "session_origin",
            "parent_conversation_id",
        )
        if row:
            if row.record_origin == "EXTERNAL_SAFETY":
                return self._promote_external(row, event, identity)
            if any(getattr(row, key) != data.get(key) for key in identity):
                raise ValueError("Conflicting audit identity")
            return row
        if setting.audit_deleted_before is not None and naive_utc(data["started_at"]) < naive_utc(
            setting.audit_deleted_before
        ):
            raise ValueError("Audit request is below retention watermark")
        conversation = data.get("conversation_id")
        row = DshModelAuditRequest(
            request_id=event.request_id,
            model_entered=True,
            model_started_at=data["started_at"],
            user_id=data["user_id"],
            session_id=data["session_id"],
            model_id=data["model_id"],
            model_name=data.get("model_name", ""),
            model_name_digest=sha256(data.get("model_name", "").encode("utf8")).hexdigest(),
            provider_name=data.get("provider_name", ""),
            conversation_id=conversation,
            conversation_key=conversation_key(event.tenant_id, data["user_id"], conversation) if conversation else None,
            conversation_id_digest=sha256(conversation.encode("utf8")).hexdigest()
            if conversation is not None
            else None,
            request_kind=data.get("request_kind"),
            session_origin=data.get("session_origin"),
            parent_conversation_id=data.get("parent_conversation_id"),
            message_sources_status=data.get("message_sources_status", "NOT_PROVIDED"),
            association_status="ASSOCIATED" if conversation is not None else "UNASSOCIATED",
            context_invalid=data.get("context_invalid", False),
            effective_mode=data["effective_mode"],
            content_status="PENDING" if data["effective_mode"] == "CONTENT" else "NOT_CAPTURED",
            input_units=data.get("input_units", 0),
            started_at=data["started_at"],
            last_write_at=event.observed_at,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _promote_external(self, row, event, identity):
        """Confirm native facts atomically, leaving the safety-owned columns intact.

        Coverage AC: AC-03, AC-32, AC-38, AC-41, AC-47, AC-49, AC-52.
        NULL optional identities are unknown only while the origin is external;
        an existing MODEL row keeps the original strict identity comparison.
        """
        data = event.metadata
        if (row.tenant_id, row.user_id, row.model_id) != (event.tenant_id, data["user_id"], data["model_id"]):
            raise ValueError("Conflicting audit identity")
        mode = data["effective_mode"]
        if mode not in {"METADATA", "CONTENT"}:
            raise ValueError("Conflicting audit identity")
        optional = tuple(key for key in identity if key not in {"user_id", "model_id", "effective_mode"})
        if any(getattr(row, key) is not None and getattr(row, key) != data.get(key) for key in optional):
            raise ValueError("Conflicting audit identity")
        for key in optional:
            if getattr(row, key) is None:
                setattr(row, key, data.get(key))
        row.record_origin, row.effective_mode = "MODEL", mode
        row.model_entered = True
        if row.model_started_at is None:
            row.model_started_at = data["started_at"]
        row.model_name = data.get("model_name", "")
        row.model_name_digest = sha256(row.model_name.encode("utf8")).hexdigest()
        row.provider_name = data.get("provider_name", "")
        row.conversation_key = (
            conversation_key(row.tenant_id, row.user_id, row.conversation_id) if row.conversation_id else None
        )
        row.conversation_id_digest = (
            sha256(row.conversation_id.encode("utf8")).hexdigest() if row.conversation_id is not None else None
        )
        row.association_status = "ASSOCIATED" if row.conversation_id is not None else "UNASSOCIATED"
        row.context_invalid = data.get("context_invalid", False)
        row.message_sources_status = data.get("message_sources_status", "NOT_PROVIDED")
        for key, initial in (
            ("model_result", "RUNNING"),
            ("response_result", "RUNNING"),
            ("usage_settlement", "PENDING"),
        ):
            if getattr(row, key) is None:
                setattr(row, key, initial)
        row.content_status = "PENDING" if mode == "CONTENT" else "NOT_CAPTURED"
        row.input_units = data.get("input_units", 0)
        row.group_index_pending = bool(row.conversation_key)
        self.session.add(row)
        # One flush checks origin and mode together; the caller commits this
        # promotion with its body/terminal/control facts or rolls all of it back.
        self.session.flush()
        return row

    def save_annotation(self, row, event, reference):
        expected = AuditScope(row.tenant_id, row.user_id, "REQUEST", row.request_id, 2)
        if row.effective_mode != "CONTENT" or reference.scope_key != expected.key or reference.encoding_version != 2:
            raise ValueError("Foreign audit annotation")
        value = asdict(reference)
        if row.message_sources_ref is not None and row.message_sources_ref != value:
            row.message_sources_status = "INVALID"
            return
        if row.message_sources_status == "INVALID":
            return
        row.message_sources_ref = value
        row.message_sources_status = event.metadata["sources_result"]

    @staticmethod
    def scope(row):
        return AuditScope(
            row.tenant_id,
            row.user_id,
            "CONVERSATION" if row.conversation_id is not None else "REQUEST",
            row.conversation_id if row.conversation_id is not None else row.request_id,
        )

    def append_occurrence(self, row, event, reference):
        scope = self.scope(row)
        if reference.scope_key != scope.key or reference.encoding_version != scope.encoding_version:
            raise ValueError("Foreign audit reference")
        digest = reference.digest
        existing = self.one(
            DshModelAuditOccurrence,
            DshModelAuditOccurrence.request_id == row.request_id,
            DshModelAuditOccurrence.stage == "MODEL",
            DshModelAuditOccurrence.channel == event.channel,
            DshModelAuditOccurrence.sequence == event.sequence,
        )
        if existing:
            if (existing.digest, existing.byte_length, existing.unit_index) != (
                digest,
                len(event.body),
                event.unit_index,
            ):
                row.capture_failed = True
            return False
        content = self.one(
            DshModelAuditContent,
            DshModelAuditContent.scope_key == reference.scope_key,
            DshModelAuditContent.encoding_version == reference.encoding_version,
            DshModelAuditContent.key_version == reference.key_version,
            DshModelAuditContent.digest == reference.digest,
        )
        if content is None:
            content = DshModelAuditContent(
                content_id=str(uuid4()),
                user_id=row.user_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                **{
                    key: getattr(reference, key)
                    for key in ("scope_key", "encoding_version", "key_version", "digest", "byte_length", "object_key")
                },
            )
            self.session.add(content)
            self.session.flush()
        elif content.byte_length != reference.byte_length or content.object_key != reference.object_key:
            raise ValueError("Conflicting audit content")
        occurrence = DshModelAuditOccurrence(
            request_id=row.request_id,
            channel=event.channel,
            sequence=event.sequence,
            unit_index=event.unit_index,
            byte_length=len(event.body),
            digest=digest,
            content_id=content.content_id,
        )
        self.session.add(occurrence)
        self.session.flush()
        if event.channel == "input":
            row.input_bytes += len(event.body)
        else:
            row.output_bytes += len(event.body)
        return True

    def save_manifest(self, row, event):
        data = event.metadata
        existing = self.one(DshModelAuditManifest, DshModelAuditManifest.request_id == row.request_id)
        facts = {key: data[key] for key in ("input_complete", "capture_failed", "model_result", "channels")}
        if existing:
            if any(getattr(existing, key) != value for key, value in facts.items()):
                row.capture_failed = True
            return existing
        manifest = DshModelAuditManifest(request_id=row.request_id, observed_at=event.observed_at, **facts)
        self.session.add(manifest)
        self.session.flush()
        return manifest

    def manifest(self, request_id):
        return self.one(DshModelAuditManifest, DshModelAuditManifest.request_id == request_id)

    def facts(self, request_id):
        with strict_tenant_filter():
            occurrences = self.session.exec(
                select(DshModelAuditOccurrence)
                .where(DshModelAuditOccurrence.request_id == request_id)
                .order_by(DshModelAuditOccurrence.channel, DshModelAuditOccurrence.sequence)
            ).all()
            contents = self.session.exec(
                select(DshModelAuditContent)
                .join(DshModelAuditOccurrence, DshModelAuditOccurrence.content_id == DshModelAuditContent.content_id)
                .where(DshModelAuditOccurrence.request_id == request_id)
            ).all()
        manifest = self.one(DshModelAuditManifest, DshModelAuditManifest.request_id == request_id)
        return manifest, occurrences, {item.content_id: item for item in contents}

    def evidence(self, event):
        kind = event.metadata["event_type"]
        existing = self.one(
            DshModelAuditEvidence,
            DshModelAuditEvidence.request_id == event.request_id,
            DshModelAuditEvidence.event_type == kind,
        )
        if existing is None:
            self.session.add(
                DshModelAuditEvidence(
                    request_id=event.request_id,
                    event_type=kind,
                    user_id=event.metadata.get("user_id") if kind == "MODEL_ENTERED" else None,
                    effective_mode=event.metadata.get("effective_mode") if kind == "MODEL_ENTERED" else None,
                    reason=event.metadata.get("reason"),
                    observed_at=event.observed_at,
                )
            )
