from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusSnapshot
from bisheng.approval.domain.ports.scenario_policy import (
    ApprovalSubmissionCommand,
    ApprovalSubmissionResult,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.api.endpoints import resource_permission as resource_permission_endpoint
from bisheng.permission.api.router import router as permission_router
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.services import resource_user_invite_application_service as application_module
from bisheng.permission.domain.services.resource_user_invite_application_service import (
    ResourceUserInviteApplicationService,
)

TENANT_ID = 7


class _User:
    user_id = 101
    user_name = "inviter-a"
    tenant_id = TENANT_ID

    @staticmethod
    def is_admin() -> bool:
        return True


class _SubmissionPort:
    def __init__(self) -> None:
        self.commands: list[ApprovalSubmissionCommand] = []

    async def submit_in_uow(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult:
        del session
        self.commands.append(command)
        return ApprovalSubmissionResult(instance_id=501)

    @asynccontextmanager
    async def scenario_guard(self, **_identity):
        yield


class _ApprovalStatusPort:
    """Read-only Approval port used by Permission; it never exposes payload."""

    def __init__(self, statuses: Mapping[int, str]) -> None:
        self.statuses = dict(statuses)
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    async def get_statuses(
        self,
        *,
        tenant_id: int,
        approval_instance_ids: tuple[int, ...],
    ) -> Mapping[int, ApprovalStatusSnapshot]:
        self.calls.append((tenant_id, approval_instance_ids))
        return {
            instance_id: ApprovalStatusSnapshot(
                instance_id=instance_id,
                status=self.statuses[instance_id],
            )
            for instance_id in approval_instance_ids
            if instance_id in self.statuses
        }


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.failure: Exception | None = None

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        self.calls.append((tenant_id, request_id))
        if self.failure is not None:
            raise self.failure


@asynccontextmanager
async def _no_op_lock(**_identity):
    class _Lock:
        @staticmethod
        def ensure_owned() -> None:
            return None

    yield _Lock()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ResourceUserInviteRequest.__table__.create)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_token = set_current_tenant_id(TENANT_ID)
    try:
        yield factory
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


def _application_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    statuses: Mapping[int, str],
) -> tuple[ResourceUserInviteApplicationService, _ApprovalStatusPort, _Dispatcher]:
    status_port = _ApprovalStatusPort(statuses)
    dispatcher = _Dispatcher()
    service = ResourceUserInviteApplicationService(
        submission_port=_SubmissionPort(),
        session_factory=session_factory,
        lock_factory=_no_op_lock,
        approval_status_port=status_port,
        dispatcher=dispatcher,
    )
    return service, status_port, dispatcher


async def _insert_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    target_user_id: int,
    approval_instance_id: int,
    execution_state: str,
    resource_id: str = "88",
    active_marker: int = 0,
) -> ResourceUserInviteRequest:
    row = ResourceUserInviteRequest(
        tenant_id=TENANT_ID,
        business_key=f"resource-user-invite:knowledge_space:{resource_id}:user:{target_user_id}",
        active_marker=active_marker,
        request_fingerprint=f"request-fingerprint-{target_user_id}",
        resource_type="knowledge_space",
        resource_id=resource_id,
        resource_name="Docs",
        inviter_user_id=101,
        inviter_user_name="inviter-a",
        target_user_id=target_user_id,
        target_user_name=f"target-{target_user_id}",
        relation="editor",
        model_id="editor-model",
        include_children=True,
        role_snapshot={
            "name": "Editor",
            "relation": "editor",
            "grant_tier": "usage",
            "permissions": ["read", "write"],
        },
        role_fingerprint=f"role-fingerprint-{target_user_id}",
        approval_instance_id=approval_instance_id,
        decision_event_id=(9000 + target_user_id if execution_state != "awaiting_approval" else None),
        execution_state=execution_state,
        execution_token="must-not-be-exposed",
        error_summary="internal failure detail",
        result_snapshot={"authorization_tuple": "must-not-be-exposed"},
    )
    async with session_factory() as session, session.begin():
        session.add(row)
        await session.flush()
    return row


