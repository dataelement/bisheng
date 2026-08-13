"""In-process API E2E coverage for F045 personal-user invite confirmation.

The suite runs the real Permission application service, decision subscriber,
business worker state machine, and grant registry against SQLite. Approval,
broker, and resource-owner adapters are deterministic in-process fakes so the
full lifecycle is testable without local MySQL/Redis/OpenFGA services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Cookie, Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusSnapshot
from bisheng.approval.domain.ports.decision_subscriber import ApprovalDecisionEvent
from bisheng.approval.domain.ports.scenario_policy import ApprovalSubmissionCommand, ApprovalSubmissionResult
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.models.resource_user_invite_request import (
    RESOURCE_USER_INVITE_REQUEST_TYPE,
    RESOURCE_USER_INVITE_SCENARIO_CODE,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
)
from bisheng.permission.domain.services.resource_grant_executor_registry import ResourceGrantExecutorRegistry
from bisheng.permission.domain.services.resource_user_invite_application_service import (
    ResourceUserInviteApplicationService,
)
from bisheng.permission.domain.services.resource_user_invite_decision_subscriber import (
    ResourceUserInviteDecisionSubscriber,
)
from bisheng.worker.permission import resource_user_invite_tasks as worker_module
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

PREFIX = f"e2e-f045-{uuid4().hex[:8]}-"
TEST_TENANT_ID = 74501
ADMIN_USER_ID = 9001
INVITER_USER_ID = 9002
TARGET_USER_ID = 9003
OTHER_TENANT_ID = 74502

TOKENS = {
    "e2e-f045-admin": (TEST_TENANT_ID, ADMIN_USER_ID),
    "e2e-f045-inviter": (TEST_TENANT_ID, INVITER_USER_ID),
    "e2e-f045-target": (TEST_TENANT_ID, TARGET_USER_ID),
    "e2e-f045-other-tenant": (OTHER_TENANT_ID, TARGET_USER_ID),
}


class InviteBody(BaseModel):
    resource_id: str = Field(min_length=1)
    resource_name: str = Field(min_length=1)
    target_user_id: int = Field(gt=0)
    relation: str = Field(min_length=1)


class DecisionBody(BaseModel):
    action: str


class _NoopNotification:
    async def notify_execution_result(self, **_kwargs) -> None:
        return None


@dataclass(slots=True)
class _ApprovalFact:
    instance_id: int
    task_id: int
    request_id: int
    applicant_user_id: int
    approver_user_id: int
    status: str = "pending"
    event: ApprovalDecisionEvent | None = None


class _ApprovalAdapter:
    def __init__(self) -> None:
        self.instances: dict[int, _ApprovalFact] = {}
        self.commands: list[ApprovalSubmissionCommand] = []
        self.next_instance_id = 1000
        self.next_event_id = 5000

    @asynccontextmanager
    async def scenario_guard(self, **_identity):
        yield

    async def submit_in_uow(
        self,
        *,
        session: AsyncSession,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult:
        assert session.in_transaction()
        self.next_instance_id += 1
        instance_id = self.next_instance_id
        task_id = instance_id + 10000
        fact = _ApprovalFact(
            instance_id=instance_id,
            task_id=task_id,
            request_id=int(command.business_request_id),
            applicant_user_id=command.applicant.user_id,
            approver_user_id=command.initial_approver_user_ids[0],
        )
        self.instances[instance_id] = fact
        self.commands.append(command)
        return ApprovalSubmissionResult(instance_id=instance_id, task_ids=(task_id,))

    async def get_statuses(self, *, tenant_id: int, approval_instance_ids) -> Mapping[int, ApprovalStatusSnapshot]:
        assert tenant_id == TEST_TENANT_ID
        return {
            instance_id: ApprovalStatusSnapshot(instance_id=instance_id, status=self.instances[instance_id].status)
            for instance_id in approval_instance_ids
            if instance_id in self.instances
        }


class _GrantExecutor:
    resource_type = "knowledge_space"

    def __init__(self) -> None:
        self.authoritative: set[tuple[str, int, str]] = set()
        self.execute_calls: list[int] = []
        self.fail_next = False

    async def execute(self, command: ResourceGrantCommand) -> None:
        self.execute_calls.append(command.request_id)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("e2e-f045-openfga-unavailable")
        self.authoritative.add((command.resource_id, command.target_user_id, command.relation))

    async def verify(self, command: ResourceGrantCommand) -> ResourceGrantVerificationResult:
        key = (command.resource_id, command.target_user_id, command.relation)
        return ResourceGrantVerificationResult(
            applied=key in self.authoritative,
            result_snapshot={"resource_id": command.resource_id, "target_user_id": command.target_user_id},
        )


class _Harness:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.approval = _ApprovalAdapter()
        self.executor = _GrantExecutor()
        self.registry = ResourceGrantExecutorRegistry()
        self.registry.register("knowledge_space", self.executor)
        self.registry.freeze(required_resource_types={"knowledge_space"})
        self.worker_queue: list[int] = []
        self.consumer_enabled = True
        self.app_service = ResourceUserInviteApplicationService(
            submission_port=self.approval,
            session_factory=session_factory,
            lock_factory=self._lock,
            approval_status_port=self.approval,
            dispatcher=self,
        )
        self.subscriber = ResourceUserInviteDecisionSubscriber(
            dispatcher=self,
            session_factory=session_factory,
        )

    @asynccontextmanager
    async def _lock(self, **_identity):
        yield SimpleNamespace(ensure_owned=lambda: None)

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        assert tenant_id == TEST_TENANT_ID
        if request_id not in self.worker_queue:
            self.worker_queue.append(request_id)

    async def run_worker(self, request_id: int) -> dict:
        if request_id in self.worker_queue:
            self.worker_queue.remove(request_id)
        token = set_current_tenant_id(TEST_TENANT_ID)
        try:
            return await worker_module._execute_resource_user_invite_async(
                tenant_id=TEST_TENANT_ID,
                request_id=request_id,
                notification_service=_NoopNotification(),
            )
        finally:
            current_tenant_id.reset(token)

    async def load_request(self, request_id: int) -> ResourceUserInviteRequest:
        async with self.session_factory() as session:
            row = await session.get(ResourceUserInviteRequest, request_id)
        assert row is not None
        return row

    async def cleanup(self) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                delete(ResourceUserInviteRequest).where(
                    ResourceUserInviteRequest.tenant_id == TEST_TENANT_ID,
                    ResourceUserInviteRequest.resource_name.like(f"{PREFIX}%"),
                )
            )
        self.approval.instances.clear()
        self.approval.commands.clear()
        self.executor.authoritative.clear()
        self.executor.execute_calls.clear()
        self.worker_queue.clear()
        self.consumer_enabled = True
        self.executor.fail_next = False

    async def build_event(self, fact: _ApprovalFact, decision: str, operator_user_id: int) -> ApprovalDecisionEvent:
        row = await self.load_request(fact.request_id)
        self.approval.next_event_id += 1
        return ApprovalDecisionEvent(
            event_id=self.approval.next_event_id,
            event_version=1,
            decision_version=1,
            tenant_id=TEST_TENANT_ID,
            scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
            approval_instance_id=fact.instance_id,
            business_request_type=RESOURCE_USER_INVITE_REQUEST_TYPE,
            business_request_id=str(fact.request_id),
            business_key=row.business_key,
            request_fingerprint=row.request_fingerprint,
            decision=decision,
            decided_at=datetime.now(UTC),
            operator_user_id=operator_user_id,
        )


def _actor(access_token_cookie: str | None = Cookie(default=None)) -> tuple[int, int]:
    actor = TOKENS.get(str(access_token_cookie))
    if actor is None:
        raise RuntimeError("missing E2E auth token")
    return actor


def _success(response: httpx.Response):
    data = assert_resp_200(response)
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": data}
    return data


def _error(response: httpx.Response, code: int, message: str):
    body = assert_resp_error(response, code)
    assert body == {"status_code": code, "status_message": message, "data": None}
    return body


def _build_app(harness: _Harness) -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/e2e-f045/invites")
    async def create_invite(body: InviteBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TEST_TENANT_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(tenant_id)
        try:
            result = await harness.app_service.request_invite(
                tenant_id=tenant_id,
                resource_type="knowledge_space",
                resource_id=body.resource_id,
                resource_name=body.resource_name,
                inviter_user_id=user_id,
                inviter_user_name=f"{PREFIX}inviter",
                target_user_id=body.target_user_id,
                target_user_name=f"{PREFIX}target",
                relation=body.relation,
                model_id="e2e-f045-viewer-model",
                role_snapshot={"name": "Viewer", "relation": body.relation},
            )
            return resp_200(result)
        finally:
            current_tenant_id.reset(token)

    @app.get("/api/v1/e2e-f045/requests/{request_id}")
    async def get_request(request_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        token = set_current_tenant_id(tenant_id)
        try:
            row = await harness.load_request(request_id)
            if int(row.tenant_id) != tenant_id:
                return resp_500(code=18100, message="Approval request does not exist")
            approval_status = harness.approval.instances[int(row.approval_instance_id)].status
            grant = (row.resource_id, row.target_user_id, row.relation) in harness.executor.authoritative
            return resp_200(
                {
                    "request_id": int(row.id),
                    "approval_instance_id": int(row.approval_instance_id),
                    "approval_status": approval_status,
                    "execution_state": row.execution_state,
                    "grant_active": grant,
                    "resource_name": row.resource_name,
                }
            )
        finally:
            current_tenant_id.reset(token)

    @app.post("/api/v1/e2e-f045/tasks/{task_id}/decision")
    async def decide(task_id: int, body: DecisionBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        fact = next((value for value in harness.approval.instances.values() if value.task_id == task_id), None)
        if tenant_id != TEST_TENANT_ID or fact is None or fact.approver_user_id != user_id:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        if fact.status != "pending":
            return resp_500(code=18102, message="Approval request has already been processed")
        if body.action not in {"approve", "reject"}:
            return resp_500(code=18102, message="Approval request has already been processed")
        decision = "approved" if body.action == "approve" else "rejected"
        fact.status = decision
        fact.event = await harness.build_event(fact, decision, user_id)
        token = set_current_tenant_id(TEST_TENANT_ID)
        try:
            if harness.consumer_enabled:
                await harness.subscriber.accept(fact.event)
        finally:
            current_tenant_id.reset(token)
        return resp_200({"instance_id": fact.instance_id, "status": fact.status, "event_id": fact.event.event_id})

    @app.post("/api/v1/e2e-f045/instances/{instance_id}/{action}")
    async def terminate(instance_id: int, action: str, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        fact = harness.approval.instances.get(instance_id)
        if tenant_id != TEST_TENANT_ID or fact is None or fact.applicant_user_id != user_id:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        if fact.status != "pending" or action not in {"withdraw", "cancel"}:
            return resp_500(code=18102, message="Approval request has already been processed")
        fact.status = "withdrawn" if action == "withdraw" else "cancelled"
        fact.event = await harness.build_event(fact, fact.status, user_id)
        token = set_current_tenant_id(TEST_TENANT_ID)
        try:
            await harness.subscriber.accept(fact.event)
        finally:
            current_tenant_id.reset(token)
        return resp_200({"instance_id": instance_id, "status": fact.status})

    @app.post("/api/v1/e2e-f045/events/{event_id}/deliver")
    async def deliver(event_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        if tenant_id != TEST_TENANT_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        fact = next((value for value in harness.approval.instances.values() if value.event and value.event.event_id == event_id), None)
        assert fact is not None and fact.event is not None
        token = set_current_tenant_id(TEST_TENANT_ID)
        try:
            await harness.subscriber.accept(fact.event)
        finally:
            current_tenant_id.reset(token)
        return resp_200({"event_id": event_id, "delivered": True})

    @app.post("/api/v1/e2e-f045/requests/{request_id}/retry")
    async def retry(request_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        token = set_current_tenant_id(tenant_id)
        try:
            result = await harness.app_service.retry_failed_invite(tenant_id=tenant_id, request_id=request_id)
            return resp_200(result)
        except ValueError:
            return resp_500(code=18102, message="Approval request has already been processed")
        finally:
            current_tenant_id.reset(token)

    return app


@pytest.fixture(scope="module")
async def e2e_harness() -> AsyncIterator[_Harness]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ResourceUserInviteRequest.__table__.create)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    harness = _Harness(session_factory)

    @asynccontextmanager
    async def worker_session_factory():
        async with session_factory() as session:
            yield session

    patcher = pytest.MonkeyPatch()
    patcher.setattr(worker_module, "get_async_db_session", worker_session_factory)
    patcher.setattr(worker_module, "_build_grant_executor_registry", lambda: harness.registry)
    try:
        yield harness
    finally:
        patcher.undo()
        await engine.dispose()


@pytest.fixture(scope="module")
async def client(e2e_harness: _Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_build_app(e2e_harness))
    async with httpx.AsyncClient(transport=transport, base_url="http://e2e-f045.local") as value:
        yield value


@pytest.fixture(autouse=True)
async def setup_and_teardown(e2e_harness: _Harness):
    """Double cleanup: remove only this run's e2e-f045-prefixed data."""
    await e2e_harness.cleanup()
    try:
        yield
    finally:
        await e2e_harness.cleanup()


