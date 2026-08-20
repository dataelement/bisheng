"""In-process API E2E coverage for the F046 approval and Knowledge saga."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from fastapi import Cookie, Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bisheng.approval.domain.ports.decision_subscriber import ApprovalDecisionEvent
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber import (
    KnowledgeSpaceFileChangeDecisionSubscriber,
)
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

PREFIX = f"e2e-f046-{uuid4().hex[:8]}-"
TENANT_ID = 74601
OTHER_TENANT_ID = 74602
SPACE_ID = 6401
OWNER_ID = 9201
MANAGER_ID = 9202
REPLACEMENT_MANAGER_ID = 9203
EDITOR_ID = 9204

TOKENS = {
    "e2e-f046-owner": (TENANT_ID, OWNER_ID),
    "e2e-f046-manager": (TENANT_ID, MANAGER_ID),
    "e2e-f046-replacement": (TENANT_ID, REPLACEMENT_MANAGER_ID),
    "e2e-f046-editor": (TENANT_ID, EDITOR_ID),
    "e2e-f046-other": (OTHER_TENANT_ID, EDITOR_ID),
}


class SubmitBody(BaseModel):
    action: str
    resource_name: str = Field(min_length=1)


class DecisionBody(BaseModel):
    action: str


class ApproverBody(BaseModel):
    user_ids: list[int]


@dataclass(slots=True)
class _ApprovalFact:
    instance_id: int
    task_id: int
    request_id: int
    status: str = "pending"
    event: ApprovalDecisionEvent | None = None


class _NoopCleanup:
    async def cleanup(self, **_kwargs):
        return None


class _Harness:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.approvals: dict[int, _ApprovalFact] = {}
        self.current_approvers = {OWNER_ID, MANAGER_ID}
        self.next_instance_id = 2000
        self.next_event_id = 7000
        self.queue: list[int] = []
        self.consumer_enabled = True
        self.worker_enabled = True
        self.fail_next_after_effect = False
        self.effect_calls: list[tuple[int, str]] = []
        self.active_effects: set[tuple[int, str]] = set()
        self.compensation_calls: list[int] = []
        self.state_history: dict[int, list[str]] = {}
        self.subscriber = KnowledgeSpaceFileChangeDecisionSubscriber(
            dispatcher=self,
            terminal_cleanup=_NoopCleanup(),
            session_factory=session_factory,
        )

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        assert tenant_id == TENANT_ID
        if request_id not in self.queue:
            self.queue.append(request_id)

    async def submit(self, *, action: str, resource_name: str) -> _ApprovalFact:
        if action not in {
            KnowledgeSpaceFileChangeAction.UPLOAD,
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
            KnowledgeSpaceFileChangeAction.DELETE,
        }:
            raise ValueError("unsupported action")
        self.next_instance_id += 1
        instance_id = self.next_instance_id
        business_key = f"{PREFIX}{action}:{resource_name}"
        fingerprint = sha256(business_key.encode()).hexdigest()
        resource_type = (
            KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD
            if action == KnowledgeSpaceFileChangeAction.UPLOAD
            else KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE
        )
        async with self.session_factory() as session, session.begin():
            row = KnowledgeSpaceFileChangeRequest(
                tenant_id=TENANT_ID,
                space_id=SPACE_ID,
                action=action,
                resource_type=resource_type,
                resource_id=None if action == KnowledgeSpaceFileChangeAction.UPLOAD else instance_id + 30000,
                applicant_user_id=EDITOR_ID,
                business_key=business_key,
                request_fingerprint=fingerprint,
                approval_instance_id=instance_id,
                file_name=resource_name,
                action_snapshot={
                    "old_name": resource_name,
                    "new_name": f"{resource_name}-renamed",
                    "target_parent_id": 8801,
                },
                execution_state=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
                cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
            )
            session.add(row)
            await session.flush()
            fact = _ApprovalFact(
                instance_id=instance_id,
                task_id=instance_id + 10000,
                request_id=int(row.id),
            )
        self.approvals[instance_id] = fact
        self.state_history[fact.request_id] = [KnowledgeSpaceFileChangeExecutionState.NOT_STARTED]
        return fact

    async def row(self, request_id: int) -> KnowledgeSpaceFileChangeRequest:
        async with self.session_factory() as session:
            result = await session.execute(
                select(KnowledgeSpaceFileChangeRequest).where(KnowledgeSpaceFileChangeRequest.id == request_id)
            )
            row = result.scalars().first()
        assert row is not None
        return row

    async def build_event(
        self,
        *,
        fact: _ApprovalFact,
        decision: str,
        operator_user_id: int,
    ) -> ApprovalDecisionEvent:
        row = await self.row(fact.request_id)
        self.next_event_id += 1
        return ApprovalDecisionEvent(
            event_id=self.next_event_id,
            event_version=1,
            decision_version=1,
            tenant_id=TENANT_ID,
            scenario_code=KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
            approval_instance_id=fact.instance_id,
            business_request_type=KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
            business_request_id=str(fact.request_id),
            business_key=row.business_key,
            request_fingerprint=row.request_fingerprint,
            decision=decision,
            decided_at=datetime.now(UTC),
            operator_user_id=operator_user_id,
        )

    async def run_worker(self, request_id: int) -> dict:
        if not self.worker_enabled:
            return {"request_id": request_id, "dispatched": False}
        if request_id in self.queue:
            self.queue.remove(request_id)
        async with self.session_factory() as session, session.begin():
            row = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert row is not None
            if row.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                return {"request_id": request_id, "status": row.execution_state}
            if row.execution_state not in {
                KnowledgeSpaceFileChangeExecutionState.QUEUED,
                KnowledgeSpaceFileChangeExecutionState.FAILED,
            }:
                raise RuntimeError(f"F046 request cannot run from {row.execution_state}")
            generation = len([state for state in self.state_history[request_id] if state == "applying"]) + 1
            row.execution_token = f"{PREFIX}generation-{generation}"
            row.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
            self.state_history[request_id].append(KnowledgeSpaceFileChangeExecutionState.APPLYING)
            session.add(row)
        row = await self.row(request_id)
        effect = (request_id, row.action)
        if effect not in self.active_effects:
            self.active_effects.add(effect)
            self.effect_calls.append(effect)
        if self.fail_next_after_effect:
            self.fail_next_after_effect = False
            async with self.session_factory() as session, session.begin():
                current = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
                assert current is not None
                current.execution_state = KnowledgeSpaceFileChangeExecutionState.COMPENSATING
                session.add(current)
            self.state_history[request_id].append(KnowledgeSpaceFileChangeExecutionState.COMPENSATING)
            self.active_effects.discard(effect)
            self.compensation_calls.append(request_id)
            async with self.session_factory() as session, session.begin():
                current = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
                assert current is not None
                current.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED
                current.execution_checkpoint = {"failure_reason": "e2e-f046-owner-unavailable"}
                session.add(current)
            self.state_history[request_id].append(KnowledgeSpaceFileChangeExecutionState.FAILED)
            raise RuntimeError("e2e-f046-owner-unavailable")
        async with self.session_factory() as session, session.begin():
            current = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert current is not None
            current.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
            if current.action == KnowledgeSpaceFileChangeAction.UPLOAD:
                current.executed_resource_id = 50000 + request_id
            session.add(current)
        self.state_history[request_id].append(KnowledgeSpaceFileChangeExecutionState.APPLIED)
        return {"request_id": request_id, "status": KnowledgeSpaceFileChangeExecutionState.APPLIED}

    async def retry(self, request_id: int) -> dict:
        row = await self.row(request_id)
        fact = self.approvals[int(row.approval_instance_id)]
        if fact.status != "approved" or row.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED:
            raise ValueError("request is not retryable")
        previous_token = row.execution_token
        async with self.session_factory() as session, session.begin():
            current = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert current is not None
            current.execution_state = KnowledgeSpaceFileChangeExecutionState.QUEUED
            current.execution_token = f"{PREFIX}retry-{uuid4().hex[:8]}"
            current.execution_checkpoint = {}
            session.add(current)
        self.state_history[request_id].append(KnowledgeSpaceFileChangeExecutionState.QUEUED)
        if request_id not in self.queue:
            self.queue.append(request_id)
        return {
            "request_id": request_id,
            "approval_instance_id": fact.instance_id,
            "approval_status": fact.status,
            "previous_execution_token": previous_token,
            "retry_dispatched": True,
        }

    async def cleanup(self) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                delete(KnowledgeSpaceFileChangeRequest).where(
                    KnowledgeSpaceFileChangeRequest.tenant_id == TENANT_ID,
                    KnowledgeSpaceFileChangeRequest.business_key.like(f"{PREFIX}%"),
                )
            )
        self.approvals.clear()
        self.current_approvers = {OWNER_ID, MANAGER_ID}
        self.queue.clear()
        self.consumer_enabled = True
        self.worker_enabled = True
        self.fail_next_after_effect = False
        self.effect_calls.clear()
        self.active_effects.clear()
        self.compensation_calls.clear()
        self.state_history.clear()


def _actor(access_token_cookie: str | None = Cookie(default=None)) -> tuple[int, int]:
    actor = TOKENS.get(str(access_token_cookie))
    if actor is None:
        raise RuntimeError("missing F046 E2E token")
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

    @app.post("/api/v1/e2e-f046/file-changes")
    async def submit(body: SubmitBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != EDITOR_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(tenant_id)
        try:
            fact = await harness.submit(action=body.action, resource_name=body.resource_name)
            return resp_200(
                {
                    "request_id": fact.request_id,
                    "approval_instance_id": fact.instance_id,
                    "task_id": fact.task_id,
                    "decision": "pending",
                }
            )
        finally:
            current_tenant_id.reset(token)

    @app.get("/api/v1/e2e-f046/file-changes/{request_id}")
    async def detail(request_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        token = set_current_tenant_id(tenant_id)
        try:
            row = await harness.row(request_id)
            if int(row.tenant_id) != tenant_id:
                return resp_500(code=18100, message="Approval request does not exist")
            fact = harness.approvals[int(row.approval_instance_id)]
            return resp_200(
                {
                    "request_id": int(row.id),
                    "approval_instance_id": fact.instance_id,
                    "approval_status": fact.status,
                    "execution_state": row.execution_state,
                    "action": row.action,
                    "resource_name": row.file_name,
                    "effect_active": (int(row.id), row.action) in harness.active_effects,
                }
            )
        finally:
            current_tenant_id.reset(token)

    @app.put("/api/v1/e2e-f046/spaces/current-approvers")
    async def replace_approvers(body: ApproverBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != OWNER_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        harness.current_approvers = set(body.user_ids)
        return resp_200({"user_ids": sorted(harness.current_approvers)})

    @app.get("/api/v1/e2e-f046/spaces/current-approvers")
    async def get_approvers(actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        if tenant_id != TENANT_ID:
            return resp_500(code=18100, message="Approval request does not exist")
        return resp_200({"user_ids": sorted(harness.current_approvers)})

    @app.post("/api/v1/e2e-f046/tasks/{task_id}/decision")
    async def decide(task_id: int, body: DecisionBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        fact = next((item for item in harness.approvals.values() if item.task_id == task_id), None)
        if tenant_id != TENANT_ID or fact is None or user_id not in harness.current_approvers:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        if fact.status != "pending" or body.action != "approve":
            return resp_500(code=18102, message="Approval request has already been processed")
        fact.status = "approved"
        fact.event = await harness.build_event(fact=fact, decision="approved", operator_user_id=user_id)
        token = set_current_tenant_id(TENANT_ID)
        try:
            if harness.consumer_enabled:
                await harness.subscriber.accept(fact.event)
        finally:
            current_tenant_id.reset(token)
        return resp_200(
            {"instance_id": fact.instance_id, "status": fact.status, "event_id": fact.event.event_id}
        )

    @app.post("/api/v1/e2e-f046/events/{event_id}/deliver")
    async def deliver(event_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        if tenant_id != TENANT_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        fact = next(
            (item for item in harness.approvals.values() if item.event and item.event.event_id == event_id),
            None,
        )
        assert fact is not None and fact.event is not None
        token = set_current_tenant_id(TENANT_ID)
        try:
            await harness.subscriber.accept(fact.event)
        finally:
            current_tenant_id.reset(token)
        return resp_200({"event_id": event_id, "delivered": True})

    @app.post("/api/v1/e2e-f046/file-changes/{request_id}/run")
    async def run_worker(request_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        if tenant_id != TENANT_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(TENANT_ID)
        try:
            return resp_200(await harness.run_worker(request_id))
        finally:
            current_tenant_id.reset(token)

    @app.post("/api/v1/e2e-f046/file-changes/{request_id}/retry")
    async def retry(request_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != EDITOR_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(TENANT_ID)
        try:
            try:
                result = await harness.retry(request_id)
            except ValueError:
                return resp_500(code=18102, message="Approval request has already been processed")
            return resp_200(result)
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
        await connection.run_sync(KnowledgeSpaceFileChangeRequest.__table__.create)
    harness = _Harness(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    try:
        yield harness
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def client(e2e_harness: _Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_build_app(e2e_harness))
    async with httpx.AsyncClient(transport=transport, base_url="http://e2e-f046.local") as value:
        yield value


@pytest.fixture(autouse=True)
async def double_cleanup(e2e_harness: _Harness):
    """Delete only this run's e2e-f046-prefixed rows before and after every test."""
    await e2e_harness.cleanup()
    try:
        yield
    finally:
        await e2e_harness.cleanup()