async def test_pending_list_reads_business_rows_and_batches_readonly_approval_statuses(session_factory) -> None:
    awaiting = await _insert_request(
        session_factory,
        target_user_id=201,
        approval_instance_id=501,
        execution_state=ResourceUserInviteExecutionState.AWAITING_APPROVAL,
    )
    failed = await _insert_request(
        session_factory,
        target_user_id=202,
        approval_instance_id=502,
        execution_state=ResourceUserInviteExecutionState.FAILED,
    )
    await _insert_request(
        session_factory,
        target_user_id=203,
        approval_instance_id=503,
        execution_state=ResourceUserInviteExecutionState.QUEUED,
    )
    await _insert_request(
        session_factory,
        target_user_id=204,
        approval_instance_id=504,
        execution_state=ResourceUserInviteExecutionState.APPLYING,
    )
    await _insert_request(
        session_factory,
        target_user_id=205,
        approval_instance_id=505,
        execution_state=ResourceUserInviteExecutionState.CLOSED,
        active_marker=205,
    )
    await _insert_request(
        session_factory,
        target_user_id=206,
        approval_instance_id=506,
        execution_state=ResourceUserInviteExecutionState.QUEUED,
        resource_id="other-resource",
    )
    service, status_port, _ = _application_service(
        session_factory,
        statuses={
            501: "pending",
            502: "approved",
            503: "approved",
            504: "approved",
            505: "rejected",
            506: "approved",
        },
    )

    items = await service.list_pending_invite_items(
        tenant_id=TENANT_ID,
        resource_type="knowledge_space",
        resource_id="88",
    )

    assert status_port.calls == [(TENANT_ID, (501, 502, 503, 504))]
    assert [item.business_request_id for item in items[:2]] == [awaiting.id, failed.id]
    assert [item.approval_status for item in items] == ["pending", "approved", "approved", "approved"]
    assert [item.execution_state for item in items] == [
        "awaiting_approval",
        "failed",
        "queued",
        "applying",
    ]
    assert [item.retryable for item in items] == [False, True, False, False]

    payload = items[1].model_dump(mode="json")
    assert payload == {
        "subject_type": "user",
        "subject_id": 202,
        "subject_name": "target-202",
        "subject_group_names": None,
        "subject_member_names": None,
        "relation": "editor",
        "include_children": True,
        "model_id": "editor-model",
        "model_name": "Editor",
        "is_creator": False,
        "authorization_status": "pending",
        "approval_instance_id": 502,
        "business_request_id": failed.id,
        "approval_status": "approved",
        "execution_state": "failed",
        "retryable": True,
    }


async def test_pending_projection_does_not_scan_approval_payload_or_expose_execution_facts(session_factory) -> None:
    await _insert_request(
        session_factory,
        target_user_id=201,
        approval_instance_id=501,
        execution_state=ResourceUserInviteExecutionState.FAILED,
    )
    service, _, _ = _application_service(session_factory, statuses={501: "approved"})

    item = (
        await service.list_pending_invite_items(
            tenant_id=TENANT_ID,
            resource_type="knowledge_space",
            resource_id="88",
        )
    )[0]

    payload = item.model_dump(mode="json")
    assert not {
        "role_snapshot",
        "role_fingerprint",
        "request_fingerprint",
        "execution_token",
        "error_summary",
        "result_snapshot",
        "authorization_tuple",
    }.intersection(payload)
    source = inspect.getsource(application_module)
    assert "payload_snapshot" not in source
    assert "approval.domain.models" not in source
    assert "approval.domain.repositories" not in source


