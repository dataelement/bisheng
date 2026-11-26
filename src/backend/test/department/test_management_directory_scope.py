"""The management view follows business mounts, while directory storage remains unchanged."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import delete, select

from bisheng.common.errcode.department import DepartmentPermissionDeniedError
from bisheng.common.request_scope import admitted_request_scope
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id, tenant_execution_scope
from bisheng.database.models.department import Department
from bisheng.department.domain.schemas.department_schema import DepartmentMoveRequest, DepartmentUpdate
from bisheng.department.domain.services import department_service as service
from bisheng.department.domain.services.directory_scope import organization_directory_scope, own_primary_department
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def directory_db(policy_db, monkeypatch):
    from bisheng.department.domain.repositories import (
        directory_repository,
        management_search_repository,
        organization_search_repository,
    )
    from bisheng.user.domain.repositories import management_search_repository as users

    for module in (directory_repository, organization_search_repository, management_search_repository, service):
        monkeypatch.setattr(module, "get_async_db_session", policy_db.sessions)
    monkeypatch.setattr(directory_repository, "get_sync_db_session", policy_db.sync_sessions)
    monkeypatch.setattr(users, "get_sync_db_session", policy_db.sync_sessions)
    import bisheng.user.domain.models.user as user_models

    monkeypatch.setattr(user_models, "get_async_db_session", policy_db.sessions)
    import bisheng.database.models.tenant as tenant_models

    monkeypatch.setattr(tenant_models, "get_async_db_session", policy_db.sessions)
    return policy_db


def actor():
    return SimpleNamespace(
        user_id=191, tenant_id=1, is_global_super=True, user_role=[1], user_name="operator", is_admin=lambda: True
    )


@pytest.fixture
def selected():
    def select_target(tenant_id, kind="tenant"):
        return admitted_request_scope.set(
            SimpleNamespace(tenant_id=tenant_id, home_tenant_id=1, user_id=191, is_super=True, kind=kind)
        )

    return select_target


async def test_child_tree_search_and_write_stay_in_mounted_subtree(directory_db, selected):
    from bisheng.department.domain.services.organization_search_service import OrganizationSearchService

    token = selected(2)
    try:
        with tenant_execution_scope(2):
            async with organization_directory_scope():
                assert get_current_tenant_id() == 1  # physical directory storage, never a fake actor Home
                assert [row["id"] for row in await service.DepartmentService.aget_children_layer(actor())] == [20]
                assert [row["id"] for row in await service.DepartmentService.aget_children_layer(actor(), 20)] == [30]
                result = await OrganizationSearchService.search(actor(), "B", "departments", 1, 20, False, None)
                assert result == {"data": [], "total": 0}
                await service.DepartmentService.aupdate_department("a-leaf", DepartmentUpdate(name="updated"), actor())
                with pytest.raises(DepartmentPermissionDeniedError):
                    await service.DepartmentService.aupdate_department("b", DepartmentUpdate(name="forbidden"), actor())
                with pytest.raises(DepartmentPermissionDeniedError):
                    await service.DepartmentService.amove_department(
                        "a-leaf", DepartmentMoveRequest(new_parent_id=40), actor()
                    )
            assert get_current_tenant_id() == 2
        with bypass_tenant_filter():
            async with directory_db.sessions() as session:
                assert (await session.get(Department, 30)).name == "updated"
                assert (await session.get(Department, 40)).name == "B"
                assert {row.tenant_id for row in (await session.exec(select(Department))).all()} == {1}
    finally:
        admitted_request_scope.reset(token)


async def test_root_view_excludes_child_mounts_before_counts_and_flags(directory_db, selected):
    from bisheng.department.domain.services.organization_search_service import OrganizationSearchService

    token = selected(1)
    try:
        async with organization_directory_scope():
            roots = await service.DepartmentService.aget_children_layer(actor())
            assert [row["id"] for row in roots] == [10]
            assert roots[0]["has_children"] is False
            assert await service.DepartmentService.aget_children_layer(actor(), 10) == []
            result = await OrganizationSearchService.search(actor(), "A", "departments", 1, 20, False, None)
            assert result == {"data": [], "total": 0}
    finally:
        admitted_request_scope.reset(token)


async def test_archived_child_is_hidden_and_cannot_receive_a_knowledge_space(directory_db, selected):
    from bisheng.common.errcode.department import DepartmentNotFoundError
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    with bypass_tenant_filter():
        async with directory_db.sessions() as session:
            (await session.get(Department, 30)).status = "archived"
            await session.commit()
    token = selected(2)
    try:
        async with organization_directory_scope():
            assert [row["id"] for row in await service.DepartmentService.aget_children_layer(actor(), 20)] == []
        with pytest.raises(DepartmentNotFoundError):
            await DepartmentKnowledgeSpaceService._load_departments([30])
    finally:
        admitted_request_scope.reset(token)


async def test_child_directory_department_loads_for_its_management_view(directory_db, selected):
    from bisheng.common.errcode.department import DepartmentPermissionDeniedError
    from bisheng.core.context.tenant import management_tenant_scope
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    token = selected(2)
    try:
        with management_tenant_scope(2):
            loaded = await DepartmentKnowledgeSpaceService._load_departments([30])
            assert loaded[30].tenant_id == 1
            assert loaded[30].name == "leaf"
    finally:
        admitted_request_scope.reset(token)
    token = selected(1)
    try:
        with management_tenant_scope(1):
            with pytest.raises(DepartmentPermissionDeniedError):
                await DepartmentKnowledgeSpaceService._load_departments([30])
    finally:
        admitted_request_scope.reset(token)


async def test_foreign_affiliate_visible_without_leaking_primary_path(directory_db, selected):
    from bisheng.department.domain.services.organization_search_service import OrganizationSearchService

    token = selected(3)
    try:
        async with organization_directory_scope():
            result = await OrganizationSearchService.search(actor(), "policy", "members", 1, 20, False, None)
            assert result["total"] == 1
            assert result["data"][0]["department"]["id"] == 40
            assert result["data"][0]["department"]["path"] == "B"
            assert result["data"][0]["is_primary"] is False
            with pytest.raises(DepartmentPermissionDeniedError):
                await service._check_permission(actor(), 30)
    finally:
        admitted_request_scope.reset(token)


async def test_archived_department_is_readable_but_cannot_be_edited(directory_db, selected):
    with bypass_tenant_filter():
        async with directory_db.sessions() as session:
            (await session.get(Department, 30)).status = "archived"
            await session.commit()
    from bisheng.common.errcode.department import DepartmentArchivedReadonlyError

    token = selected(2)
    try:
        async with organization_directory_scope():
            assert (await service.DepartmentService.aget_department("a-leaf", actor()))["status"] == "archived"
            with pytest.raises(DepartmentArchivedReadonlyError):
                await service.DepartmentService.aupdate_department("a-leaf", DepartmentUpdate(name="invalid"), actor())
    finally:
        admitted_request_scope.reset(token)


async def test_existing_mount_is_revalidated_before_write(directory_db, selected):
    token = selected(2)
    try:
        async with organization_directory_scope():
            with bypass_tenant_filter():
                async with directory_db.sessions() as session:
                    mount = await session.get(Department, 20)
                    mount.is_tenant_root = 0
                    mount.mounted_tenant_id = None
                    await session.commit()
            with pytest.raises(DepartmentPermissionDeniedError):
                await service.DepartmentService.aupdate_department("a-leaf", DepartmentUpdate(name="invalid"), actor())
    finally:
        admitted_request_scope.reset(token)


async def test_gateway_primary_department_keeps_real_identity_and_self_only(directory_db, selected):
    from bisheng.common.errcode.http_error import UnAuthorizedError

    token = selected(3, kind="identity")
    try:
        async with organization_directory_scope():
            user = SimpleNamespace(user_id=77, tenant_id=2)
            assert await own_primary_department(77, user) == [{"id": 30, "dept_id": "a-leaf", "name": "leaf"}]
            with pytest.raises(UnAuthorizedError):
                await own_primary_department(78, user)
    finally:
        admitted_request_scope.reset(token)


async def test_user_picker_includes_affiliates_and_preserves_home_accounts(directory_db, selected):
    from bisheng.user.domain.repositories.management_search_repository import ManagementSearchRepository

    token = selected(3)
    try:
        with tenant_execution_scope(3):
            rows, total = ManagementSearchRepository.list_users()
            assert total == 1 and [row.user_id for row in rows] == [77]
            ids, labels = ManagementSearchRepository.department_hints([77])
            assert ids == {77: 40} and labels == {40: "B"}
    finally:
        admitted_request_scope.reset(token)
    token = selected(1)
    try:
        with tenant_execution_scope(1):
            rows, total = ManagementSearchRepository.list_users()
            assert total == 1 and [row.user_id for row in rows] == [78]
    finally:
        admitted_request_scope.reset(token)


async def test_ordinary_tenant_admin_is_clamped_to_own_business_mount(directory_db, selected, monkeypatch):
    monkeypatch.setattr(service, "_is_tenant_admin", AsyncMock(return_value=True))
    token = selected(2)
    try:
        ordinary = SimpleNamespace(user_id=77, tenant_id=2, is_global_super=False, user_role=[])
        async with organization_directory_scope():
            assert [row["id"] for row in await service.DepartmentService.aget_children_layer(ordinary)] == [20]
            with pytest.raises(DepartmentPermissionDeniedError):
                await service.DepartmentService.aget_children_layer(ordinary, 40)
    finally:
        admitted_request_scope.reset(token)


async def test_account_admin_rejects_foreign_home_even_for_a_visible_affiliate(directory_db, selected):
    from bisheng.common.errcode.role import RolePermissionDeniedError
    from bisheng.user.application.management_subject import require_management_subject

    token = selected(3)
    try:
        with pytest.raises(RolePermissionDeniedError):
            await require_management_subject(77)
    finally:
        admitted_request_scope.reset(token)


async def test_root_cannot_move_an_ancestor_of_a_child_mount(directory_db, selected):
    with bypass_tenant_filter():
        async with directory_db.sessions() as session:
            session.add(
                Department(id=15, dept_id="root-branch", name="Branch", tenant_id=1, parent_id=10, path="/10/15/")
            )
            (await session.get(Department, 20)).parent_id = 15
            (await session.get(Department, 20)).path = "/10/15/20/"
            (await session.get(Department, 30)).path = "/10/15/20/30/"
            await session.commit()
    token = selected(1)
    try:
        async with organization_directory_scope():
            with pytest.raises(DepartmentPermissionDeniedError):
                await service.DepartmentService.amove_department(
                    "root-branch", DepartmentMoveRequest(new_parent_id=10), actor()
                )
    finally:
        admitted_request_scope.reset(token)


async def test_foreign_affiliation_form_cannot_apply_a_context_role(directory_db, selected, monkeypatch):
    from bisheng.common.errcode.department import DepartmentInvalidRolesError
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.database.models.user_role import UserRole
    from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

    with bypass_tenant_filter():
        async with directory_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.role_id == 1))
            await session.commit()
    monkeypatch.setattr(UserGroupDao, "aget_user_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(service.DepartmentService, "_manageable_group_options", AsyncMock(return_value=[]))
    token = selected(3)
    try:
        async with organization_directory_scope():
            form = await service.DepartmentService.aget_member_edit_form("b", 77, actor())
            assert form["policy_editable"] is False
            assert form["role_apply_status"] == "NOT_APPLICABLE_CROSS_TENANT"
            assert form["context_role_ids"] == []
            assert form["assignable_roles_catalog"]["b"] == []
            with pytest.raises(DepartmentInvalidRolesError):
                await service.DepartmentService.aapply_member_edit(
                    "b", 77, DepartmentMemberEditApply(context_role_ids=[4]), actor()
                )
    finally:
        admitted_request_scope.reset(token)


async def test_department_http_keeps_business_headers_and_real_actor_home(directory_db, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.admin.application import request_admission
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.request_scope import RequestScope, ScopedAPIRouter
    from bisheng.department.api.router import router

    user = actor()
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    monkeypatch.setattr(
        request_admission, "request_target", AsyncMock(return_value=SimpleNamespace(tenant_id=2, source="selected"))
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    root = ScopedAPIRouter()
    root.include_router(router, request_scope=RequestScope.TENANT)
    app.include_router(root, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    request_admission.install_request_admission(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/v1/departments/children", headers={"X-Management-Tenant": "2"})
        denied = await client.get("/api/v1/departments/children?parent_id=10", headers={"X-Management-Tenant": "2"})
    assert result.json()["status_code"] == 200
    assert [row["id"] for row in result.json()["data"]] == [20]
    assert result.headers["X-Management-Tenant"] == "2"
    assert denied.json()["status_code"] == 21009
    assert user.tenant_id == 1


async def test_legacy_user_creation_in_child_view_initializes_the_selected_mount(directory_db, selected, monkeypatch):
    from unittest.mock import Mock

    from starlette.requests import Request

    from bisheng.api.services.audit_log import AuditLogService
    from bisheng.user.application import policy_bindings
    from bisheng.user.domain.services.account_identity_service import AccountIdentityService
    from bisheng.user.domain.services.user import UserService

    monkeypatch.setattr(UserService, "decrypt_md5_password_strict", lambda _: "fixture-only-password-hash")
    account = SimpleNamespace(user_id=99, user_name="created")
    created_in = []

    def create(*args, **kwargs):
        created_in.append(get_current_tenant_id())
        return account

    monkeypatch.setattr(AccountIdentityService, "create_local", create)
    initialize = AsyncMock(return_value=SimpleNamespace(id=2))
    monkeypatch.setattr(service.DepartmentService, "ainitialize_local_member", initialize)
    grant = AsyncMock()
    monkeypatch.setattr(policy_bindings, "grant_policy_bindings", grant)
    monkeypatch.setattr(AuditLogService, "record", Mock())
    token = selected(2)
    try:
        with tenant_execution_scope(2):
            result = await UserService.create_user(
                Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)}),
                actor(),
                SimpleNamespace(user_name="created", external_id="new-account", password="cipher", group_roles=[]),
            )
        assert result is account and created_in == [2]
        initialize.assert_awaited_once()
        assert initialize.call_args.args[1] == "a"
        assert grant.call_args.args[:2] == (99, 2)
    finally:
        admitted_request_scope.reset(token)


async def test_known_grant_names_keep_cross_home_people_and_mounted_department_labels(directory_db, monkeypatch):
    from bisheng.open_api.domain.repositories.service_account_repository import ServiceAccountRepository
    from bisheng.tenant.domain.repositories import permission_subject_repository
    from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory

    monkeypatch.setattr(permission_subject_repository, "get_async_db_session", directory_db.sessions)
    monkeypatch.setattr(ServiceAccountRepository, "get_by_ids", AsyncMock(return_value=[]))
    with tenant_execution_scope(2):
        names = await TenantPermissionSubjectDirectory().display_names((("user", "78"), ("department", "20")))
        assert names == {("user", "78"): "empty", ("department", "20"): "A"}
        records = await permission_subject_repository.PermissionSubjectRepository().load(
            2, (("department", "20"), ("department", "40"))
        )
        assert list(records) == [("department", "20")]
        assert records[("department", "20")].business_tenant_id == 2
        assert records[("department", "20")].storage_tenant_id == 1


async def test_projected_department_subjects_use_business_home_and_stop_at_mount(directory_db, monkeypatch):
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory

    monkeypatch.setattr(UserGroupDao, "aget_user_group", AsyncMock(return_value=[]))
    monkeypatch.setattr(UserGroupDao, "aget_user_admin_group", AsyncMock(return_value=[]))
    with tenant_execution_scope(2):
        subjects = await TenantPermissionSubjectDirectory().actor_projected_subjects(
            SimpleNamespace(subject_type="user", fga_subject="user:77", current_tenant_id=2, user_id=77)
        )
    assert "department:30#member" in subjects
    assert "department:20#subtree_member" in subjects
    assert "department:10#subtree_member" not in subjects
    assert "department:40#member" not in subjects


@pytest.mark.parametrize("global_super", [True, False])
async def test_member_page_uses_business_roles_and_limits_diagnostics(
    directory_db, selected, monkeypatch, global_super
):
    from bisheng.database.models.group import Group
    from bisheng.database.models.user_group import UserGroup
    from bisheng.department.domain.repositories import department_member_repository
    from bisheng.user_group.domain.services import user_group_service

    await directory_db.create(Group, UserGroup)
    monkeypatch.setattr(department_member_repository, "get_async_db_session", directory_db.sessions, raising=False)
    monkeypatch.setattr(user_group_service, "_can_view_all_groups", AsyncMock(return_value=True))
    monkeypatch.setattr(service.DepartmentService, "_aget_department_admin_user_ids", AsyncMock(return_value=[]))
    operator = (
        actor() if global_super else SimpleNamespace(user_id=191, tenant_id=2, user_role=[], is_global_super=False)
    )

    # Permission admission is independent; verify the exact admitted page's enrichment.
    async def authorized_department(session, *args):
        return await session.get(Department, 30)

    monkeypatch.setattr(service, "_get_dept_and_check_permission", authorized_department)
    token = selected(2)
    try:
        with tenant_execution_scope(2):
            async with organization_directory_scope():
                result = await service.DepartmentService.aget_members("a-leaf", 1, 20, "", operator)
                assert get_current_tenant_id() == 1
        member = next(row for row in result["data"] if row["user_id"] == 77)
        assert {role["id"] for role in member["roles"]} == {2, 3, 4, 5}
        assert ("role_binding_issues" in member) is global_super
        if global_super:
            assert member["role_binding_issues"] == []
    finally:
        admitted_request_scope.reset(token)
