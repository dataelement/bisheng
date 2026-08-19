from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
    ApprovalDecisionPermanentError,
    ApprovalDecisionRetryableError,
)
from bisheng.approval.domain.ports.scenario_policy import DECISION_DELIVERY_COMPLETION_MODE
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_terminal_cleanup_service import (
    KnowledgeSpaceFileChangeTerminalCleanupService,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeSpaceFileChangeDispatcher(Protocol):
    async def dispatch(self, *, tenant_id: int, request_id: int) -> None: ...


class KnowledgeSpaceFileChangeTerminalCleanup(Protocol):
    async def cleanup(
        self,
        *,
        tenant_id: int,
        request_id: int,
        upload_id: str,
        terminal_action: str,
        reason: str | None,
    ) -> object: ...


class KnowledgeSpaceFileChangeDecisionSubscriber:
    """Accept terminal facts and advance only the Knowledge-owned request."""

    scenario_code = KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE
    subscriber_key = KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE
    protocol_version = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version = APPROVAL_DECISION_EVENT_VERSION
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE

    _DISPATCH_PENDING = "pending"
    _DISPATCHED = "dispatched"
    _DISPATCH_NOT_REQUIRED = "not_required"
    _CLEANUP_PENDING = "pending"
    _CLEANUP_SUCCEEDED = "success"
    _CLEANUP_NOT_REQUIRED = "not_required"
    _TERMINAL_DECISIONS = {"approved", "rejected", "withdrawn", "cancelled"}

    def __init__(
        self,
        *,
        dispatcher: KnowledgeSpaceFileChangeDispatcher,
        terminal_cleanup: KnowledgeSpaceFileChangeTerminalCleanup | None = None,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self.dispatcher = dispatcher
        self.terminal_cleanup = terminal_cleanup or KnowledgeSpaceFileChangeTerminalCleanupService()
        self.session_factory = session_factory

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        tenant_id, request_id = self._validate_event_envelope(event)
        try:
            async with self.session_factory() as session, session.begin():
                row = await self._load_for_update(
                    session,
                    tenant_id=tenant_id,
                    request_id=request_id,
                )
                self._validate_binding(row, event)
                if row.decision_event_id is None:
                    should_dispatch, should_cleanup = self._accept_first_event(row, event)
                else:
                    should_dispatch, should_cleanup = self._accept_repeated_event(row, event)
                session.add(row)
                await session.flush()
        except (ApprovalDecisionPermanentError, IntegrityError) as error:
            if isinstance(error, IntegrityError):
                raise ApprovalDecisionPermanentError("file change event conflicts with another request") from error
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("file change decision persistence failed") from error

        if should_dispatch:
            await self._dispatch_and_mark(event=event, request_id=request_id)
        if should_cleanup:
            await self._cleanup_and_mark(event=event, request_id=request_id)

    async def _dispatch_and_mark(self, *, event: ApprovalDecisionEvent, request_id: int) -> None:
        try:
            await self.dispatcher.dispatch(tenant_id=event.tenant_id, request_id=request_id)
        except (ApprovalDecisionPermanentError, ApprovalDecisionRetryableError):
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError(str(error) or type(error).__name__) from error

        try:
            async with self.session_factory() as session, session.begin():
                row = await self._load_for_update(
                    session,
                    tenant_id=event.tenant_id,
                    request_id=request_id,
                )
                self._validate_binding(row, event)
                self._validate_recorded_event(row, event)
                if row.execution_state != KnowledgeSpaceFileChangeExecutionState.QUEUED:
                    raise ApprovalDecisionPermanentError("file change queued state mismatch")
                snapshot = deepcopy(row.result_snapshot or {})
                snapshot["dispatch_state"] = self._DISPATCHED
                row.result_snapshot = snapshot
                session.add(row)
                await session.flush()
        except ApprovalDecisionPermanentError:
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("file change dispatch acknowledgement failed") from error

    async def _cleanup_and_mark(self, *, event: ApprovalDecisionEvent, request_id: int) -> None:
        upload_id = await self._load_cleanup_binding(event=event, request_id=request_id)
        try:
            await self.terminal_cleanup.cleanup(
                tenant_id=event.tenant_id,
                request_id=request_id,
                upload_id=upload_id,
                terminal_action=event.decision,
                reason=None,
            )
        except (ApprovalDecisionPermanentError, ApprovalDecisionRetryableError):
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError(str(error) or type(error).__name__) from error

        try:
            async with self.session_factory() as session, session.begin():
                row = await self._load_for_update(
                    session,
                    tenant_id=event.tenant_id,
                    request_id=request_id,
                )
                self._validate_binding(row, event)
                self._validate_recorded_event(row, event)
                if row.cleanup_state != KnowledgeSpaceFileChangeCleanupState.SUCCESS:
                    raise ApprovalDecisionRetryableError("file change cleanup did not persist success")
                snapshot = deepcopy(row.result_snapshot or {})
                snapshot["cleanup_state"] = self._CLEANUP_SUCCEEDED
                row.result_snapshot = snapshot
                session.add(row)
                await session.flush()
        except (ApprovalDecisionPermanentError, ApprovalDecisionRetryableError):
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("file change cleanup acknowledgement failed") from error

    async def _load_cleanup_binding(self, *, event: ApprovalDecisionEvent, request_id: int) -> str:
        try:
            async with self.session_factory() as session, session.begin():
                row = await self._load_for_update(
                    session,
                    tenant_id=event.tenant_id,
                    request_id=request_id,
                )
                self._validate_binding(row, event)
                self._validate_recorded_event(row, event)
                upload_id = (row.action_snapshot or {}).get("upload_id")
                if not upload_id:
                    raise ApprovalDecisionPermanentError("file change upload cleanup binding is missing")
                return str(upload_id)
        except ApprovalDecisionPermanentError:
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("file change cleanup binding load failed") from error

    @classmethod
    def _accept_first_event(
        cls,
        row: KnowledgeSpaceFileChangeRequest,
        event: ApprovalDecisionEvent,
    ) -> tuple[bool, bool]:
        if row.execution_state != KnowledgeSpaceFileChangeExecutionState.NOT_STARTED:
            raise ApprovalDecisionPermanentError("file change request is not awaiting approval")
        if row.cleanup_state != KnowledgeSpaceFileChangeCleanupState.NONE:
            raise ApprovalDecisionPermanentError("file change cleanup state is invalid before decision")
        requires_cleanup = event.decision != "approved" and cls._requires_cleanup(row)
        row.decision_event_id = event.event_id
        row.result_snapshot = {
            "accepted_decision": event.decision,
            "accepted_decision_version": event.decision_version,
            "accepted_event_id": event.event_id,
            "accepted_event_version": event.event_version,
            "cleanup_state": (cls._CLEANUP_PENDING if requires_cleanup else cls._CLEANUP_NOT_REQUIRED),
            "dispatch_state": (cls._DISPATCH_PENDING if event.decision == "approved" else cls._DISPATCH_NOT_REQUIRED),
        }
        if event.decision == "approved":
            row.execution_state = KnowledgeSpaceFileChangeExecutionState.QUEUED
            return True, False
        row.execution_state = KnowledgeSpaceFileChangeExecutionState.CLOSED
        return False, requires_cleanup

    @classmethod
    def _accept_repeated_event(
        cls,
        row: KnowledgeSpaceFileChangeRequest,
        event: ApprovalDecisionEvent,
    ) -> tuple[bool, bool]:
        cls._validate_recorded_event(row, event)
        snapshot = deepcopy(row.result_snapshot or {})
        if event.decision == "approved":
            dispatch_state = snapshot.get("dispatch_state")
            if dispatch_state == cls._DISPATCHED:
                return False, False
            if dispatch_state != cls._DISPATCH_PENDING:
                raise ApprovalDecisionPermanentError("file change event dispatch state mismatch")
            if row.execution_state != KnowledgeSpaceFileChangeExecutionState.QUEUED:
                raise ApprovalDecisionPermanentError("file change queued state mismatch")
            return True, False

        if row.execution_state != KnowledgeSpaceFileChangeExecutionState.CLOSED:
            raise ApprovalDecisionPermanentError("file change closed state mismatch")
        if not cls._requires_cleanup(row):
            if snapshot.get("cleanup_state") != cls._CLEANUP_NOT_REQUIRED:
                raise ApprovalDecisionPermanentError("file change event cleanup state mismatch")
            return False, False
        if row.cleanup_state == KnowledgeSpaceFileChangeCleanupState.SUCCESS:
            snapshot["cleanup_state"] = cls._CLEANUP_SUCCEEDED
            row.result_snapshot = snapshot
            return False, False
        if snapshot.get("cleanup_state") != cls._CLEANUP_PENDING:
            raise ApprovalDecisionPermanentError("file change event cleanup state mismatch")
        return False, True

    @staticmethod
    def _validate_recorded_event(
        row: KnowledgeSpaceFileChangeRequest,
        event: ApprovalDecisionEvent,
    ) -> None:
        snapshot = row.result_snapshot or {}
        if (
            int(row.decision_event_id or 0) != int(event.event_id)
            or snapshot.get("accepted_event_id") != event.event_id
            or snapshot.get("accepted_event_version") != event.event_version
            or snapshot.get("accepted_decision_version") != event.decision_version
            or snapshot.get("accepted_decision") != event.decision
        ):
            raise ApprovalDecisionPermanentError("file change event is old or out of order")

    @classmethod
    def _validate_event_envelope(cls, event: ApprovalDecisionEvent) -> tuple[int, int]:
        if event.event_version != APPROVAL_DECISION_EVENT_VERSION:
            raise ApprovalDecisionPermanentError("file change event version mismatch")
        if event.decision_version != 1:
            raise ApprovalDecisionPermanentError("file change decision version mismatch")
        if event.scenario_code != cls.scenario_code:
            raise ApprovalDecisionPermanentError("file change scenario binding mismatch")
        if event.business_request_type != KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("file change business type mismatch")
        if not event.business_key:
            raise ApprovalDecisionPermanentError("file change business key is required")
        if not event.request_fingerprint:
            raise ApprovalDecisionPermanentError("file change request fingerprint is required")
        if event.decision not in cls._TERMINAL_DECISIONS:
            raise ApprovalDecisionPermanentError("file change decision is invalid")
        if int(event.event_id) <= 0:
            raise ApprovalDecisionPermanentError("file change event id is invalid")
        tenant_id = cls._require_tenant(event.tenant_id)
        request_id = cls._parse_request_id(event.business_request_id)
        return tenant_id, request_id

    @staticmethod
    def _validate_binding(
        row: KnowledgeSpaceFileChangeRequest,
        event: ApprovalDecisionEvent,
    ) -> None:
        if row.approval_instance_id is None or int(row.approval_instance_id) != int(event.approval_instance_id):
            raise ApprovalDecisionPermanentError("file change approval instance mismatch")
        if not row.business_key or row.business_key != event.business_key:
            raise ApprovalDecisionPermanentError("file change business key mismatch")
        if not row.request_fingerprint or row.request_fingerprint != event.request_fingerprint:
            raise ApprovalDecisionPermanentError("file change request fingerprint mismatch")

    @staticmethod
    async def _load_for_update(
        session: AsyncSession,
        *,
        tenant_id: int,
        request_id: int,
    ) -> KnowledgeSpaceFileChangeRequest:
        statement = (
            select(KnowledgeSpaceFileChangeRequest)
            .where(
                KnowledgeSpaceFileChangeRequest.id == request_id,
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        result = await session.execute(statement)
        row = result.scalars().first()
        if row is None:
            raise ApprovalDecisionPermanentError("file change business request does not exist")
        return row

    @classmethod
    def _parse_request_id(cls, value: str) -> int:
        try:
            request_id = int(value)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("file change business request id is invalid") from error
        if request_id <= 0 or str(request_id) != str(value):
            raise ApprovalDecisionPermanentError("file change business request id is invalid")
        return request_id

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        try:
            normalized = int(tenant_id)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("file change tenant is invalid") from error
        current_tenant_id = get_current_tenant_id()
        if normalized <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized:
            raise ApprovalDecisionPermanentError("file change requires the matching tenant context")
        return normalized

    @staticmethod
    def _requires_cleanup(row: KnowledgeSpaceFileChangeRequest) -> bool:
        return row.action == KnowledgeSpaceFileChangeAction.UPLOAD


__all__ = [
    "KnowledgeSpaceFileChangeDecisionSubscriber",
    "KnowledgeSpaceFileChangeDispatcher",
    "KnowledgeSpaceFileChangeTerminalCleanup",
]
