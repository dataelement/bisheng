"""Project durable safety facts without manufacturing model execution or usage.

The caller owns the transaction, commit and complete retry after a unique-key
race. All association and summary writes remain in that transaction.
"""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import update
from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshContentSafetyConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.content_safety_event import DshContentSafetyEvent
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from bisheng.dsh.domain.repositories.content_safety import _event_time, _require_event_tenant, _utc
from bisheng.dsh.domain.schemas.content_safety import ContentSafetyEvent
from bisheng.dsh.domain.services.content_safety_states import reduce_safety
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key


def _one(session, model, *conditions):
    with strict_tenant_filter():
        return session.exec(
            select(model).where(*conditions).with_for_update().execution_options(populate_existing=True)
        ).one_or_none()


def _saved_fact(session: Session, event: ContentSafetyEvent) -> DshContentSafetyEvent:
    fact = _one(
        session,
        DshContentSafetyEvent,
        DshContentSafetyEvent.source_id == event.source_id,
        DshContentSafetyEvent.event_id == event.event_id.lower(),
    )
    if fact is None:
        raise DshContentSafetyConflictError()
    # Compare cleaned semantics, not a new hash: omitted/null wire distinctions
    # were already validated by append_event using the original payload digest.
    for name in ContentSafetyEvent.model_fields:
        incoming, stored = getattr(event, name), getattr(fact, name)
        if name in {"tenant_id", "user_id", "model_id"}:
            incoming = int(incoming)
        elif name in {"event_id", "gateway_request_id", "backend_request_id", "session_id"}:
            incoming = incoming.lower() if incoming else None
        elif name in {"request_started_at", "occurred_at"}:
            incoming, stored = _event_time(incoming), _utc(stored)
        elif name in {"stage_results", "stage_versions", "conversation"}:
            incoming = incoming.model_dump(exclude_none=True) if incoming is not None else None
        elif name == "rule_refs":
            incoming = list(incoming)
        if incoming != stored:
            raise DshContentSafetyConflictError()
    return fact


def _request_id(event: ContentSafetyEvent) -> str | None:
    if not event.forwarded:
        return event.gateway_request_id.lower() if event.stage_results.input == "BLOCKED" else None
    return event.backend_request_id.lower() if event.backend_request_id else None


def _external(fact: DshContentSafetyEvent, request_id: str) -> DshModelAuditRequest:
    hints = fact.conversation or {}
    conversation_id = hints.get("conversation_id")
    return DshModelAuditRequest(
        request_id=request_id,
        tenant_id=fact.tenant_id,
        user_id=fact.user_id,
        model_id=fact.model_id,
        session_id=fact.session_id,
        record_origin="EXTERNAL_SAFETY",
        model_entered=False if not fact.forwarded else None,
        effective_mode=None,
        model_result=None,
        response_result=None,
        usage_settlement=None,
        content_status="NOT_CAPTURED",
        audit_status="NOT_APPLICABLE",
        model_name="",
        model_name_digest=sha256(b"").hexdigest(),
        started_at=fact.request_started_at,
        safety_source_id=fact.source_id,
        safety_gateway_request_id=fact.gateway_request_id,
        conversation_id=conversation_id,
        conversation_id_digest=sha256(conversation_id.encode("utf8")).hexdigest() if conversation_id else None,
        conversation_key=conversation_key(fact.tenant_id, fact.user_id, conversation_id) if conversation_id else None,
        request_kind=hints.get("request_kind"),
        session_origin=hints.get("session_origin"),
        parent_conversation_id=hints.get("parent_conversation_id"),
        association_status="ASSOCIATED" if conversation_id else "UNASSOCIATED",
    )


def _can_associate(row: DshModelAuditRequest, fact: DshContentSafetyEvent) -> bool:
    if (row.tenant_id, row.user_id, row.model_id) != (fact.tenant_id, fact.user_id, fact.model_id):
        return False
    binding = row.safety_source_id, row.safety_gateway_request_id
    return binding in {(None, None), (fact.source_id, fact.gateway_request_id)}


def _associate_fact(session: Session, fact: DshContentSafetyEvent, request_id: str) -> None:
    if fact.audit_request_id == request_id and fact.association_status == "ASSOCIATED":
        return
    if fact.audit_request_id is not None and fact.audit_request_id != request_id:
        raise DshContentSafetyConflictError()
    result = session.execute(
        update(DshContentSafetyEvent)
        .where(
            DshContentSafetyEvent.tenant_id == fact.tenant_id,
            DshContentSafetyEvent.id == fact.id,
            DshContentSafetyEvent.event_version == fact.event_version,
        )
        .values(audit_request_id=request_id, association_status="ASSOCIATED")
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise DshContentSafetyConflictError()
    set_committed_value(fact, "audit_request_id", request_id)
    set_committed_value(fact, "association_status", "ASSOCIATED")


def _merge_summary(session: Session, row: DshModelAuditRequest, event: ContentSafetyEvent) -> None:
    previous = {key: getattr(row, key) for key in reduce_safety(None, None)}
    reduced = reduce_safety(previous, event)
    changes = {key: value for key, value in reduced.items() if previous[key] != value}
    binding = {"safety_source_id": event.source_id, "safety_gateway_request_id": event.gateway_request_id.lower()}
    changes.update({key: value for key, value in binding.items() if getattr(row, key) != value})
    # A delayed snapshot may add a historical hit, but cannot roll back the
    # policy annotation of a later observed stage.
    if event.event_version >= max(row.input_safety_version, row.output_safety_version):
        policy = {"policy_version": event.policy_version, "builtin_digest": event.builtin_digest}
        changes.update({key: value for key, value in policy.items() if getattr(row, key) != value})
    if not changes:
        return
    version = row.safety_projection_version
    changes.update(
        safety_projection_version=version + 1,
        content_safety_updated_at=datetime.now(UTC).replace(tzinfo=None),
        group_index_pending=bool(row.conversation_key),
    )
    result = session.execute(
        update(DshModelAuditRequest)
        .where(
            DshModelAuditRequest.tenant_id == row.tenant_id,
            DshModelAuditRequest.request_id == row.request_id,
            DshModelAuditRequest.safety_projection_version == version,
        )
        .values(**changes)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise DshContentSafetyConflictError()
    session.expire(row)


def merge_audit(session: Session, event: ContentSafetyEvent) -> DshModelAuditRequest | None:
    """Merge a saved fact; None preserves an unconfirmed association as event-only.

    Coverage AC: AC-27, AC-32, AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-44, AC-48.
    No commit, rollback or failed-transaction re-read occurs at this boundary.
    """
    _require_event_tenant(event)
    fact = _saved_fact(session, event)
    request_id = _request_id(event)
    if request_id is None:
        return None
    row = _one(session, DshModelAuditRequest, DshModelAuditRequest.request_id == request_id)
    if row is not None and not _can_associate(row, fact):
        return None
    prior = _one(
        session,
        DshModelAuditRequest,
        DshModelAuditRequest.safety_source_id == fact.source_id,
        DshModelAuditRequest.safety_gateway_request_id == fact.gateway_request_id,
    )
    if prior is not None and prior.request_id != request_id:
        # A changed trusted identity/request fact survives without rewriting
        # the historical row already owning the unique safety association.
        return None
    if row is None:
        row = _external(fact, request_id)
        session.add(row)
        session.flush()
    _merge_summary(session, row, event)
    _associate_fact(session, fact, request_id)
    session.flush()
    return _one(session, DshModelAuditRequest, DshModelAuditRequest.request_id == request_id)