async def test_retry_dispatches_the_same_approved_failed_business_request(session_factory) -> None:
    row = await _insert_request(
        session_factory,
        target_user_id=201,
        approval_instance_id=501,
        execution_state=ResourceUserInviteExecutionState.FAILED,
    )
    service, status_port, dispatcher = _application_service(session_factory, statuses={501: "approved"})

    result = await service.retry_failed_invite(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    assert status_port.calls == [(TENANT_ID, (501,))]
    assert dispatcher.calls == [(TENANT_ID, int(row.id))]
    assert result.business_request_id == row.id
    assert result.approval_instance_id == 501
    assert result.approval_status == "approved"
    assert result.execution_state == "failed"
    assert result.retry_dispatched is True


async def test_retry_broker_failure_keeps_the_business_request_failed(session_factory) -> None:
    row = await _insert_request(
        session_factory,
        target_user_id=201,
        approval_instance_id=501,
        execution_state=ResourceUserInviteExecutionState.FAILED,
    )
    service, _, dispatcher = _application_service(session_factory, statuses={501: "approved"})
    dispatcher.failure = RuntimeError("broker unavailable")

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await service.retry_failed_invite(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
        )

    async with session_factory() as session:
        persisted = await session.get(ResourceUserInviteRequest, int(row.id))
    assert persisted is not None
    assert persisted.execution_state == ResourceUserInviteExecutionState.FAILED
    assert persisted.active_marker == 0


@pytest.mark.parametrize(
    ("execution_state", "approval_status"),
    [
        (ResourceUserInviteExecutionState.AWAITING_APPROVAL, "pending"),
        (ResourceUserInviteExecutionState.FAILED, "rejected"),
        (ResourceUserInviteExecutionState.QUEUED, "approved"),
        (ResourceUserInviteExecutionState.APPLYING, "approved"),
        (ResourceUserInviteExecutionState.APPLIED, "approved"),
    ],
)
async def test_retry_rejects_everything_except_approved_failed_original_request(
    session_factory,
    execution_state,
    approval_status,
) -> None:
    active_marker = 201 if execution_state == ResourceUserInviteExecutionState.APPLIED else 0
    row = await _insert_request(
        session_factory,
        target_user_id=201,
        approval_instance_id=501,
        execution_state=execution_state,
        active_marker=active_marker,
    )
    service, _, dispatcher = _application_service(session_factory, statuses={501: approval_status})

    with pytest.raises(ValueError, match=r"approved.*failed|failed.*approved"):
        await service.retry_failed_invite(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
        )

    assert dispatcher.calls == []


async def test_approval_submission_contains_only_safe_display_snapshot(session_factory) -> None:
    submission_port = _SubmissionPort()
    service = ResourceUserInviteApplicationService(
        submission_port=submission_port,
        session_factory=session_factory,
        lock_factory=_no_op_lock,
    )

    result = await service.request_invite(
        tenant_id=TENANT_ID,
        resource_type="knowledge_space",
        resource_id="88",
        resource_name="Docs",
        inviter_user_id=101,
        inviter_user_name="inviter-a",
        target_user_id=201,
        target_user_name="target-201",
        relation="editor",
        model_id="editor-model",
        include_children=True,
        role_snapshot={"name": "Editor", "permissions": ["read", "write"]},
        reason="project collaboration",
    )

    command = submission_port.commands[0]
    assert command.business_request_id == str(result["request_id"])
    assert command.detail_snapshot == {
        "resource_type": "knowledge_space",
        "resource_name": "Docs",
        "target_user_id": 201,
        "target_user_name": "target-201",
        "relation": "editor",
        "model_id": "editor-model",
        "include_children": True,
        "reason": "project collaboration",
    }
    assert command.link_snapshot == {
        "resource_type": "knowledge_space",
        "resource_id": "88",
    }
    assert not {
        "role_snapshot",
        "role_fingerprint",
        "request_fingerprint",
        "execution_state",
        "execution_token",
        "result_snapshot",
        "error_summary",
        "authorization_tuple",
    }.intersection(command.detail_snapshot)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(permission_router, prefix="/api/v1")

    async def get_user():
        return _User()

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    return app


def test_retry_api_uses_business_request_id_and_delegates_to_permission_service(monkeypatch) -> None:
    service = SimpleNamespace(
        retry_failed_invite=AsyncMock(
            return_value={
                "business_request_id": 301,
                "approval_instance_id": 501,
                "approval_status": "approved",
                "execution_state": "failed",
                "retry_dispatched": True,
            }
        )
    )
    monkeypatch.setattr(
        resource_permission_endpoint,
        "build_runtime_resource_user_invite_application_service",
        lambda: service,
        raising=False,
    )

    with TestClient(_make_app()) as client:
        response = client.post("/api/v1/permissions/resource-user-invites/301/retry")

    assert response.status_code == 200
    assert response.json()["data"]["business_request_id"] == 301
    service.retry_failed_invite.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        request_id=301,
    )


def test_pending_response_schema_preserves_frontend_fields_and_hides_internal_snapshots() -> None:
    from bisheng.permission.domain.schemas.resource_authorization_schema import (
        ResourceUserInvitePendingItem,
    )

    item = ResourceUserInvitePendingItem(
        subject_type="user",
        subject_id=201,
        subject_name="target-201",
        subject_group_names=None,
        subject_member_names=None,
        relation="editor",
        include_children=True,
        model_id="editor-model",
        model_name="Editor",
        is_creator=False,
        authorization_status="pending",
        approval_instance_id=501,
        business_request_id=301,
        approval_status="approved",
        execution_state="failed",
        retryable=True,
        role_snapshot={"permissions": ["must-not-leak"]},
        result_snapshot={"authorization_tuple": "must-not-leak"},
    )

    assert item.model_dump(mode="json") == {
        "subject_type": "user",
        "subject_id": 201,
        "subject_name": "target-201",
        "subject_group_names": None,
        "subject_member_names": None,
        "relation": "editor",
        "include_children": True,
        "model_id": "editor-model",
        "model_name": "Editor",
        "is_creator": False,
        "authorization_status": "pending",
        "approval_instance_id": 501,
        "business_request_id": 301,
        "approval_status": "approved",
        "execution_state": "failed",
        "retryable": True,
    }
