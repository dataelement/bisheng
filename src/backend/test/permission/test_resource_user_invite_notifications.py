from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.services import resource_user_invite_application_service as application_module

TENANT_ID = 7
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_APPROVAL_ROOT = _BACKEND_ROOT / "bisheng" / "approval"
_SUBMISSION_PATH = _APPROVAL_ROOT / "domain" / "services" / "approval_submission_service.py"
_CENTER_PATH = _APPROVAL_ROOT / "domain" / "services" / "approval_center_service.py"
_OUTBOX_PATH = _APPROVAL_ROOT / "domain" / "services" / "approval_outbox_service.py"
_SUBSCRIBER_PATH = (
    _BACKEND_ROOT
    / "bisheng"
    / "permission"
    / "domain"
    / "services"
    / "resource_user_invite_decision_subscriber.py"
)
_APPLICATION_PATH = (
    _BACKEND_ROOT
    / "bisheng"
    / "permission"
    / "domain"
    / "services"
    / "resource_user_invite_application_service.py"
)
_WORKER_PATH = (
    _BACKEND_ROOT / "bisheng" / "worker" / "permission" / "resource_user_invite_tasks.py"
)


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


async def _create_terminal_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    state: str,
    token: str,
) -> ResourceUserInviteRequest:
    async with session_factory() as session, session.begin():
        row = ResourceUserInviteRequest(
            tenant_id=TENANT_ID,
            business_key=f"resource-user-invite:knowledge_space:88:user:{token}",
            active_marker=0,
            request_fingerprint=f"request-{token}",
            resource_type="knowledge_space",
            resource_id="88",
            resource_name="Quarterly Plans",
            inviter_user_id=101,
            inviter_user_name="sensitive-inviter@example.test",
            target_user_id=201,
            target_user_name="sensitive-target@example.test",
            relation="editor",
            model_id="model-1",
            include_children=False,
            role_snapshot={"permissions": ["secret.read", "secret.write"]},
            role_fingerprint=f"role-{token}",
            approval_instance_id=501,
            decision_event_id=9001,
            execution_state=state,
            execution_token=token,
            error_summary="authorization failed" if state == ResourceUserInviteExecutionState.FAILED else None,
            result_snapshot={"grant_visible": state == ResourceUserInviteExecutionState.APPLIED},
        )
        session.add(row)
        await session.flush()
        assert row.id is not None
        if state == ResourceUserInviteExecutionState.APPLIED:
            row.active_marker = int(row.id)
    return row


def test_f025_keeps_task_and_decision_notifications_but_not_business_execution_notifications() -> None:
    submission_source = _SUBMISSION_PATH.read_text(encoding="utf-8")
    center_source = _CENTER_PATH.read_text(encoding="utf-8")
    outbox_source = _OUTBOX_PATH.read_text(encoding="utf-8")

    assert "approval_task_pending" in submission_source
    assert "approval_instance_approved" in center_source
    assert "approval_task_rejected" in center_source
    assert "approval_instance_withdrawn" in center_source
    assert "resource_user_invite_effective" not in outbox_source
    assert "resource.user_invite.execute.success" not in outbox_source
    assert "resource.user_invite.execute.failed" not in outbox_source


def test_repeated_decision_delivery_cannot_emit_permission_business_notifications() -> None:
    subscriber_source = _SUBSCRIBER_PATH.read_text(encoding="utf-8")

    assert "resource_user_invite_effective" not in subscriber_source
    assert "resource_user_invite_failed" not in subscriber_source
    assert "notify_execution_result" not in subscriber_source


@pytest.mark.parametrize(
    ("state", "action_code"),
    [
        (ResourceUserInviteExecutionState.APPLIED, "resource_user_invite_effective"),
        (ResourceUserInviteExecutionState.FAILED, "resource_user_invite_failed"),
    ],
)
async def test_permission_business_notification_is_once_per_execution_token(
    session_factory: async_sessionmaker[AsyncSession],
    state: str,
    action_code: str,
) -> None:
    row = await _create_terminal_request(
        session_factory,
        state=state,
        token=f"stable-{state}",
    )
    sent: list[dict[str, Any]] = []

    async def send_notification(**payload: Any) -> None:
        sent.append(payload)

    service_type = application_module.ResourceUserInviteBusinessNotificationService
    service = service_type(
        session_factory=session_factory,
        send_notification=send_notification,
    )

    for _ in range(2):
        await service.notify_execution_result(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
            execution_token=str(row.execution_token),
        )

    assert len(sent) == 1
    assert sent[0]["action_code"] == action_code
    assert sent[0]["sender"] == 201
    assert sent[0]["receiver_user_ids"] == [101]


async def test_failed_notification_is_retryable_and_is_not_marked_sent_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_terminal_request(
        session_factory,
        state=ResourceUserInviteExecutionState.APPLIED,
        token="notification-retry-token",
    )
    attempts = 0
    sent: list[dict[str, Any]] = []

    async def send_notification(**payload: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("message service unavailable")
        sent.append(payload)

    service = application_module.ResourceUserInviteBusinessNotificationService(
        session_factory=session_factory,
        send_notification=send_notification,
    )
    kwargs = {
        "tenant_id": TENANT_ID,
        "request_id": int(row.id),
        "execution_token": str(row.execution_token),
    }

    with pytest.raises(RuntimeError, match="message service unavailable"):
        await service.notify_execution_result(**kwargs)
    async with session_factory() as session:
        persisted = await session.get(ResourceUserInviteRequest, int(row.id))
    assert persisted is not None
    assert "business_notification_deliveries" not in persisted.result_snapshot

    await service.notify_execution_result(**kwargs)
    await service.notify_execution_result(**kwargs)

    assert attempts == 2
    assert len(sent) == 1


def test_permission_worker_invokes_only_the_permission_owned_notification_service() -> None:
    worker_source = _WORKER_PATH.read_text(encoding="utf-8")
    application_source = _APPLICATION_PATH.read_text(encoding="utf-8")

    assert "ResourceUserInviteBusinessNotificationService" in application_source
    assert "notify_execution_result" in worker_source
    assert "ApprovalNotificationService" not in worker_source
    assert "bisheng.approval" not in worker_source


def test_worker_logs_do_not_render_arbitrary_exception_text_or_business_snapshots() -> None:
    source = _WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_WORKER_PATH))
    error_summary = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_error_summary"
    )
    summary_source = ast.get_source_segment(source, error_summary) or ""
    logger_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"debug", "info", "warning", "error", "exception"}
    ]
    logged_source = "\n".join(ast.get_source_segment(source, node) or "" for node in logger_calls)

    assert "str(error)" not in summary_source
    assert "role_snapshot" not in logged_source
    assert "inviter_user_name" not in logged_source
    assert "target_user_name" not in logged_source
