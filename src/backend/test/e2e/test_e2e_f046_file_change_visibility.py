"""In-process API E2E coverage for F046 publication and preview gates."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from fastapi import Cookie, Depends, FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.services.knowledge_space_file_publication_guard import (
    KnowledgeSpaceFilePublicationGuard,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import UploadExecutionStepCode
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

PREFIX = f"e2e-f046-{uuid4().hex[:8]}-visibility-"
TENANT_ID = 74611
OTHER_TENANT_ID = 74612
SPACE_ID = 6411
OWNER_ID = 9301
MANAGER_ID = 9302
REPLACEMENT_MANAGER_ID = 9303
EDITOR_ID = 9304

TOKENS = {
    "e2e-f046-v-owner": (TENANT_ID, OWNER_ID),
    "e2e-f046-v-manager": (TENANT_ID, MANAGER_ID),
    "e2e-f046-v-replacement": (TENANT_ID, REPLACEMENT_MANAGER_ID),
    "e2e-f046-v-editor": (TENANT_ID, EDITOR_ID),
    "e2e-f046-v-other": (OTHER_TENANT_ID, EDITOR_ID),
}


class ResourceBody(BaseModel):
    name: str = Field(min_length=1)


class StateBody(BaseModel):
    execution_state: str
    complete_steps: bool = False


class ApproverBody(BaseModel):
    user_ids: list[int]


class _ApproverResolver:
    def __init__(self) -> None:
        self.current = {MANAGER_ID}

    async def is_current_approver(self, *, tenant_id: int, space_id: int, user_id: int) -> bool:
        assert tenant_id == TENANT_ID
        assert space_id == SPACE_ID
        return user_id in self.current


class _VisibilityHarness:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.approvers = _ApproverResolver()
        self.guard = KnowledgeSpaceFilePublicationGuard(
            session_factory=self._session,
            approver_resolver=self.approvers,
        )

    @asynccontextmanager
    async def _session(self):
        async with self.session_factory() as session:
            yield session

    async def create(self, name: str) -> tuple[int, int]:
        async with self.session_factory() as session, session.begin():
            row = KnowledgeSpaceFileChangeRequest(
                tenant_id=TENANT_ID,
                space_id=SPACE_ID,
                action=KnowledgeSpaceFileChangeAction.UPLOAD,
                resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
                resource_id=None,
                applicant_user_id=EDITOR_ID,
                business_key=f"{PREFIX}{name}",
                request_fingerprint=uuid4().hex,
                approval_instance_id=9901,
                file_name=name,
                action_snapshot={"file_name": name},
                execution_state=KnowledgeSpaceFileChangeExecutionState.QUEUED,
                execution_token=f"{PREFIX}generation-1",
                cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
            )
            session.add(row)
            await session.flush()
            request_id = int(row.id)
            resource_id = 60000 + request_id
            row.executed_resource_id = resource_id
            row.execution_checkpoint = {
                "formal_resource_ids": [
                    {
                        "resource_type": KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
                        "resource_id": resource_id,
                    }
                ]
            }
            for step_code in UploadExecutionStepCode.BUSINESS_REQUIRED:
                session.add(
                    KnowledgeSpaceFileChangeExecutionStep(
                        tenant_id=TENANT_ID,
                        request_id=request_id,
                        step_code=step_code,
                        attempt_token=row.execution_token,
                        idempotency_key=f"{PREFIX}{request_id}:{step_code}",
                        state=KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                    )
                )
        return request_id, resource_id

    async def set_state(self, *, request_id: int, state: str, complete_steps: bool) -> None:
        async with self.session_factory() as session, session.begin():
            row = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
            assert row is not None
            row.execution_state = state
            session.add(row)
            await session.execute(
                update(KnowledgeSpaceFileChangeExecutionStep)
                .where(KnowledgeSpaceFileChangeExecutionStep.request_id == request_id)
                .values(
                    state=(
                        KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                        if complete_steps
                        else KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
                    )
                )
            )

    async def resource_ids(self, *, tenant_id: int) -> list[int]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(KnowledgeSpaceFileChangeRequest.executed_resource_id).where(
                    KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
                    KnowledgeSpaceFileChangeRequest.business_key.like(f"{PREFIX}%"),
                )
            )
            rows = result.scalars().all()
        return [int(value) for value in rows if value is not None]

    async def cleanup(self) -> None:
        async with self.session_factory() as session, session.begin():
            result = await session.execute(
                select(KnowledgeSpaceFileChangeRequest.id).where(
                    KnowledgeSpaceFileChangeRequest.tenant_id == TENANT_ID,
                    KnowledgeSpaceFileChangeRequest.business_key.like(f"{PREFIX}%"),
                )
            )
            request_ids = list(result.scalars().all())
            if request_ids:
                await session.execute(
                    delete(KnowledgeSpaceFileChangeExecutionStep).where(
                        KnowledgeSpaceFileChangeExecutionStep.request_id.in_(request_ids)
                    )
                )
                await session.execute(
                    delete(KnowledgeSpaceFileChangeRequest).where(
                        KnowledgeSpaceFileChangeRequest.id.in_(request_ids)
                    )
                )
        self.approvers.current = {MANAGER_ID}


def _actor(access_token_cookie: str | None = Cookie(default=None)) -> tuple[int, int]:
    actor = TOKENS.get(str(access_token_cookie))
    if actor is None:
        raise RuntimeError("missing F046 visibility E2E token")
    return actor


def _success(response: httpx.Response):
    data = assert_resp_200(response)
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": data}
    return data


def _error(response: httpx.Response, code: int, message: str):
    body = assert_resp_error(response, code)
    assert body == {"status_code": code, "status_message": message, "data": None}
    return body


def _build_app(harness: _VisibilityHarness) -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/e2e-f046/visibility/resources")
    async def create_resource(body: ResourceBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != EDITOR_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(TENANT_ID)
        try:
            request_id, resource_id = await harness.create(body.name)
            return resp_200(
                {
                    "request_id": request_id,
                    "resource_id": resource_id,
                    "approval_status": "approved",
                    "execution_state": "queued",
                }
            )
        finally:
            current_tenant_id.reset(token)

    @app.post("/api/v1/e2e-f046/visibility/requests/{request_id}/state")
    async def set_state(request_id: int, body: StateBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != OWNER_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        token = set_current_tenant_id(TENANT_ID)
        try:
            await harness.set_state(
                request_id=request_id,
                state=body.execution_state,
                complete_steps=body.complete_steps,
            )
            return resp_200(
                {
                    "request_id": request_id,
                    "approval_status": "approved",
                    "execution_state": body.execution_state,
                    "complete_steps": body.complete_steps,
                }
            )
        finally:
            current_tenant_id.reset(token)

    @app.put("/api/v1/e2e-f046/visibility/current-approvers")
    async def set_approvers(body: ApproverBody, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        if tenant_id != TENANT_ID or user_id != OWNER_ID:
            return resp_500(code=18101, message="You do not have permission to access this approval request")
        harness.approvers.current = set(body.user_ids)
        return resp_200({"user_ids": sorted(harness.approvers.current)})

    @app.get("/api/v1/e2e-f046/visibility/resources")
    async def list_resources(actor: tuple[int, int] = Depends(_actor)):
        tenant_id, _ = actor
        token = set_current_tenant_id(tenant_id)
        try:
            candidates = await harness.resource_ids(tenant_id=tenant_id)
            visible = await harness.guard.filter_published_ids(
                tenant_id=tenant_id,
                space_ids=[SPACE_ID],
                resource_ids=candidates,
            )
            return resp_200({"resource_ids": visible})
        finally:
            current_tenant_id.reset(token)

    @app.get("/api/v1/e2e-f046/visibility/resources/{resource_id}")
    async def preview(resource_id: int, actor: tuple[int, int] = Depends(_actor)):
        tenant_id, user_id = actor
        token = set_current_tenant_id(tenant_id)
        try:
            try:
                await harness.guard.require_published_or_stakeholder(
                    tenant_id=tenant_id,
                    space_id=SPACE_ID,
                    resource_id=resource_id,
                    viewer_user_id=user_id,
                )
            except Exception as error:
                if type(error).__name__ != "SpaceFileChangeRequestNotFoundError":
                    raise
                return resp_500(code=18100, message="Approval request does not exist")
            if resource_id not in await harness.resource_ids(tenant_id=tenant_id):
                return resp_500(code=18100, message="Approval request does not exist")
            return resp_200({"resource_id": resource_id, "preview": f"{PREFIX}safe-preview"})
        finally:
            current_tenant_id.reset(token)

    return app


@pytest.fixture(scope="module")
async def visibility_harness() -> AsyncIterator[_VisibilityHarness]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(KnowledgeSpaceFileChangeRequest.__table__.create)
        await connection.run_sync(KnowledgeSpaceFileChangeExecutionStep.__table__.create)
    harness = _VisibilityHarness(async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    try:
        yield harness
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def visibility_client(visibility_harness: _VisibilityHarness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_build_app(visibility_harness))
    async with httpx.AsyncClient(transport=transport, base_url="http://e2e-f046-visibility.local") as value:
        yield value


@pytest.fixture(autouse=True)
async def double_cleanup(visibility_harness: _VisibilityHarness):
    """Delete only this run's e2e-f046-prefixed rows before and after every test."""
    await visibility_harness.cleanup()
    try:
        yield
    finally:
        await visibility_harness.cleanup()


