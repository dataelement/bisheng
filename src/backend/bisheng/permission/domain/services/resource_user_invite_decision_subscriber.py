from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from copy import deepcopy

from sqlalchemy import select
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
from bisheng.permission.domain.models.resource_user_invite_request import (
    RESOURCE_USER_INVITE_REQUEST_TYPE,
    RESOURCE_USER_INVITE_SCENARIO_CODE,
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.ports.resource_user_invite_dispatcher import (
    ResourceUserInviteDispatcher,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ResourceUserInviteDecisionSubscriber:
    """Idempotently accept F045 terminal facts before dispatching execution."""

    scenario_code = RESOURCE_USER_INVITE_SCENARIO_CODE
    subscriber_key = RESOURCE_USER_INVITE_SCENARIO_CODE
    protocol_version = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version = APPROVAL_DECISION_EVENT_VERSION
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE

    _DISPATCH_PENDING = "pending"
    _DISPATCHED = "dispatched"
    _DISPATCH_NOT_REQUIRED = "not_required"
    _TERMINAL_DECISIONS = {"approved", "rejected", "withdrawn", "cancelled"}

    def __init__(
        self,
        *,
        dispatcher: ResourceUserInviteDispatcher,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self.dispatcher = dispatcher
        self.session_factory = session_factory

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        tenant_id, request_id = self._validate_event_envelope(event)
        should_dispatch = False

        async with self.session_factory() as session, session.begin():
            row = await self._load_for_update(
                session,
                tenant_id=tenant_id,
                request_id=request_id,
            )
            self._validate_binding(row, event)
            if row.decision_event_id is None:
                self._accept_first_event(row, event)
                session.add(row)
                await session.flush()
                should_dispatch = event.decision == "approved"
            else:
                should_dispatch = self._validate_repeated_event(row, event)

        if should_dispatch:
            await self._dispatch_and_mark(event=event, request_id=request_id)

    async def _dispatch_and_mark(self, *, event: ApprovalDecisionEvent, request_id: int) -> None:
        try:
            await self.dispatcher.dispatch(
                tenant_id=event.tenant_id,
                request_id=request_id,
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
                snapshot = deepcopy(row.result_snapshot or {})
                snapshot["dispatch_state"] = self._DISPATCHED
                row.result_snapshot = snapshot
                session.add(row)
                await session.flush()
        except ApprovalDecisionPermanentError:
            raise
        except Exception as error:
            raise ApprovalDecisionRetryableError("resource user invite dispatch acknowledgement failed") from error

    @classmethod
    def _accept_first_event(
        cls,
        row: ResourceUserInviteRequest,
        event: ApprovalDecisionEvent,
    ) -> None:
        if row.execution_state != ResourceUserInviteExecutionState.AWAITING_APPROVAL or row.active_marker != 0:
            raise ApprovalDecisionPermanentError("resource user invite is not awaiting approval")
        row.decision_event_id = event.event_id
        row.result_snapshot = {
            "accepted_decision": event.decision,
            "accepted_decision_version": event.decision_version,
            "accepted_event_id": event.event_id,
            "accepted_event_version": event.event_version,
            "dispatch_state": (cls._DISPATCH_PENDING if event.decision == "approved" else cls._DISPATCH_NOT_REQUIRED),
        }
        if event.decision == "approved":
            row.execution_state = ResourceUserInviteExecutionState.QUEUED
            return
        row.execution_state = ResourceUserInviteExecutionState.CLOSED
        row.active_marker = cls._required_row_id(row)

    @classmethod
    def _validate_repeated_event(
        cls,
        row: ResourceUserInviteRequest,
        event: ApprovalDecisionEvent,
    ) -> bool:
        cls._validate_recorded_event(row, event)
        snapshot = row.result_snapshot or {}
        if event.decision != "approved":
            return False
        dispatch_state = snapshot.get("dispatch_state")
        if dispatch_state == cls._DISPATCHED:
            return False
        if dispatch_state != cls._DISPATCH_PENDING:
            raise ApprovalDecisionPermanentError("resource user invite event dispatch state mismatch")
        if row.execution_state != ResourceUserInviteExecutionState.QUEUED:
            raise ApprovalDecisionPermanentError("resource user invite queued state mismatch")
        return True

    @staticmethod
    def _validate_recorded_event(
        row: ResourceUserInviteRequest,
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
            raise ApprovalDecisionPermanentError("resource user invite event is old or out of order")

    @classmethod
    def _validate_event_envelope(cls, event: ApprovalDecisionEvent) -> tuple[int, int]:
        if event.event_version != APPROVAL_DECISION_EVENT_VERSION:
            raise ApprovalDecisionPermanentError("resource user invite event version mismatch")
        if event.decision_version != 1:
            raise ApprovalDecisionPermanentError("resource user invite decision version mismatch")
        if event.scenario_code != cls.scenario_code:
            raise ApprovalDecisionPermanentError("resource user invite scenario binding mismatch")
        if event.business_request_type != RESOURCE_USER_INVITE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("resource user invite business type mismatch")
        if event.decision not in cls._TERMINAL_DECISIONS:
            raise ApprovalDecisionPermanentError("resource user invite decision is invalid")
        tenant_id = cls._require_tenant(event.tenant_id)
        request_id = cls._parse_request_id(event.business_request_id)
        return tenant_id, request_id

    @staticmethod
    def _validate_binding(
        row: ResourceUserInviteRequest,
        event: ApprovalDecisionEvent,
    ) -> None:
        if row.approval_instance_id is None or int(row.approval_instance_id) != int(event.approval_instance_id):
            raise ApprovalDecisionPermanentError("resource user invite approval instance mismatch")
        if row.business_key != event.business_key:
            raise ApprovalDecisionPermanentError("resource user invite business key mismatch")
        if row.request_fingerprint != event.request_fingerprint:
            raise ApprovalDecisionPermanentError("resource user invite request fingerprint mismatch")

    @staticmethod
    async def _load_for_update(
        session: AsyncSession,
        *,
        tenant_id: int,
        request_id: int,
    ) -> ResourceUserInviteRequest:
        statement = (
            select(ResourceUserInviteRequest)
            .where(
                ResourceUserInviteRequest.id == request_id,
                ResourceUserInviteRequest.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        result = await session.execute(statement)
        row = result.scalars().first()
        if row is None:
            raise ApprovalDecisionPermanentError("resource user invite business request does not exist")
        return row

    @staticmethod
    def _parse_request_id(value: str) -> int:
        try:
            request_id = int(value)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("resource user invite business request id is invalid") from error
        if request_id <= 0 or str(request_id) != str(value):
            raise ApprovalDecisionPermanentError("resource user invite business request id is invalid")
        return request_id

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        try:
            normalized_tenant_id = int(tenant_id)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("resource user invite tenant is invalid") from error
        current_tenant_id = get_current_tenant_id()
        if normalized_tenant_id <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized_tenant_id:
            raise ApprovalDecisionPermanentError("resource user invite requires the matching tenant context")
        return normalized_tenant_id

    @staticmethod
    def _required_row_id(row: ResourceUserInviteRequest) -> int:
        if row.id is None:
            raise ApprovalDecisionPermanentError("resource user invite request id is missing")
        return int(row.id)


__all__ = ["ResourceUserInviteDecisionSubscriber", "ResourceUserInviteDispatcher"]
