"""T055: ASGI route over a reopened control DB, without a running external provider."""

import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.api.router import knowledge_space_router
from bisheng.knowledge.application import provider_diagnostics as diagnostics
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderBinding as Binding
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderOperation as Op
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.fixtures.table_definitions import TABLE_KNOWLEDGE

URL = "/api/v1/knowledge/space/20/provider-operations"


@pytest.fixture
async def browser(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}"
    writer = create_async_engine(url)
    async with writer.begin() as conn:
        await conn.execute(text(TABLE_KNOWLEDGE))
        await conn.execute(
            text(
                "INSERT INTO knowledge(id,tenant_id,type,state,name,user_id,auth_type) VALUES "
                "(20,7,3,0,'shell',87,'PRIVATE'),(21,7,3,1,'native',87,'PUBLIC'),(22,1,3,1,'foreign',87,'PRIVATE')"
            )
        )
        for table in (Binding, Op):
            await conn.run_sync(table.__table__.create)
    async with async_sessionmaker(writer).begin() as session:
        session.add(
            Binding(tenant_id=7, space_id=20, provider_key="weknora", state="provisioning", active_generation=None)
        )
        for n, tenant, space, kind, phase, state, target in [
            (1, 7, 20, "create_space", "create", "manual_review", "private-kb"),
            (2, 7, 20, "upload", "upload", "reconciling", "private-kb"),
            (3, 7, 20, "private-kind", "private-phase", "private-state", "private-kb-two"),
            (4, 1, 20, "upload", "upload", "failed", "other-tenant"),
            (5, 7, 23, "upload", "upload", "failed", "other-space"),
        ]:
            session.add(
                Op(
                    operation_id=f"00000000-0000-4000-8000-{n:012}",
                    tenant_id=tenant,
                    space_id=space,
                    request_key=f"private-key-{n}",
                    request_hash="private-hash",
                    actor_user_id=87,
                    remote_scope_id="private-scope",
                    remote_kb_id=target,
                    provider_instance_id=1,
                    kind=kind,
                    phase=phase,
                    state=state,
                    attempt=n,
                    generation=2,
                    capability_revision=3,
                    operation_epoch=9,
                    create_time=datetime(2026, 1, 1),
                    last_error_code={1: "manual_review_required", 2: None, 3: "private-raw-error"}.get(n),
                    remote_task_id="private-task",
                    lease_token="private-lease",
                    target_manifest=[
                        {"version_id": 31, "body": "private-document", "endpoint": "private-url"},
                        {"version_id": "private-string"},
                        {"version_id": True},
                        {"version_id": 31},
                    ],
                )
            )
    # Deliberately destroy the writer's pool. The request builds a new session
    # on a different engine pointing at the same persisted database file.
    await writer.dispose()
    reader = create_async_engine(url)
    statements = []
    event.listen(reader.sync_engine, "before_cursor_execute", lambda c, cur, stmt, *args: statements.append(stmt))
    monkeypatch.setattr(diagnostics, "get_async_db_session", async_sessionmaker(reader))
    space_action = AsyncMock()
    monkeypatch.setattr(diagnostics, "require_business_action", space_action)
    app = FastAPI()
    app.include_router(knowledge_space_router, prefix="/api/v1")
    person = SimpleNamespace(user_id=43, tenant_id=7, is_global_super=False)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: person

    @app.exception_handler(BaseErrorCode)
    async def domain_error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    with tenant_execution_scope(7):
        token = set_current_permission_actor(
            PermissionActor(user_id=43, current_tenant_id=7, tenant_admin_tenant_ids=frozenset({7}))
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                yield client, person, space_action, statements
        finally:
            reset_current_permission_actor(token)
            await reader.dispose()


async def test_reopen_unready_paginate_redact_and_never_mutate(browser):
    client, person, space_action, statements = browser

    async def fetch(**params):
        response = await client.get(URL, params=params)
        assert response.status_code == 200 and response.json()["status_code"] == 200
        assert "private-" not in response.text
        return response.json()["data"]

    result = await fetch()
    rows = result["data"]
    assert result["total"] == 3
    assert [row["attempt"] for row in rows] == [3, 2, 1]
    assert [row["state"] for row in rows] == ["unknown", "reconciling", "manual_review"]
    assert [row["error_code"] for row in rows] == ["unknown", None, "manual_review_required"]
    assert rows[0]["kind"] == rows[0]["phase"] == "unknown"
    assert rows[1]["kind"] == rows[1]["phase"] == "upload"
    assert rows[1]["version_ids"] == [31] and rows[0]["version_ids"] == rows[2]["version_ids"] == []
    assert rows[1]["remote_target"] == rows[2]["remote_target"] != rows[0]["remote_target"]
    for row in rows:
        assert set(row) == {
            "operation_id",
            "space_id",
            "version_ids",
            "remote_target",
            "generation",
            "kind",
            "phase",
            "state",
            "error_code",
            "attempt",
            "create_time",
            "capability_revision",
            "capability_state",
            "manual_release_allowed",
        }
        assert re.fullmatch("target-[0-9a-f]{16}", row["remote_target"])
        assert (
            row["space_id"],
            row["generation"],
            row["capability_revision"],
            row["capability_state"],
            row["manual_release_allowed"],
        ) == (20, 2, 3, "unknown", False)
    assert (await fetch(page=1, page_size=2))["data"] + (await fetch(page=2, page_size=2))["data"] == rows
    assert await fetch(page=3, page_size=2) == {"total": 3, "data": []}
    space_action.assert_awaited_with(person, resource_type="knowledge_space", resource_id=20, action="edit")
    assert (await client.get(URL.replace("/20/", "/21/"))).json()["data"] == {"total": 0, "data": []}
    assert (await client.post(URL)).status_code == 405
    assert (await client.get(URL, params={"page_size": 101})).status_code == 422
    assert statements and all(stmt.lstrip().upper().startswith("SELECT") for stmt in statements)


@pytest.mark.parametrize(
    "actor",
    [
        PermissionActor(user_id=43, current_tenant_id=7),
        PermissionActor(user_id=43, current_tenant_id=8, tenant_admin_tenant_ids=frozenset({8})),
        PermissionActor(user_id=43, current_tenant_id=7, super_admin=True, data_scope="restricted"),
    ],
)
async def test_limited_identity_never_reads_ledger(browser, actor):
    client, _, space_action, statements = browser
    token = set_current_permission_actor(actor)
    try:
        assert (await client.get(URL)).json()["status_code"] == UnAuthorizedError.Code
        space_action.assert_not_awaited()
        assert not statements
    finally:
        reset_current_permission_actor(token)


async def test_foreign_space_missing_space_and_denied_action_do_not_reveal_ledger(browser):
    client, _, space_action, statements = browser
    for space in (22, 999):
        assert (await client.get(URL.replace("/20/", f"/{space}/"))).json()["status_code"] == SpaceNotFoundError.Code
    space_action.assert_not_awaited()
    space_action.side_effect = UnAuthorizedError()
    assert (await client.get(URL)).json()["status_code"] == UnAuthorizedError.Code
    with bypass_tenant_filter():
        assert (await client.get(URL)).json()["status_code"] == UnAuthorizedError.Code
    assert space_action.await_count == 1
    assert all("knowledge_provider_operation" not in s for s in statements)


async def test_space_action_resolves_unpublished_shell_but_requires_a_decidable_projection(browser, monkeypatch):
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError
    from bisheng.knowledge.domain.models import knowledge
    from bisheng.knowledge.domain.services.knowledge_permission_service import (
        F048KnowledgeContainerPermissionAdapter,
        KnowledgeContainerDaoPermissionLoader,
    )
    from bisheng.permission.application import business_authorization as auth
    from bisheng.permission.application.resource_authorization import (
        BoundResourceAuthorizationPort,
        ResourceAuthorizationRegistry,
    )

    client, _, _, statements = browser
    monkeypatch.setattr(diagnostics, "require_business_action", auth.require_business_action)
    monkeypatch.setattr(knowledge, "get_async_db_session", diagnostics.get_async_db_session)
    # Keep the real F048 target loader, tenant checks and action gate. Only the
    # permission-version/decision backends stand in for an installed F048 runtime.
    policy = SimpleNamespace(
        get_permission_version=AsyncMock(return_value=(1, "projection")), check_action=AsyncMock(return_value=True)
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=KnowledgeContainerDaoPermissionLoader(policy), permission=policy
    )
    registry = ResourceAuthorizationRegistry()
    registry.register(
        "knowledge_space", BoundResourceAuthorizationPort(resource_type="knowledge_space", adapter=adapter)
    )
    monkeypatch.setattr(auth, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(auth, "get_f048_runtime", AsyncMock(return_value=policy))
    assert (await client.get(URL)).json()["data"]["total"] == 3
    actor, target, action = policy.check_action.await_args.args
    assert (actor.super_admin, target.tenant_id, target.resource_id, action) == (False, 7, "20", "edit")
    statements.clear()
    policy.check_action.return_value = False
    assert (await client.get(URL)).json()["status_code"] == UnAuthorizedError.Code
    policy.get_permission_version.side_effect = PermissionPublishNotReadyError()
    assert (await client.get(URL)).json()["status_code"] == PermissionPublishNotReadyError.Code
    assert all("knowledge_provider_operation" not in s for s in statements)
