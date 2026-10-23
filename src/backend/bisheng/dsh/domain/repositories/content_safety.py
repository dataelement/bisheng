"""Tenant-scoped immutable safety facts; transaction and retry belong to the caller."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshContentSafetyConflictError, DshContentSafetyExpiredError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent


def _require_event_tenant(event: ContentSafetyEvent) -> int:
    tenant_id = get_current_tenant_id()
    if type(tenant_id) is not int or tenant_id < 1 or is_tenant_filter_bypassed() or tenant_id != int(event.tenant_id):
        raise DshContentSafetyConflictError()
    return tenant_id


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _event_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def lookup_receipt(session: Session, event: ContentSafetyEvent, payload_hash: str) -> DshContentSafetyEvent | None:
    """Find a stored fact, not an ACK; only a caller commit can confirm receipt."""
    _require_event_tenant(event)
    with strict_tenant_filter():
        row = session.exec(
            select(DshContentSafetyEvent).where(
                DshContentSafetyEvent.source_id == event.source_id,
                DshContentSafetyEvent.event_id == event.event_id.lower(),
            )
        ).one_or_none()
    if row is not None and row.payload_hash != payload_hash:
        raise DshContentSafetyConflictError()
    return row


def retention_guard(session: Session, event: ContentSafetyEvent) -> None:
    """Reject recreation below the tenant watermark, while retained valid rows live."""
    _require_event_tenant(event)
    setting = DshModelAuditSettingRepository(session).lock_retention()
    with strict_tenant_filter():
        if setting.audit_deleted_before is None:
            return
        if _event_time(event.request_started_at) >= _utc(setting.audit_deleted_before):
            return
        request_id = event.backend_request_id
        if request_id is None and not event.forwarded:
            request_id = event.gateway_request_id
        if request_id is not None:
            retained = session.exec(
                select(DshModelAuditRequest)
                .where(
                    DshModelAuditRequest.request_id == request_id.lower(),
                    DshModelAuditRequest.user_id == int(event.user_id),
                    DshModelAuditRequest.model_id == int(event.model_id),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).one_or_none()
            if retained is not None:
                return
    raise DshContentSafetyExpiredError()


def append_event(session: Session, event: ContentSafetyEvent, payload_hash: str) -> tuple[DshContentSafetyEvent, bool]:
    """Append within the caller's transaction and return the fact plus duplicate flag.

    Raw-wire hashing happens before DTO cleaning. Never recompute that digest from
    a model dump, which would conflate an omitted optional field with explicit null.
    A racing unique-key IntegrityError intentionally escapes: the transaction owner
    must exit the failed transaction and retry the full merge in a fresh session.
    """
    tenant_id = _require_event_tenant(event)
    previous = lookup_receipt(session, event, payload_hash)
    if previous is not None:
        return previous, True
    with strict_tenant_filter():
        same_version = session.exec(
            select(DshContentSafetyEvent).where(
                DshContentSafetyEvent.source_id == event.source_id,
                DshContentSafetyEvent.gateway_request_id == event.gateway_request_id.lower(),
                DshContentSafetyEvent.event_version == event.event_version,
            )
        ).one_or_none()
    if same_version is not None:
        if same_version.event_id != event.event_id.lower() or same_version.payload_hash != payload_hash:
            raise DshContentSafetyConflictError()
        return same_version, True
    retention_guard(session, event)
    row = DshContentSafetyEvent(
        tenant_id=tenant_id,
        source_id=event.source_id,
        event_id=event.event_id.lower(),
        gateway_request_id=event.gateway_request_id.lower(),
        backend_request_id=event.backend_request_id.lower() if event.backend_request_id else None,
        user_id=int(event.user_id),
        model_id=int(event.model_id),
        session_id=event.session_id.lower() if event.session_id else None,
        schema_version=event.schema_version,
        event_version=event.event_version,
        event_kind=event.event_kind,
        protocol=event.protocol,
        request_started_at=_event_time(event.request_started_at).replace(tzinfo=None),
        occurred_at=_event_time(event.occurred_at).replace(tzinfo=None),
        received_at=datetime.now(UTC).replace(tzinfo=None),
        payload_hash=payload_hash,
        stage_results=event.stage_results.model_dump(),
        stage_versions=event.stage_versions.model_dump(),
        policy_version=event.policy_version,
        builtin_digest=event.builtin_digest,
        hit_count=event.hit_count,
        hit_count_truncated=event.hit_count_truncated,
        rule_refs=list(event.rule_refs),
        forwarded=event.forwarded,
        drain_status=event.drain_status,
        conversation=event.conversation.model_dump(exclude_none=True) if event.conversation else None,
    )
    session.add(row)
    session.flush()
    return row, False