async def _create(visibility_client: httpx.AsyncClient) -> dict:
    return _success(
        await visibility_client.post(
            "/api/v1/e2e-f046/visibility/resources",
            json={"name": f"{PREFIX}report.pdf"},
            headers=auth_headers("e2e-f046-v-editor"),
        )
    )


async def test_ac27_ac28_publish_gate_requires_applied_request_and_all_steps(
    visibility_client: httpx.AsyncClient,
) -> None:
    """AC-27/28: list publication waits for applied state and every authoritative step."""
    created = await _create(visibility_client)
    assert _success(
        await visibility_client.get(
            "/api/v1/e2e-f046/visibility/resources",
            headers=auth_headers("e2e-f046-v-editor"),
        )
    ) == {"resource_ids": []}
    _success(
        await visibility_client.post(
            f"/api/v1/e2e-f046/visibility/requests/{created['request_id']}/state",
            json={"execution_state": "failed", "complete_steps": False},
            headers=auth_headers("e2e-f046-v-owner"),
        )
    )
    assert _success(
        await visibility_client.get(
            "/api/v1/e2e-f046/visibility/resources",
            headers=auth_headers("e2e-f046-v-editor"),
        )
    ) == {"resource_ids": []}
    applied_incomplete = _success(
        await visibility_client.post(
            f"/api/v1/e2e-f046/visibility/requests/{created['request_id']}/state",
            json={"execution_state": "applied", "complete_steps": False},
            headers=auth_headers("e2e-f046-v-owner"),
        )
    )
    assert applied_incomplete["approval_status"] == "approved"
    assert _success(
        await visibility_client.get(
            "/api/v1/e2e-f046/visibility/resources",
            headers=auth_headers("e2e-f046-v-editor"),
        )
    ) == {"resource_ids": []}
    _success(
        await visibility_client.post(
            f"/api/v1/e2e-f046/visibility/requests/{created['request_id']}/state",
            json={"execution_state": "applied", "complete_steps": True},
            headers=auth_headers("e2e-f046-v-owner"),
        )
    )
    assert _success(
        await visibility_client.get(
            "/api/v1/e2e-f046/visibility/resources",
            headers=auth_headers("e2e-f046-v-editor"),
        )
    ) == {"resource_ids": [created["resource_id"]]}


