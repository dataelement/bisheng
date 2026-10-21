"""Derive completeness from independent expectations and verified object references."""

from bisheng.dsh.domain.schemas.model_audit_events import ChannelExpectation
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage


def verify_content(row, manifest, occurrences, contents):
    if row.effective_mode != "CONTENT":
        return "NOT_CAPTURED"
    if row.capture_failed:
        return "PARTIAL"
    if manifest is None:
        return "PENDING"
    if (
        not manifest.input_complete
        or manifest.capture_failed
        or manifest.model_result not in {"SUCCEEDED", "FAILED", "CANCELLED"}
    ):
        return "PARTIAL"
    scope_type = "CONVERSATION" if row.conversation_id is not None else "REQUEST"
    scope_id = row.conversation_id if row.conversation_id is not None else row.request_id
    scope = AuditScope(row.tenant_id, row.user_id, scope_type, scope_id)
    for channel in ("input", "output"):
        expected = manifest.channels.get(channel)
        if not isinstance(expected, dict):
            return "PARTIAL"
        counter = ChannelExpectation()
        for occurrence in (item for item in occurrences if item.channel == channel):
            content = contents.get(occurrence.content_id)
            if occurrence.sequence != counter.count or content is None or content.write_status != "READY":
                return "PARTIAL"
            if (
                content.scope_key != scope.key
                or content.encoding_version != scope.encoding_version
                or content.digest != occurrence.digest
                or content.object_key != EncryptedAuditStorage._name(scope, content.key_version, content.digest)
            ):
                return "PARTIAL"
            if (content.tenant_id, content.user_id, content.scope_type, content.scope_id, content.byte_length) != (
                row.tenant_id,
                row.user_id,
                scope_type,
                scope_id,
                occurrence.byte_length,
            ):
                return "PARTIAL"
            counter.observe_digest(occurrence.byte_length, occurrence.digest)
        if counter.snapshot() != expected:
            return "PARTIAL"
    return "COMPLETE"
