"""Real F083 HTTP routes + SQLite state; no network or customer data mutations."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import Cookie, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.api.endpoints import knowledge_space as endpoint
from bisheng.knowledge.domain.models.folder_deletion import RESERVED_KEY, make_marker
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeFootprint,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.repositories.knowledge_folder_deletion_repository import KnowledgeFolderDeletionRepository
from bisheng.knowledge.domain.services.knowledge_folder_deletion_service import KnowledgeFolderDeletionService
from test.e2e.helpers.api import assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

TENANT = 78301
SPACE = 78301
PREFIX = "e2e-f083-"


class _Owner:
    """Only identity/permission boundaries are controlled; routes/storage are production code."""

    def __init__(self, user_id):
        self.login_user = SimpleNamespace(user_id=user_id)

    async def _load_space_listing_scope(self, space_id, _parent):
        if space_id != SPACE or get_current_tenant_id() != TENANT:
            raise SpaceNotFoundError()
        return SimpleNamespace(id=SPACE), None

    async def _batch_actions(self, _kind, _ids, _actions):
        return {str(SPACE): {"visible"}}

    async def _filter_visible_child_items(self, rows, **_kwargs):
        return rows


@pytest.fixture
async def status_http(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                model.__table__
                for model in (
                    KnowledgeFile,
                    KnowledgeSpaceFileChangeRequest,
                    KnowledgeSpaceFileChangeFootprint,
                    KnowledgeSpaceFileChangeExecutionStep,
                )
            ],
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    token = set_current_tenant_id(TENANT)
    operation_id = str(uuid4())
    try:
        async with sessions() as session, session.begin():
            row = KnowledgeFile(
                id=83,
                tenant_id=TENANT,
                knowledge_id=SPACE,
                user_id=9,
                file_name=f"{PREFIX}{operation_id}",
                file_type=0,
                status=2,
                file_level_path="",
            )
            session.add(row)
        async with sessions() as session, session.begin():
            await KnowledgeFolderDeletionRepository(session, TENANT, SPACE).claim(83, operation_id, 9)
    finally:
        current_tenant_id.reset(token)

    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")

    async def owner(access_token_cookie: str = Cookie()):
        identity = {
            "e2e-f083-owner": (TENANT, 9),
            "e2e-f083-viewer": (TENANT, 10),
            "e2e-f083-other-tenant": (TENANT + 1, 9),
        }[access_token_cookie]
        context = set_current_tenant_id(identity[0])
        try:
            yield _Owner(identity[1])
        finally:
            current_tenant_id.reset(context)

    app.dependency_overrides[get_knowledge_space_service] = owner
    monkeypatch.setattr(
        endpoint, "KnowledgeFolderDeletionService", lambda sid: KnowledgeFolderDeletionService(sid, sessions)
    )

    @app.exception_handler(BaseErrorCode)
    async def domain_error(_request, error):
        return JSONResponse(error.to_dict())

    async def expire():
        context = set_current_tenant_id(TENANT)
        try:
            async with sessions() as session, session.begin():
                row = await session.get(KnowledgeFile, 83)
                row.user_metadata = {
                    RESERVED_KEY: make_marker(operation_id, 9, datetime.now(UTC) - timedelta(minutes=2))
                }
        finally:
            current_tenant_id.reset(context)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://f083.local") as client:
            yield SimpleNamespace(client=client, operation_id=operation_id, expire=expire, sessions=sessions)
    finally:
        await engine.dispose()


def _status_url():
    return f"/api/v1/knowledge/space/{SPACE}/folder-deletions/status"


def _known(harness):
    return {"folder_ids": [83], "known_operations": [{"folder_id": 83, "operation_id": harness.operation_id}]}


async def test_reload_reads_committed_delete_status(status_http):
    """AC-01, AC-02: a new page can observe deletion before the delete completes."""
    result = assert_resp_200(
        await status_http.client.post(_status_url(), json={"folder_ids": [83]}, headers=auth_headers("e2e-f083-owner"))
    )
    assert result["items"][0]["state"] == "running"
    assert result["items"][0]["operation_id"] == status_http.operation_id
    assert "initiator_user_id" not in result["items"][0]


async def test_observer_cannot_recover_another_users_unknown_delete(status_http):
    """AC-05, AC-07: visible observers cannot invalidate the initiator's request."""
    await status_http.expire()
    url = f"/api/v1/knowledge/space/{SPACE}/folder-deletions/{status_http.operation_id}/reconcile"
    item = assert_resp_200(
        await status_http.client.post(url, json={"folder_id": 83}, headers=auth_headers("e2e-f083-viewer"))
    )
    assert item["state"] == "unknown"
    assert item["can_reconcile"] is False
    result = assert_resp_200(
        await status_http.client.post(_status_url(), json=_known(status_http), headers=auth_headers("e2e-f083-owner"))
    )
    assert result["items"][0]["state"] == "unknown"
    assert result["items"][0]["can_reconcile"] is True


async def test_initiator_can_recover_stale_attempt_without_redeleting(status_http):
    """AC-04, AC-05: recovery restores the row only after invalidating the old marker."""
    await status_http.expire()
    item = assert_resp_200(
        await status_http.client.post(
            f"/api/v1/knowledge/space/{SPACE}/folder-deletions/{status_http.operation_id}/reconcile",
            json={"folder_id": 83},
            headers=auth_headers("e2e-f083-owner"),
        )
    )
    assert item["state"] == "failed"
    assert item["failure_reason"] == "interrupted"
    token = set_current_tenant_id(TENANT)
    try:
        async with status_http.sessions() as session:
            row = await session.get(KnowledgeFile, 83)
            assert row.status == 2
            assert row.file_name.startswith(PREFIX)
    finally:
        current_tenant_id.reset(token)


async def test_cross_tenant_status_is_denied(status_http):
    """AC-07: the authenticated tenant cannot enumerate another tenant's folder status."""
    response = await status_http.client.post(
        _status_url(), json=_known(status_http), headers=auth_headers("e2e-f083-other-tenant")
    )
    assert_resp_error(response, 18000)


async def test_status_batch_has_an_input_bound(status_http):
    """AC-08: oversized batches are rejected before repository reads."""
    response = await status_http.client.post(
        _status_url(), json={"folder_ids": list(range(1, 102))}, headers=auth_headers("e2e-f083-owner")
    )
    assert response.status_code == 422