async def test_ac05_ac08_dynamic_stakeholder_preview_and_former_approver_denial(
    visibility_client: httpx.AsyncClient,
) -> None:
    """AC-05/08: unpublished preview is safe and follows the current approver set."""
    created = await _create(visibility_client)
    for token in ("e2e-f046-v-editor", "e2e-f046-v-manager"):
        preview = _success(
            await visibility_client.get(
                f"/api/v1/e2e-f046/visibility/resources/{created['resource_id']}",
                headers=auth_headers(token),
            )
        )
        assert preview == {"resource_id": created["resource_id"], "preview": f"{PREFIX}safe-preview"}
    _error(
        await visibility_client.get(
            f"/api/v1/e2e-f046/visibility/resources/{created['resource_id']}",
            headers=auth_headers("e2e-f046-v-replacement"),
        ),
        18100,
        "Approval request does not exist",
    )
    _success(
        await visibility_client.put(
            "/api/v1/e2e-f046/visibility/current-approvers",
            json={"user_ids": [REPLACEMENT_MANAGER_ID]},
            headers=auth_headers("e2e-f046-v-owner"),
        )
    )
    _error(
        await visibility_client.get(
            f"/api/v1/e2e-f046/visibility/resources/{created['resource_id']}",
            headers=auth_headers("e2e-f046-v-manager"),
        ),
        18100,
        "Approval request does not exist",
    )
    _success(
        await visibility_client.get(
            f"/api/v1/e2e-f046/visibility/resources/{created['resource_id']}",
            headers=auth_headers("e2e-f046-v-replacement"),
        )
    )


async def test_ac07_tenant_isolation_hides_pending_resource(visibility_client: httpx.AsyncClient) -> None:
    """AC-07: another tenant cannot enumerate or preview a pending F046 resource."""
    created = await _create(visibility_client)
    assert _success(
        await visibility_client.get(
            "/api/v1/e2e-f046/visibility/resources",
            headers=auth_headers("e2e-f046-v-other"),
        )
    ) == {"resource_ids": []}
    _error(
        await visibility_client.get(
            f"/api/v1/e2e-f046/visibility/resources/{created['resource_id']}",
            headers=auth_headers("e2e-f046-v-other"),
        ),
        18100,
        "Approval request does not exist",
    )
