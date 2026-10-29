"""Exercise mounted-tenant grant pickers and subject validation with real SQL."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionInvalidResourceError
from bisheng.database.models.department import Department
from bisheng.database.models.tenant import Tenant
from bisheng.permission.api.endpoints import grant_subjects
from bisheng.permission.application.resource_api import F048ResourcePermissionApi
from bisheng.permission.domain.schemas import GrantMutationRequest, VerifiedPermissionTarget
from bisheng.permission.domain.services import grant_subject_service
from bisheng.permission.domain.services.grant_subject_service import GrantSubjectScope
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tenant.domain.repositories import grant_department_repository as queries
from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory


def scope(tenant_id=11, path=None):
    return GrantSubjectScope(tenant_id=tenant_id, department_path=path)


def flatten(nodes):
    return [child for node in nodes for child in [node, *flatten(node["children"])]]


def ids(nodes):
    return [node["id"] for node in flatten(nodes)]


@pytest.fixture()
async def directory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda db: SQLModel.metadata.create_all(db, tables=[Department.__table__, Tenant.__table__])
        )

    @asynccontextmanager
    async def session():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    def dept(identifier, parent, path, tenant=1, **kwargs):
        return Department(
            id=identifier,
            dept_id=f"D{identifier}",
            name=f"Team {identifier}",
            external_id=f"org-{identifier}",
            parent_id=parent,
            path=path,
            tenant_id=tenant,
            **kwargs,
        )

    async with session() as db:
        db.add_all(
            [
                dept(1, None, "/1/"),
                dept(20, 1, "/1/20/", is_tenant_root=1, mounted_tenant_id=11),
                dept(21, 20, "/1/20/21/"),
                dept(22, 21, "/1/20/21/22/"),
                dept(23, 20, "/1/20/23/"),
                dept(24, 20, "/1/20/24/", status="archived"),
                dept(25, 23, "/1/20/23/25/", tenant=12),
                dept(30, 1, "/1/30/", is_tenant_root=1, mounted_tenant_id=12),
                dept(31, 30, "/1/30/31/"),
                dept(100, None, "/100/", tenant=15),
                dept(101, 100, "/100/101/", tenant=15),
                dept(200, 1, "/1/200/", tenant=18, is_tenant_root=1, mounted_tenant_id=18),
                dept(201, 200, "/1/200/201/", tenant=18),
            ]
        )
        for identifier, root_id in [(1, 1), (11, 20), (12, 30), (15, 100), (18, 200), (21, 999), (22, 20), (23, None)]:
            db.add(
                Tenant(
                    id=identifier,
                    tenant_code=f"tenant-{identifier}",
                    tenant_name=f"Tenant {identifier}",
                    root_dept_id=root_id,
                    parent_tenant_id=1 if identifier != 1 else None,
                )
            )
        await db.commit()
    monkeypatch.setattr(queries, "get_async_db_session", session)
    instance = TenantPermissionSubjectDirectory()
    monkeypatch.setattr(grant_subject_service, "get_grant_subject_directory", AsyncMock(return_value=instance))
    yield instance
    await engine.dispose()


@pytest.mark.parametrize(("tenant_id", "root_id"), [(1, 1), (11, 20), (15, 100), (18, 200)])
async def test_first_layer_uses_authoritative_tenant_root(directory, tenant_id, root_id):
    nodes = await grant_subject_service.list_candidate_department_layer(scope(tenant_id), parent_id=None)
    assert ids(nodes) == [root_id]
    assert nodes[0]["has_children"] is True
    assert nodes[0]["children"] == []


@pytest.mark.parametrize(
    ("parent_id", "expected"), [(20, [21, 23]), (21, [22]), (22, []), (1, []), (30, []), (999, [])]
)
async def test_expand_rejects_parents_outside_the_tenant(directory, parent_id, expected):
    nodes = await grant_subject_service.list_candidate_department_layer(scope(), parent_id=parent_id)
    assert ids(nodes) == expected
    if parent_id == 20:
        assert {node["id"]: node["has_children"] for node in nodes} == {21: True, 23: False}


async def test_search_is_confined_and_does_not_reveal_ancestors_above_mount(directory):
    result = await grant_subject_service.search_candidate_departments(scope(), keyword="org-22", limit=50)
    assert ids(result["roots"]) == [20, 21, 22]
    assert result["total_matches"] == 1
    assert result["truncated"] is False
    assert [node["id"] for node in flatten(result["roots"]) if node["matched"]] == [22]
    assert await directory.candidate_departments(scope(), keyword="org-31", limit=50) == []
    result = await grant_subject_service.search_candidate_departments(scope(), keyword="Team", limit=2)
    assert result["total_matches"] == 2
    assert result["truncated"] is True
    assert set(ids(result["roots"])) <= {20, 21, 22, 23}


async def test_path_tree_starts_at_mount_root(directory):
    result = await grant_subject_service.get_candidate_department_path(scope(), dept_id=22)
    assert ids(result["roots"]) == [20, 21, 22]
    assert result["total_matches"] == 1
    assert result["roots"][0]["parent_id"] == 1


@pytest.mark.parametrize("dept_id", [1, 24, 25, 30, 31, 100, 200, 999])
async def test_locate_and_save_reject_foreign_archived_or_missing_departments(directory, dept_id):
    result = await grant_subject_service.get_candidate_department_path(scope(), dept_id=dept_id)
    assert result == {"roots": [], "total_matches": 0, "truncated": False}
    with pytest.raises(PermissionInvalidResourceError):
        await directory.canonical_source(
            tenant_id=11,
            source_id=7,
            subject_type="department",
            subject_id=str(dept_id),
            userset_relation=None,
            include_children=True,
        )


@pytest.mark.parametrize("dept_id", [20, 21, 22, 23])
@pytest.mark.parametrize("include_children", [False, True])
async def test_save_accepts_mount_and_descendants_without_changing_storage_tenant(directory, dept_id, include_children):
    source = await directory.canonical_source(
        tenant_id=11,
        source_id=7,
        subject_type="department",
        subject_id=str(dept_id),
        userset_relation=None,
        include_children=include_children,
    )
    relation = "subtree_member" if include_children else "member"
    assert source.projected_subject == f"department:{dept_id}#{relation}"
    assert source.source_type == "DEPARTMENT"
    async with queries.get_async_db_session() as db:
        assert (await db.get(Department, dept_id)).tenant_id == 1


async def test_department_bound_space_intersects_the_tenant_subtree(directory):
    bound = scope(path="/1/20/21/")
    assert ids(await grant_subject_service.list_candidate_department_layer(bound, parent_id=None)) == [21]
    assert ids(await grant_subject_service.list_candidate_department_layer(bound, parent_id=21)) == [22]
    assert await grant_subject_service.list_candidate_department_layer(bound, parent_id=20) == []
    result = await grant_subject_service.search_candidate_departments(bound, keyword="org-22", limit=50)
    assert ids(result["roots"]) == [21, 22]
    assert (await grant_subject_service.get_candidate_department_path(bound, dept_id=23))["roots"] == []
    outside = scope(path="/1/30/")
    assert await grant_subject_service.list_candidate_department_layer(outside, parent_id=None) == []
    assert (await grant_subject_service.search_candidate_departments(outside, keyword="Team", limit=50))["roots"] == []


@pytest.mark.parametrize("tenant_id", [21, 22, 23, 999])
async def test_missing_or_inconsistent_root_fails_closed(directory, tenant_id):
    invalid = scope(tenant_id)
    assert await grant_subject_service.list_candidate_department_layer(invalid, parent_id=None) == []
    assert (await grant_subject_service.search_candidate_departments(invalid, keyword="Team", limit=50))["roots"] == []
    assert (await grant_subject_service.get_candidate_department_path(invalid, dept_id=20))["roots"] == []
    with pytest.raises(PermissionInvalidResourceError):
        await directory.canonical_source(
            tenant_id=tenant_id,
            source_id=7,
            subject_type="department",
            subject_id="20",
            userset_relation=None,
            include_children=True,
        )


@pytest.mark.parametrize("change", ["archived_root", "disabled_tenant", "malformed_path"])
async def test_invalid_root_status_or_path_does_not_widen_candidates(directory, change):
    async with queries.get_async_db_session() as db:
        root = await db.get(Department, 20)
        if change == "archived_root":
            root.status = "archived"
        elif change == "disabled_tenant":
            (await db.get(Tenant, 11)).status = "disabled"
        else:
            root.path = "/1/%/"
        await db.commit()
    assert await grant_subject_service.list_candidate_department_layer(scope(), parent_id=None) == []
    assert (await grant_subject_service.search_candidate_departments(scope(), keyword="Team", limit=50))["roots"] == []


async def test_non_admin_workflow_owner_can_use_picker_but_non_manager_is_denied(directory, monkeypatch):
    user = UserPayload(user_id=42, user_name="owner", user_role=[], tenant_id=11)
    registry = SimpleNamespace(resolve=AsyncMock(return_value=SimpleNamespace(tenant_id=11)))
    allowed = AsyncMock(return_value=True)
    monkeypatch.setattr(grant_subjects, "resolve_permission_actor", AsyncMock(return_value=object()))
    monkeypatch.setattr(grant_subjects, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(grant_subjects, "check_business_action", allowed)
    app = FastAPI()
    app.include_router(grant_subjects.router, prefix="/api/v1/permissions")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    root = "/api/v1/permissions/resources/workflow/owned-workflow/grant-subjects/departments"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"{root}/children")
        assert response.status_code == 200
        assert ids(response.json()["data"]) == [20]
        response = await client.get(f"{root}/search", params={"keyword": "org-22"})
        assert ids(response.json()["data"]["roots"]) == [20, 21, 22]
        response = await client.get(f"{root}/22/path-tree")
        assert ids(response.json()["data"]["roots"]) == [20, 21, 22]
        allowed.return_value = False
        for path in ["children", "search?keyword=Team", "22/path-tree"]:
            response = await client.get(f"{root}/{path}")
            assert response.json()["status_code"] == PermissionDeniedError.Code
    assert all(call.kwargs["action"] == "manage_permission" for call in allowed.await_args_list)


@pytest.mark.parametrize(
    ("tenant_id", "dept_id", "valid"),
    [(11, 20, True), (11, 22, True), (15, 100, True), (18, 200, True), (11, 31, False), (11, 1, False)],
)
async def test_grant_mutation_validates_department_before_entering_projection(directory, tenant_id, dept_id, valid):
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=tenant_id,
        resource_type="workflow",
        resource_id="owned-workflow",
        resource_version=1,
        context_version="workflow:owned-workflow:v1",
    )
    resources = SimpleNamespace(resolve=AsyncMock(return_value=target))
    runtime = SimpleNamespace(
        allocate_source_ids=AsyncMock(return_value=(7,)),
        mutate_grants=AsyncMock(return_value=SimpleNamespace(resource_version=2, grants=())),
    )
    api = F048ResourcePermissionApi(resources=resources, runtime=runtime, subjects=directory)
    request = GrantMutationRequest(
        idempotency_key="department-grant",
        expected_resource_version=1,
        expected_catalog_release_id=12,
        changes=[
            {
                "op": "ADD",
                "model_key": "viewer",
                "subject": {"type": "department", "id": str(dept_id), "include_children": True},
            }
        ],
    )
    kwargs = {
        "resource_type": "workflow",
        "resource_id": "owned-workflow",
        "actor": PermissionActor(user_id=42, current_tenant_id=tenant_id),
        "request": request,
    }
    if valid:
        assert (await api.mutate_grants(**kwargs))["resource_version"] == 2
        mutation = runtime.mutate_grants.await_args.kwargs
        assert mutation["target"] == target
        assert mutation["changes"][0].source.projected_subject == f"department:{dept_id}#subtree_member"
        assert mutation["expected_resource_version"] == 1
    else:
        with pytest.raises(PermissionInvalidResourceError):
            await api.mutate_grants(**kwargs)
        runtime.mutate_grants.assert_not_awaited()


@pytest.mark.parametrize("resource_type", ["knowledge_space", "channel"])
async def test_creation_picker_uses_the_same_mounted_department_boundary(directory, resource_type):
    assert ids(await directory.list_department_children(tenant_id=11, resource_type=resource_type, parent_id=None)) == [
        20
    ]
    result = await directory.search_departments(tenant_id=11, resource_type=resource_type, keyword="org-22", limit=50)
    assert ids(result["roots"]) == [20, 21, 22]
    result = await directory.get_department_path(tenant_id=11, resource_type=resource_type, department_id=31)
    assert result["roots"] == []


async def test_large_search_batches_ancestor_and_child_existence_reads(directory):
    async with queries.get_async_db_session() as db:
        db.add_all(
            [
                Department(
                    id=identifier,
                    dept_id=f"D{identifier}",
                    name=f"Team {identifier}",
                    tenant_id=1,
                    parent_id=20,
                    path=f"/1/20/{identifier}/",
                )
                for identifier in range(1000, 1201)
            ]
        )
        await db.commit()
        engine = db.bind.sync_engine
    reads = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.startswith("SELECT"):
            reads.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await grant_subject_service.search_candidate_departments(scope(), keyword="Team", limit=250)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert set(ids(result["roots"])) == {20, 21, 22, 23, *range(1000, 1201)}
    assert result["truncated"] is False
    assert len(reads) <= 10
    # Each batch binds at most 100 IDs plus storage tenant, active status and path.
    assert all(len(parameters) <= 103 for statement, parameters in reads if " IN (" in statement)