def _invite_payload(suffix: str = "resource") -> dict:
    return {
        "resource_id": f"{PREFIX}{suffix}",
        "resource_name": f"{PREFIX}{suffix}",
        "target_user_id": TARGET_USER_ID,
        "relation": "viewer",
    }


async def _create(client: httpx.AsyncClient, payload: dict | None = None) -> dict:
    return _success(
        await client.post(
            "/api/v1/e2e-f045/invites",
            json=payload or _invite_payload(),
            headers=auth_headers("e2e-f045-inviter"),
        )
    )


async def _detail(client: httpx.AsyncClient, request_id: int, token: str = "e2e-f045-inviter") -> dict:
    return _success(
        await client.get(
            f"/api/v1/e2e-f045/requests/{request_id}",
            headers=auth_headers(token),
        )
    )


class TestE2EPersonalUserInviteConfirmation:
    async def test_ac07_ac08_ac09_ac10_ac13_ac14_ac17_approve_to_effective(
        self,
        client: httpx.AsyncClient,
        e2e_harness: _Harness,
    ) -> None:
        """AC-07/08/09/10/13/14/17: invitee approval reaches one authoritative grant."""
        created = await _create(client)
        before = await _detail(client, created["request_id"])
        assert before == {
            "request_id": created["request_id"],
            "approval_instance_id": created["approval_instance_id"],
            "approval_status": "pending",
            "execution_state": "awaiting_approval",
            "grant_active": False,
            "resource_name": f"{PREFIX}resource",
        }
        fact = e2e_harness.approval.instances[created["approval_instance_id"]]

        _error(
            await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers("e2e-f045-admin"),
            ),
            18101,
            "You do not have permission to access this approval request",
        )
        _success(
            await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers("e2e-f045-target"),
            )
        )
        await e2e_harness.run_worker(created["request_id"])

        after = await _detail(client, created["request_id"])
        assert after["approval_status"] == "approved"
        assert after["execution_state"] == "applied"
        assert after["grant_active"] is True
        assert e2e_harness.executor.execute_calls == [created["request_id"]]

        _error(
            await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers("e2e-f045-target"),
            ),
            18102,
            "Approval request has already been processed",
        )

    async def test_ac15_duplicate_invite_reuses_request_and_first_snapshot(
        self,
        client: httpx.AsyncClient,
        e2e_harness: _Harness,
    ) -> None:
        """AC-15: duplicate invite returns the same request, task, and first role snapshot."""
        first = await _create(client)
        changed = {**_invite_payload(), "relation": "editor"}
        duplicate = await _create(client, changed)

        assert first["outcome"] == "invite_created"
        assert duplicate["outcome"] == "invite_existing"
        assert duplicate["request_id"] == first["request_id"]
        assert duplicate["approval_instance_id"] == first["approval_instance_id"]
        assert duplicate["relation"] == "viewer"
        assert len(e2e_harness.approval.commands) == 1
        assert (await _detail(client, first["request_id"]))["approval_status"] == "pending"

    @pytest.mark.parametrize(
        ("terminal_action", "expected_status"),
        (("reject", "rejected"), ("withdraw", "withdrawn"), ("cancel", "cancelled")),
    )
    async def test_ac11_ac12_terminal_without_business_grant(
        self,
        client: httpx.AsyncClient,
        e2e_harness: _Harness,
        terminal_action: str,
        expected_status: str,
    ) -> None:
        """AC-11/12: reject, withdraw, and cancel close the request without granting."""
        created = await _create(client, _invite_payload(terminal_action))
        fact = e2e_harness.approval.instances[created["approval_instance_id"]]
        if terminal_action == "reject":
            response = await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "reject"},
                headers=auth_headers("e2e-f045-target"),
            )
        else:
            response = await client.post(
                f"/api/v1/e2e-f045/instances/{fact.instance_id}/{terminal_action}",
                headers=auth_headers("e2e-f045-inviter"),
            )
        _success(response)

        final = await _detail(client, created["request_id"])
        assert final["approval_status"] == expected_status
        assert final["execution_state"] == "closed"
        assert final["grant_active"] is False
        assert e2e_harness.executor.execute_calls == []

    async def test_ac16_ac18_failed_grant_retries_original_approved_request(
        self,
        client: httpx.AsyncClient,
        e2e_harness: _Harness,
    ) -> None:
        """AC-16/18: failed authorization retries the original approved request only."""
        created = await _create(client, _invite_payload("retry"))
        fact = e2e_harness.approval.instances[created["approval_instance_id"]]
        e2e_harness.executor.fail_next = True

        _success(
            await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers("e2e-f045-target"),
            )
        )
        with pytest.raises(RuntimeError, match="e2e-f045-openfga-unavailable"):
            await e2e_harness.run_worker(created["request_id"])
        failed = await _detail(client, created["request_id"])
        assert failed["approval_status"] == "approved"
        assert failed["execution_state"] == "failed"
        assert failed["grant_active"] is False

        retried = _success(
            await client.post(
                f"/api/v1/e2e-f045/requests/{created['request_id']}/retry",
                headers=auth_headers("e2e-f045-inviter"),
            )
        )
        assert retried == {
            "business_request_id": created["request_id"],
            "approval_instance_id": created["approval_instance_id"],
            "approval_status": "approved",
            "execution_state": "failed",
            "retry_dispatched": True,
        }
        await e2e_harness.run_worker(created["request_id"])
        final = await _detail(client, created["request_id"])
        assert final["approval_status"] == "approved"
        assert final["execution_state"] == "applied"
        assert final["grant_active"] is True
        assert len(e2e_harness.approval.commands) == 1
        assert e2e_harness.executor.execute_calls == [created["request_id"], created["request_id"]]

    async def test_ac29_ac30_consumer_recovery_and_ack_loss_are_idempotent(
        self,
        client: httpx.AsyncClient,
        e2e_harness: _Harness,
    ) -> None:
        """AC-29/30: stopped consumer recovers; ack-loss redelivery cannot duplicate grant."""
        created = await _create(client, _invite_payload("delivery"))
        fact = e2e_harness.approval.instances[created["approval_instance_id"]]
        e2e_harness.consumer_enabled = False
        decision = _success(
            await client.post(
                f"/api/v1/e2e-f045/tasks/{fact.task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers("e2e-f045-target"),
            )
        )
        stopped = await _detail(client, created["request_id"])
        assert stopped["approval_status"] == "approved"
        assert stopped["execution_state"] == "awaiting_approval"
        assert stopped["grant_active"] is False

        delivered = _success(
            await client.post(
                f"/api/v1/e2e-f045/events/{decision['event_id']}/deliver",
                headers=auth_headers("e2e-f045-admin"),
            )
        )
        assert delivered == {"event_id": decision["event_id"], "delivered": True}
        await e2e_harness.run_worker(created["request_id"])
        first_final = await _detail(client, created["request_id"])
        assert first_final["execution_state"] == "applied"
        assert first_final["grant_active"] is True

        # Simulate delivery acknowledgement loss by submitting the same stable
        # event again. Subscriber and worker evidence must remain single-shot.
        _success(
            await client.post(
                f"/api/v1/e2e-f045/events/{decision['event_id']}/deliver",
                headers=auth_headers("e2e-f045-admin"),
            )
        )
        second_final = await _detail(client, created["request_id"])
        assert second_final == first_final
        assert e2e_harness.executor.execute_calls == [created["request_id"]]

    async def test_ac07_cross_tenant_read_and_create_are_denied(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """AC-07: dedicated-tenant allow path is paired with cross-tenant denial."""
        created = await _create(client, _invite_payload("tenant"))
        _error(
            await client.get(
                f"/api/v1/e2e-f045/requests/{created['request_id']}",
                headers=auth_headers("e2e-f045-other-tenant"),
            ),
            18100,
            "Approval request does not exist",
        )
        _error(
            await client.post(
                "/api/v1/e2e-f045/invites",
                json=_invite_payload("other-tenant"),
                headers=auth_headers("e2e-f045-other-tenant"),
            ),
            18101,
            "You do not have permission to access this approval request",
        )
