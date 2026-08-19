from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.approval.domain.ports.approval_status_reader import (
    ApprovalStatusReadPort,
    ApprovalStatusSnapshot,
)
from bisheng.approval.domain.ports.scenario_policy import (
    ApprovalApplicant,
    ApprovalPostCommitCallback,
    ApprovalSubmissionCommand,
    ApprovalSubmissionPort,
)
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
from bisheng.permission.domain.repositories.resource_user_invite_request_repository import (
    ResourceUserInviteRequestRepository,
)
from bisheng.permission.domain.schemas.resource_authorization_schema import (
    ResourceUserInvitePendingItem,
    ResourceUserInviteRetryResult,
)
from bisheng.permission.domain.services.resource_user_invite_lock import (
    build_resource_user_invite_business_key,
    resource_user_invite_lock,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
SubmissionPortFactory = Callable[[], ApprovalSubmissionPort[AsyncSession]]
ApprovalStatusPortFactory = Callable[[], ApprovalStatusReadPort]
DispatcherFactory = Callable[[], ResourceUserInviteDispatcher]

_submission_port_factory: SubmissionPortFactory | None = None
_approval_status_port_factory: ApprovalStatusPortFactory | None = None
_dispatcher_factory: DispatcherFactory | None = None


def configure_resource_user_invite_submission_port_factory(
    factory: SubmissionPortFactory,
) -> None:
    global _submission_port_factory
    _submission_port_factory = factory


def configure_resource_user_invite_query_and_retry_factories(
    *,
    approval_status_port_factory: ApprovalStatusPortFactory,
    dispatcher_factory: DispatcherFactory,
) -> None:
    global _approval_status_port_factory, _dispatcher_factory
    _approval_status_port_factory = approval_status_port_factory
    _dispatcher_factory = dispatcher_factory


def build_runtime_resource_user_invite_application_service() -> ResourceUserInviteApplicationService:
    if _submission_port_factory is None:
        raise RuntimeError("resource user invite submission port is not configured")
    return ResourceUserInviteApplicationService(
        submission_port=_submission_port_factory(),
        approval_status_port=(_approval_status_port_factory() if _approval_status_port_factory is not None else None),
        dispatcher=_dispatcher_factory() if _dispatcher_factory is not None else None,
    )


class InviteLock(Protocol):
    def ensure_owned(self) -> None: ...


InviteLockFactory = Callable[..., AbstractAsyncContextManager[InviteLock]]
BusinessNotificationSender = Callable[..., Awaitable[None]]

_BUSINESS_NOTIFICATION_MARKERS = "business_notification_deliveries"


async def _send_resource_user_invite_business_notification(**payload: Any) -> None:
    from bisheng.message.api.dependencies import get_message_service
    from bisheng.message.domain.services.notification_content import build_notify_content

    async with get_async_db_session() as session:
        message_service = await get_message_service(session)
        await message_service.send_generic_notify(
            sender=payload["sender"],
            receiver_user_ids=payload["receiver_user_ids"],
            content_item_list=build_notify_content(
                action_code=payload["action_code"],
                target_name=payload["business_name"],
                business_type="approval_instance_id",
                business_id=payload["approval_instance_id"],
                actor_user_id=payload["sender"],
                actor_user_name=payload["actor_user_name"],
                scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
                reason=payload.get("reason"),
            ),
            action_code=payload["action_code"],
        )


class ResourceUserInviteBusinessNotificationService:
    """Send Permission-owned execution outcomes once per stable execution token."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        send_notification: BusinessNotificationSender = _send_resource_user_invite_business_notification,
    ) -> None:
        self.session_factory = session_factory
        self.send_notification = send_notification

    async def notify_execution_result(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
    ) -> None:
        tenant_id = ResourceUserInviteApplicationService._require_tenant(tenant_id)
        request_id = ResourceUserInviteApplicationService._require_positive_id(
            request_id,
            field_name="request_id",
        )
        if not isinstance(execution_token, str) or not execution_token:
            raise ValueError("execution_token is required for business notification")

        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                select(ResourceUserInviteRequest)
                .where(
                    ResourceUserInviteRequest.tenant_id == tenant_id,
                    ResourceUserInviteRequest.id == request_id,
                )
                .with_for_update()
            )
            row = result.scalars().first()
            if row is None:
                raise LookupError("resource user invite request does not exist for notification")
            if row.execution_token != execution_token:
                raise RuntimeError("resource user invite notification execution token mismatch")
            if row.execution_state not in {
                ResourceUserInviteExecutionState.APPLIED,
                ResourceUserInviteExecutionState.FAILED,
            }:
                raise RuntimeError("resource user invite notification requires a terminal business state")

            marker_key = f"{execution_token}:{row.execution_state}"
            snapshot = deepcopy(row.result_snapshot or {})
            markers = dict(snapshot.get(_BUSINESS_NOTIFICATION_MARKERS) or {})
            if markers.get(marker_key) is not None:
                return

            action_code = (
                "resource_user_invite_effective"
                if row.execution_state == ResourceUserInviteExecutionState.APPLIED
                else "resource_user_invite_failed"
            )
            await self.send_notification(
                sender=row.target_user_id,
                receiver_user_ids=[row.inviter_user_id],
                action_code=action_code,
                business_name=row.resource_name,
                approval_instance_id=row.approval_instance_id,
                actor_user_name=row.target_user_name,
                reason=(row.error_summary if row.execution_state == ResourceUserInviteExecutionState.FAILED else None),
            )
            markers[marker_key] = {
                "action_code": action_code,
                "execution_state": row.execution_state,
                "execution_token": execution_token,
            }
            snapshot[_BUSINESS_NOTIFICATION_MARKERS] = markers
            row.result_snapshot = snapshot
            session.add(row)
            await session.flush()


class ResourceUserInviteApplicationService:
    """Own F045 invite creation, de-duplication, binding, and projection."""

    def __init__(
        self,
        *,
        submission_port: ApprovalSubmissionPort[AsyncSession],
        session_factory: SessionFactory = get_async_db_session,
        lock_factory: InviteLockFactory = resource_user_invite_lock,
        approval_status_port: ApprovalStatusReadPort | None = None,
        dispatcher: ResourceUserInviteDispatcher | None = None,
    ) -> None:
        self.submission_port = submission_port
        self.session_factory = session_factory
        self.lock_factory = lock_factory
        self.approval_status_port = approval_status_port
        self.dispatcher = dispatcher

    def scenario_guard(self, *, tenant_id: int):
        return self.submission_port.scenario_guard(
            tenant_id=tenant_id,
            scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
        )

    async def request_invite(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | int,
        resource_name: str,
        inviter_user_id: int,
        inviter_user_name: str,
        target_user_id: int,
        target_user_name: str,
        relation: str,
        model_id: str | None,
        role_snapshot: Mapping[str, Any],
        include_children: bool = False,
        applicant_department_id: int | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = self._require_tenant(tenant_id)
        resource_type = self._require_text(resource_type, field_name="resource_type")
        resource_id = self._require_text(resource_id, field_name="resource_id")
        target_user_id = self._require_positive_id(target_user_id, field_name="target_user_id")
        inviter_user_id = self._require_positive_id(inviter_user_id, field_name="inviter_user_id")
        business_key = build_resource_user_invite_business_key(
            resource_type=resource_type,
            resource_id=resource_id,
            target_user_id=target_user_id,
        )
        role_copy, role_fingerprint = self._canonical_snapshot(role_snapshot)
        request_fingerprint = self._request_fingerprint(
            tenant_id=tenant_id,
            business_key=business_key,
            inviter_user_id=inviter_user_id,
            relation=relation,
            model_id=model_id,
            include_children=include_children,
            role_fingerprint=role_fingerprint,
        )

        async with self.lock_factory(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            target_user_id=target_user_id,
        ) as lock:
            lock.ensure_owned()
            try:
                row, effects, created = await self._create_or_get(
                    tenant_id=tenant_id,
                    business_key=business_key,
                    request_fingerprint=request_fingerprint,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    inviter_user_id=inviter_user_id,
                    inviter_user_name=inviter_user_name,
                    target_user_id=target_user_id,
                    target_user_name=target_user_name,
                    relation=relation,
                    model_id=model_id,
                    include_children=include_children,
                    role_snapshot=role_copy,
                    role_fingerprint=role_fingerprint,
                    applicant_department_id=applicant_department_id,
                    reason=reason,
                )
            except IntegrityError as conflict:
                row = await self._load_active_after_conflict(
                    tenant_id=tenant_id,
                    business_key=business_key,
                    original_error=conflict,
                )
                effects = ()
                created = False

        await self._run_post_commit_effects(effects)
        return self._result(row, outcome="invite_created" if created else "invite_existing")

    async def list_pending_invites(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | int,
    ) -> list[ResourceUserInviteRequest]:
        tenant_id = self._require_tenant(tenant_id)
        resource_type = self._require_text(resource_type, field_name="resource_type")
        resource_id = self._require_text(resource_id, field_name="resource_id")
        async with self.session_factory() as session:
            repository = ResourceUserInviteRequestRepository(session)
            return await repository.list_pending_for_resource(
                tenant_id=tenant_id,
                resource_type=resource_type,
                resource_id=resource_id,
            )

    async def list_pending_invite_items(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | int,
    ) -> list[ResourceUserInvitePendingItem]:
        """Project Permission facts and batch-read only Approval terminal status."""

        rows = await self.list_pending_invites(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if not rows:
            return []
        status_port = self._require_approval_status_port()
        instance_ids = tuple(self._required_id(row.approval_instance_id, label="approval instance") for row in rows)
        statuses = await status_port.get_statuses(
            tenant_id=int(tenant_id),
            approval_instance_ids=instance_ids,
        )

        items: list[ResourceUserInvitePendingItem] = []
        for row in rows:
            request_id = self._required_id(row.id, label="resource user invite request")
            approval_instance_id = self._required_id(
                row.approval_instance_id,
                label="approval instance",
            )
            approval_status = self._approval_status_value(
                statuses.get(approval_instance_id),
                expected_instance_id=approval_instance_id,
            )
            role_snapshot = row.role_snapshot if isinstance(row.role_snapshot, Mapping) else {}
            items.append(
                ResourceUserInvitePendingItem(
                    subject_type="user",
                    subject_id=int(row.target_user_id),
                    subject_name=row.target_user_name,
                    relation=row.relation,
                    include_children=bool(row.include_children),
                    model_id=row.model_id,
                    model_name=role_snapshot.get("name"),
                    is_creator=False,
                    approval_instance_id=approval_instance_id,
                    business_request_id=request_id,
                    approval_status=approval_status,
                    execution_state=row.execution_state,
                    retryable=(
                        approval_status == "approved" and row.execution_state == ResourceUserInviteExecutionState.FAILED
                    ),
                )
            )
        return items

    async def retry_failed_invite(
        self,
        *,
        tenant_id: int,
        request_id: int,
    ) -> ResourceUserInviteRetryResult:
        """Re-dispatch one approved failed request without creating new approval facts."""

        tenant_id = self._require_tenant(tenant_id)
        request_id = self._require_positive_id(request_id, field_name="request_id")
        status_port = self._require_approval_status_port()
        dispatcher = self._require_dispatcher()

        async with self.session_factory() as session:
            repository = ResourceUserInviteRequestRepository(session)
            candidate = await repository.get_by_id(
                tenant_id=tenant_id,
                request_id=request_id,
            )
            if candidate is None:
                raise ValueError("resource user invite request does not exist")
            approval_instance_id = self._required_id(
                candidate.approval_instance_id,
                label="approval instance",
            )
        statuses = await status_port.get_statuses(
            tenant_id=tenant_id,
            approval_instance_ids=(approval_instance_id,),
        )
        approval_status = self._approval_status_value(
            statuses.get(approval_instance_id),
            expected_instance_id=approval_instance_id,
        )

        async with self.session_factory() as session, session.begin():
            repository = ResourceUserInviteRequestRepository(session)
            row = await repository.get_by_id(
                tenant_id=tenant_id,
                request_id=request_id,
                for_update=True,
            )
            if row is None:
                raise ValueError("resource user invite request does not exist")
            if (
                approval_status != "approved"
                or row.execution_state != ResourceUserInviteExecutionState.FAILED
                or row.active_marker != 0
                or row.approval_instance_id != approval_instance_id
            ):
                raise ValueError("retry requires an approved approval and failed business request")

        await dispatcher.dispatch(tenant_id=tenant_id, request_id=request_id)
        return ResourceUserInviteRetryResult(
            business_request_id=request_id,
            approval_instance_id=approval_instance_id,
        )

    async def _create_or_get(
        self,
        *,
        tenant_id: int,
        business_key: str,
        request_fingerprint: str,
        resource_type: str,
        resource_id: str,
        resource_name: str,
        inviter_user_id: int,
        inviter_user_name: str,
        target_user_id: int,
        target_user_name: str,
        relation: str,
        model_id: str | None,
        include_children: bool,
        role_snapshot: dict[str, Any],
        role_fingerprint: str,
        applicant_department_id: int | None,
        reason: str | None,
    ) -> tuple[
        ResourceUserInviteRequest,
        tuple[ApprovalPostCommitCallback, ...],
        bool,
    ]:
        async with self.session_factory() as session:
            repository = ResourceUserInviteRequestRepository(session)
            async with session.begin():
                existing = await repository.get_active(
                    tenant_id=tenant_id,
                    business_key=business_key,
                    for_update=True,
                )
                if existing is not None:
                    return existing, (), False

                row = ResourceUserInviteRequest(
                    tenant_id=tenant_id,
                    business_key=business_key,
                    active_marker=0,
                    request_fingerprint=request_fingerprint,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    inviter_user_id=inviter_user_id,
                    inviter_user_name=inviter_user_name,
                    target_user_id=target_user_id,
                    target_user_name=target_user_name,
                    relation=relation,
                    model_id=model_id,
                    include_children=include_children,
                    role_snapshot=deepcopy(role_snapshot),
                    role_fingerprint=role_fingerprint,
                    execution_state=ResourceUserInviteExecutionState.AWAITING_APPROVAL,
                )
                await repository.add_and_flush(row)
                request_id = self._required_id(row.id, label="resource user invite request")
                result = await self.submission_port.submit_in_uow(
                    session=session,
                    command=ApprovalSubmissionCommand(
                        tenant_id=tenant_id,
                        scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
                        business_request_type=RESOURCE_USER_INVITE_REQUEST_TYPE,
                        business_request_id=str(request_id),
                        business_key=business_key,
                        request_fingerprint=request_fingerprint,
                        title=resource_name,
                        applicant=ApprovalApplicant(
                            user_id=inviter_user_id,
                            user_name=inviter_user_name,
                            department_id=applicant_department_id,
                        ),
                        initial_approver_user_ids=(target_user_id,),
                        detail_snapshot={
                            "resource_type": resource_type,
                            "resource_name": resource_name,
                            "target_user_id": target_user_id,
                            "target_user_name": target_user_name,
                            "relation": relation,
                            "model_id": model_id,
                            "include_children": include_children,
                            "reason": reason,
                        },
                        link_snapshot={
                            "resource_type": resource_type,
                            "resource_id": resource_id,
                        },
                    ),
                )
                await repository.bind_approval_instance(
                    row,
                    approval_instance_id=result.instance_id,
                )
            return row, result.post_commit_effects, True

    async def _load_active_after_conflict(
        self,
        *,
        tenant_id: int,
        business_key: str,
        original_error: IntegrityError,
    ) -> ResourceUserInviteRequest:
        async with self.session_factory() as session:
            repository = ResourceUserInviteRequestRepository(session)
            existing = await repository.get_active(
                tenant_id=tenant_id,
                business_key=business_key,
            )
        if existing is None:
            raise original_error
        return existing

    @staticmethod
    async def _run_post_commit_effects(effects: tuple[ApprovalPostCommitCallback, ...]) -> None:
        for effect in effects:
            outcome = effect()
            if inspect.isawaitable(outcome):
                await outcome

    @staticmethod
    def _canonical_snapshot(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        canonical = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        normalized = json.loads(canonical)
        if not isinstance(normalized, dict):
            raise ValueError("role_snapshot must be a JSON object")
        return normalized, hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_fingerprint(
        *,
        tenant_id: int,
        business_key: str,
        inviter_user_id: int,
        relation: str,
        model_id: str | None,
        include_children: bool,
        role_fingerprint: str,
    ) -> str:
        canonical = json.dumps(
            {
                "business_key": business_key,
                "include_children": bool(include_children),
                "inviter_user_id": inviter_user_id,
                "model_id": model_id,
                "relation": relation,
                "role_fingerprint": role_fingerprint,
                "tenant_id": tenant_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _result(row: ResourceUserInviteRequest, *, outcome: str) -> dict[str, Any]:
        return {
            "outcome": outcome,
            "request_id": ResourceUserInviteApplicationService._required_id(
                row.id,
                label="resource user invite request",
            ),
            "approval_instance_id": row.approval_instance_id,
            "target_user_id": row.target_user_id,
            "relation": row.relation,
            "model_id": row.model_id,
            "include_children": row.include_children,
            "role_snapshot": deepcopy(row.role_snapshot),
            "execution_state": row.execution_state,
        }

    @staticmethod
    def _required_id(value: int | None, *, label: str) -> int:
        if value is None:
            raise RuntimeError(f"{label} id was not assigned")
        return int(value)

    def _require_approval_status_port(self) -> ApprovalStatusReadPort:
        if self.approval_status_port is None:
            raise RuntimeError("resource user invite approval status port is not configured")
        return self.approval_status_port

    def _require_dispatcher(self) -> ResourceUserInviteDispatcher:
        if self.dispatcher is None:
            raise RuntimeError("resource user invite dispatcher is not configured")
        return self.dispatcher

    @staticmethod
    def _approval_status_value(
        value: ApprovalStatusSnapshot | str | None,
        *,
        expected_instance_id: int,
    ) -> str:
        if isinstance(value, ApprovalStatusSnapshot):
            if value.instance_id != expected_instance_id:
                raise RuntimeError("approval status snapshot instance mismatch")
            status = value.status
        elif isinstance(value, str):
            status = value
        else:
            raise RuntimeError(f"approval status missing for instance {expected_instance_id}")
        normalized = status.strip()
        if not normalized:
            raise RuntimeError(f"approval status missing for instance {expected_instance_id}")
        return normalized

    @staticmethod
    def _require_positive_id(value: int, *, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        return value

    @staticmethod
    def _require_text(value: str | int, *, field_name: str) -> str:
        normalized = str(value)
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        return normalized

    @classmethod
    def _require_tenant(cls, tenant_id: int) -> int:
        tenant_id = cls._require_positive_id(tenant_id, field_name="tenant_id")
        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != tenant_id:
            raise ValueError("resource user invite requires the matching tenant context")
        return tenant_id