def _payload(action: str) -> dict:
    return {"action": action, "resource_name": f"{PREFIX}{action}.txt"}


async def _submit(client: httpx.AsyncClient, action: str) -> dict:
    return _success(
        await client.post(
            "/api/v1/e2e-f046/file-changes",
            json=_payload(action),
            headers=auth_headers("e2e-f046-editor"),
        )
    )


async def _detail(client: httpx.AsyncClient, request_id: int, token: str = "e2e-f046-editor") -> dict:
    return _success(
        await client.get(
            f"/api/v1/e2e-f046/file-changes/{request_id}",
            headers=auth_headers(token),
        )
    )


@pytest.mark.parametrize(
    ("action", "approver_token"),
    (
        (KnowledgeSpaceFileChangeAction.UPLOAD, "e2e-f046-owner"),
        (KnowledgeSpaceFileChangeAction.RENAME, "e2e-f046-manager"),
        (KnowledgeSpaceFileChangeAction.MOVE, "e2e-f046-owner"),
        (KnowledgeSpaceFileChangeAction.DELETE, "e2e-f046-manager"),
    ),
)
async def test_ac20_ac21_ac22_ac23_four_actions_reach_knowledge_effect(
    client: httpx.AsyncClient,
    e2e_harness: _Harness,
    action: str,
    approver_token: str,
) -> None:
    """AC-20/21/22/23: four submissions reach a verified Knowledge-owned effect."""
    created = await _submit(client, action)
    before = await _detail(client, created["request_id"])
    assert before["approval_status"] == "pending"
    assert before["execution_state"] == "not_started"
    decision = _success(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers(approver_token),
        )
    )
    assert decision["status"] == "approved"
    queued = await _detail(client, created["request_id"])
    assert queued["approval_status"] == "approved"
    assert queued["execution_state"] == "queued"
    _success(
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/run",
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    final = await _detail(client, created["request_id"])
    assert final["approval_status"] == "approved"
    assert final["execution_state"] == "applied"
    assert final["effect_active"] is True
    assert e2e_harness.effect_calls == [(created["request_id"], action)]


async def test_ac08_ac09_ac10_dynamic_approver_excludes_former_manager(
    client: httpx.AsyncClient,
) -> None:
    """AC-08/09/10: decision authority follows current owner/manager membership."""
    created = await _submit(client, KnowledgeSpaceFileChangeAction.RENAME)
    _success(
        await client.put(
            "/api/v1/e2e-f046/spaces/current-approvers",
            json={"user_ids": [OWNER_ID, REPLACEMENT_MANAGER_ID]},
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    assert _success(
        await client.get(
            "/api/v1/e2e-f046/spaces/current-approvers",
            headers=auth_headers("e2e-f046-editor"),
        )
    ) == {"user_ids": [OWNER_ID, REPLACEMENT_MANAGER_ID]}
    _error(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-manager"),
        ),
        18101,
        "You do not have permission to access this approval request",
    )
    _success(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-replacement"),
        )
    )
    assert (await _detail(client, created["request_id"]))["approval_status"] == "approved"


async def test_ac24_ac25_failure_compensation_and_original_request_retry(
    client: httpx.AsyncClient,
    e2e_harness: _Harness,
) -> None:
    """AC-24/25: a compensated failure retries the same request and approval terminal fact."""
    created = await _submit(client, KnowledgeSpaceFileChangeAction.MOVE)
    _success(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-manager"),
        )
    )
    e2e_harness.fail_next_after_effect = True
    with pytest.raises(RuntimeError, match="e2e-f046-owner-unavailable"):
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/run",
            headers=auth_headers("e2e-f046-owner"),
        )
    failed = await _detail(client, created["request_id"])
    assert failed["approval_status"] == "approved"
    assert failed["execution_state"] == "failed"
    assert failed["effect_active"] is False
    assert "compensating" in e2e_harness.state_history[created["request_id"]]
    assert e2e_harness.compensation_calls == [created["request_id"]]

    retried = _success(
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/retry",
            headers=auth_headers("e2e-f046-editor"),
        )
    )
    assert retried["request_id"] == created["request_id"]
    assert retried["approval_instance_id"] == created["approval_instance_id"]
    assert retried["approval_status"] == "approved"
    assert retried["retry_dispatched"] is True
    _success(
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/run",
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    final = await _detail(client, created["request_id"])
    assert final["approval_status"] == "approved"
    assert final["execution_state"] == "applied"
    assert final["effect_active"] is True
    assert len(e2e_harness.approvals) == 1


async def test_ac29_ac30_consumer_worker_recovery_and_redelivery_are_idempotent(
    client: httpx.AsyncClient,
    e2e_harness: _Harness,
) -> None:
    """AC-29/30: consumer/worker recovery and stable-event redelivery are idempotent."""
    created = await _submit(client, KnowledgeSpaceFileChangeAction.UPLOAD)
    e2e_harness.consumer_enabled = False
    decision = _success(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    assert (await _detail(client, created["request_id"]))["execution_state"] == "not_started"
    e2e_harness.worker_enabled = False
    _success(
        await client.post(
            f"/api/v1/e2e-f046/events/{decision['event_id']}/deliver",
            headers=auth_headers("e2e-f046-manager"),
        )
    )
    assert (await _detail(client, created["request_id"]))["execution_state"] == "queued"
    result = _success(
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/run",
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    assert result == {"request_id": created["request_id"], "dispatched": False}
    e2e_harness.worker_enabled = True
    _success(
        await client.post(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}/run",
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    first_final = await _detail(client, created["request_id"])
    assert first_final["approval_status"] == "approved"
    assert first_final["execution_state"] == "applied"

    _success(
        await client.post(
            f"/api/v1/e2e-f046/events/{decision['event_id']}/deliver",
            headers=auth_headers("e2e-f046-manager"),
        )
    )
    assert await _detail(client, created["request_id"]) == first_final
    assert e2e_harness.effect_calls == [(created["request_id"], "upload")]


async def test_ac07_ac34_tenant_and_decision_boundaries(client: httpx.AsyncClient) -> None:
    """AC-07/34: tenant isolation and repeated decisions fail closed with exact errors."""
    created = await _submit(client, KnowledgeSpaceFileChangeAction.DELETE)
    _error(
        await client.get(
            f"/api/v1/e2e-f046/file-changes/{created['request_id']}",
            headers=auth_headers("e2e-f046-other"),
        ),
        18100,
        "Approval request does not exist",
    )
    _error(
        await client.post(
            "/api/v1/e2e-f046/file-changes",
            json=_payload(KnowledgeSpaceFileChangeAction.UPLOAD),
            headers=auth_headers("e2e-f046-other"),
        ),
        18101,
        "You do not have permission to access this approval request",
    )
    _success(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-owner"),
        )
    )
    _error(
        await client.post(
            f"/api/v1/e2e-f046/tasks/{created['task_id']}/decision",
            json={"action": "approve"},
            headers=auth_headers("e2e-f046-owner"),
        ),
        18102,
        "Approval request has already been processed",
    )
