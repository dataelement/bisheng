"""Real HTTP/DI/SQL writes retain F048 authorization and scope boundaries."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionFGAUnavailableError
from bisheng.core.context.tenant import current_tenant_id, management_tenant_scope, set_current_tenant_id
from bisheng.knowledge.api import dependencies
from bisheng.knowledge.api.endpoints import knowledge_version as routes
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from test.knowledge_unification import test_kn_version_mutation_repository as native_tests
from test.knowledge_unification.test_kn_version_mutation_repository import database as database
from test.knowledge_unification.test_kn_version_mutation_repository import native as native
from test.knowledge_unification.test_kn_version_mutation_repository import snapshot
from test.knowledge_unification.test_kn_version_mutation_wiring import wired as wired


async def request(wired, operation, *, foreign=False, other_space=False):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[dependencies.get_knowledge_version_service] = lambda: wired.service

    @app.exception_handler(BaseErrorCode)
    async def error_handler(_request, error):
        return JSONResponse(error.return_resp_instance().model_dump())

    file_id, doc_id, version_id = (901, 90, 9001) if foreign else (101, 20, 2001)
    if other_space:
        doc_id, version_id = 30, 3002
    path, body = {
        "link": ("document/link", {"knowledge_file_id": file_id, "target_document_id": doc_id, "space_id": 9702}),
        "merge": (
            "version/merge",
            {"current_knowledge_file_id": file_id if foreign else 201, "source_document_id": 30 if other_space else 10},
        ),
        "primary": (f"version/{version_id}/set-primary", None),
    }[operation]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://offline") as client:
        return await client.post("/api/v1/knowledge/space/" + path, json=body)


@pytest.fixture
def permission_check(wired, monkeypatch):
    async def allowed(user, **kwargs):
        assert user is wired.user
        assert not user.is_global_super
        assert kwargs["resource_type"] == "knowledge_space"
        assert kwargs["resource_id"] == 9700
        assert kwargs["action"] == "edit"
        # Permission I/O occurs after the lock-free read was rolled back.
        assert len(wired.sessions) == 1
        assert not wired.sessions[0].in_transaction()
        assert all("FOR UPDATE" not in sql.upper() for sql, _ in wired.database.queries)
        return True

    check = AsyncMock(side_effect=allowed)
    monkeypatch.setattr("bisheng.permission.application.business_authorization.check_business_action", check)
    return check


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_read_only_user_cannot_mutate_versions_by_direct_http(wired, permission_check, operation):
    before = await snapshot(wired.database)
    permission_check.side_effect = None
    permission_check.return_value = False
    response = await request(wired, operation)
    assert await snapshot(wired.database) == before
    assert response.status_code == 200 and response.json()["status_code"] == UnAuthorizedError.Code
    permission_check.assert_awaited_once()
    assert permission_check.await_args.kwargs["resource_id"] == 9700  # Ignore a supplied space_id.
    assert permission_check.await_args.kwargs["action"] == "edit"
    assert len(wired.sessions) == 1 and not wired.sessions[0].in_transaction()
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_non_admin_with_effective_space_edit_can_use_original_http_endpoints(wired, permission_check, operation):
    response = await request(wired, operation)
    assert response.status_code == 200 and response.json()["status_code"] == 200
    assert response.json()["data"]["document_id"] == 20
    permission_check.assert_awaited_once()
    assert len(wired.sessions) == 2 and all(not session.in_transaction() for session in wired.sessions)


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_permission_runtime_failure_leaves_all_version_data_unchanged(wired, permission_check, operation):
    before = await snapshot(wired.database)
    permission_check.side_effect = PermissionFGAUnavailableError()
    response = await request(wired, operation)
    assert await snapshot(wired.database) == before
    assert response.json()["status_code"] == PermissionFGAUnavailableError.Code
    permission_check.assert_awaited_once()
    assert len(wired.sessions) == 1
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


@pytest.mark.parametrize("super_admin", [False, True])
@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_foreign_tenant_ids_are_unavailable_even_to_root_in_child_view(
    wired, permission_check, operation, super_admin
):
    wired.user.is_global_super = super_admin
    wired.user.tenant_id = 1 if super_admin else 101
    before = await snapshot(wired.database)
    response = await request(wired, operation, foreign=True)
    assert response.json().get("data", {}).get("document_id") is None
    assert response.status_code == 404 or response.json().get("status_code") == 18064
    permission_check.assert_not_awaited()
    assert await snapshot(wired.database) == before


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_moving_the_complete_graph_during_authorization_cannot_reuse_old_space_permission(
    wired, permission_check, operation
):
    moved = None

    async def concurrent_move(*args, **kwargs):
        nonlocal moved
        async with wired.database.engine.begin() as connection:
            await connection.execute(sa.update(Document).where(Document.id.in_([10, 20])).values(knowledge_id=9702))
            await connection.execute(sa.update(File).where(File.id.in_([101, 201, 202])).values(knowledge_id=9702))
        moved = await snapshot(wired.database)
        return True

    permission_check.side_effect = concurrent_move
    response = await request(wired, operation)
    assert response.json()["status_code"] == KnowledgeOperationPlanConflictError.Code
    assert "authorized_space_changed" in response.json()["data"]["reason"]
    assert await snapshot(wired.database) == moved
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_tenant_switch_during_authorization_aborts_before_write_session(wired, permission_check, operation):
    before = await snapshot(wired.database)
    token = set_current_tenant_id(101)
    try:

        async def switched(*args, **kwargs):
            set_current_tenant_id(202)
            return True

        permission_check.side_effect = switched
        response = await request(wired, operation)
        assert response.json()["status_code"] == KnowledgeOperationPlanConflictError.Code
        assert len(wired.sessions) == 1
        assert await snapshot(wired.database) == before
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_root_managed_child_keeps_home_identity_and_uses_actual_child_space(wired, permission_check, operation):
    wired.user.tenant_id = 1
    wired.user.is_global_super = True
    original = wired.user.model_dump()
    permission_check.side_effect = None
    permission_check.return_value = True
    with management_tenant_scope(101):
        response = await request(wired, operation)
    assert response.status_code == 200 and response.json()["status_code"] == 200
    assert permission_check.await_args.args[0] is wired.user
    assert permission_check.await_args.kwargs["resource_id"] == 9700
    assert wired.user.model_dump() == original


@pytest.mark.parametrize("operation", ["link", "merge", "primary"])
async def test_permission_on_one_space_cannot_modify_another_space(wired, permission_check, operation):
    if operation == "primary":
        async with wired.database.engine.begin() as connection:
            await connection.execute(sa.insert(File), native_tests.original.file(302, knowledge_id=9702))
            await connection.execute(sa.insert(Version), native_tests.version(3002, 30, 302, no=2, primary=False))
    before = await snapshot(wired.database)

    async def editor_in_one_space(_user, **kwargs):
        return kwargs["resource_id"] == 9700

    permission_check.side_effect = editor_in_one_space
    response = await request(wired, operation, other_space=True)
    if operation == "primary":
        assert response.json()["status_code"] == UnAuthorizedError.Code
        assert permission_check.await_args.kwargs["resource_id"] == 9702
    else:
        assert response.status_code == 409
        assert permission_check.await_args.kwargs["resource_id"] == 9700
    assert await snapshot(wired.database) == before
    wired.audit_link.assert_not_called()
    wired.audit_primary.assert_not_called()
