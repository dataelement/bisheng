"""Commit immutable safety facts and their audit projection before acknowledging.

Coverage AC: AC-03, AC-35, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-58.
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session

from bisheng.common.errcode.dsh import (
    DshContentSafetyAuthError,
    DshContentSafetyExpiredError,
    DshContentSafetyInvalidEventError,
    DshContentSafetyTooLargeError,
    DshContentSafetyUnavailableError,
)
from bisheng.dsh.domain.repositories import content_safety, content_safety_projection
from bisheng.dsh.domain.repositories.model_audit_write import DshModelAuditWriteRepository
from bisheng.dsh.domain.schemas.content_safety import (
    MAX_EVENT_BYTES,
    MAX_JSON_DEPTH,
    ContentSafetyEvent,
    ContentSafetyReceipt,
)
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking


@dataclass(frozen=True)
class VerifiedSource:
    """Deployment-authenticated Gateway scope, supplied by the signature adapter."""

    source_id: str
    tenant_id: int


def _snapshot(value, *, depth=1):
    if depth > MAX_JSON_DEPTH:
        raise ValueError("Event nesting exceeds bounds")
    if isinstance(value, Mapping):
        if len(value) > MAX_EVENT_BYTES or any(type(key) is not str for key in value):
            raise ValueError("Invalid event object")
        return {key: _snapshot(item, depth=depth + 1) for key, item in value.items()}
    if type(value) is list:
        if len(value) > MAX_EVENT_BYTES:
            raise ValueError("Event array exceeds bounds")
        return [_snapshot(item, depth=depth + 1) for item in value]
    if value is None or type(value) in {str, bool, int}:
        return value
    # Signed JSON facts use exact integers; floats and runtime objects cannot
    # be laundered away by optional-hint cleaning or DTO defaults.
    raise ValueError("Invalid event JSON value")


def _validated(raw_event: Mapping) -> tuple[ContentSafetyEvent, str]:
    try:
        if not isinstance(raw_event, Mapping):
            raise ValueError("Expected an event object")
        snapshot = _snapshot(raw_event)
        canonical = json.dumps(
            snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf8")
        if len(canonical) > MAX_EVENT_BYTES:
            raise DshContentSafetyTooLargeError()
        # Hash before defaults and optional-hint cleaning. Timestamp spelling,
        # absent fields and explicit null remain distinct original facts.
        digest = sha256(canonical).hexdigest()
        return ContentSafetyEvent.model_validate(snapshot), digest
    except (ValidationError, ValueError, TypeError, UnicodeError, OverflowError):
        raise DshContentSafetyInvalidEventError() from None


class ContentSafetyIngestService:
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    async def ingest(self, raw_event: Mapping, verified_source: VerifiedSource) -> ContentSafetyReceipt:
        deadline = monotonic() + 2.0
        event, payload_hash = _validated(raw_event)
        if (
            not isinstance(verified_source, VerifiedSource)
            or type(verified_source.tenant_id) is not int
            or verified_source.tenant_id != int(event.tenant_id)
            or verified_source.source_id != event.source_id
        ):
            raise DshContentSafetyAuthError()
        try:
            # The same fixed budget includes bounded-executor queue waiting.
            # Cancellation stops observation, not a SQL call already in flight;
            # a lost commit confirmation is recovered by immutable-event retry.
            with profile_scope(verified_source.tenant_id):
                async with asyncio.timeout(max(0, deadline - monotonic())):
                    return await run_audit_blocking(
                        self._persist, event, payload_hash, verified_source.tenant_id, deadline
                    )
        except (SQLAlchemyError, RuntimeError, TimeoutError) as error:
            logger.warning("DSH content-safety ingestion unavailable ({})", type(error).__name__)
            raise DshContentSafetyUnavailableError() from None

    def _persist(self, event, payload_hash, tenant_id, deadline):
        merge_collisions = 0
        # A retry always leaves the failed transaction and closes its Session.
        # Never parse vendor SQL errors or query through a failed begin block.
        with profile_scope(tenant_id):
            for attempt in range(3):
                if monotonic() >= deadline:
                    raise TimeoutError("Safety ingestion deadline expired")
                phase = "append"
                try:
                    with self.session_factory() as session:
                        with session.begin():
                            fact, duplicate = content_safety.append_event(session, event, payload_hash)
                            can_merge = True
                            if duplicate:
                                try:
                                    content_safety.retention_guard(session, event)
                                except DshContentSafetyExpiredError:
                                    # The original committed receipt remains valid,
                                    # but replay must not recreate a purged main row.
                                    can_merge = False
                            phase = "merge"
                            if (
                                can_merge
                                and merge_collisions < 2
                                and (not merge_collisions or self._target_visible(session, event))
                            ):
                                content_safety_projection.merge_audit(session, event)
                            # A visible target does not prove the global safety
                            # binding is available: another tenant may own it.
                            # Two failed merges leave a final fresh transaction
                            # to persist only the still-unassociated immutable fact.
                            # Snapshot scalar receipt fields while the ORM is attached.
                            # Default runtime sessions may expire every attribute on commit.
                            receipt = {
                                "event_id": event.event_id,
                                "receipt": "COMMITTED",
                                "duplicate": duplicate,
                                "association_status": fact.association_status,
                                "audit_request_id": fact.audit_request_id,
                            }
                            if monotonic() >= deadline:
                                raise TimeoutError("Safety ingestion deadline expired")
                            phase = "commit"
                    # Only a successful exit from begin/Session can return COMMITTED.
                    return ContentSafetyReceipt(**receipt)
                except IntegrityError:
                    if phase == "commit" or attempt == 2:
                        raise
                    if phase == "merge":
                        merge_collisions += 1
        raise RuntimeError("Safety ingestion retries exhausted")

    @staticmethod
    def _target_visible(session, event):
        # A previous merge attempted this exact target. If strict rereading still
        # cannot see it, a global PK/association collision is not ours to inspect.
        # Preserve the fact without guessing an association or repeating INSERT.
        request_id = event.backend_request_id if event.forwarded else event.gateway_request_id
        if request_id is None:
            return False
        return DshModelAuditWriteRepository(session).request(request_id.lower(), lock=True) is not None
