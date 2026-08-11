from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, call, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core import database as database_module
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.openfga.exceptions import FGAConnectionError
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.group import Group
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.permission.domain.repositories.grant_subject_query_repository import (
    GrantSubjectQueryRepository,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.models.user import User


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)


@pytest_asyncio.fixture
async def strict_subject_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__,
        UserTenant.__table__,
        User.__table__,
        Department.__table__,
        UserDepartment.__table__,
        Group.__table__,
        UserGroup.__table__,
    ]
    async with engine.begin() as connection:
        user_group_id_column = UserGroup.__table__.c.id
        original_autoincrement = user_group_id_column.autoincrement
        user_group_id_column.autoincrement = False
        try:
            await connection.run_sync(
                lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables)
            )
        finally:
            user_group_id_column.autoincrement = original_autoincrement
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add_all(
                [
                    Tenant(id=17, tenant_code="tenant-17", tenant_name="Tenant 17"),
                    Tenant(id=18, tenant_code="tenant-18", tenant_name="Tenant 18"),
                    User(user_id=7, user_name="u7", password="pwd", delete=0),
                    User(user_id=8, user_name="u8", password="pwd", delete=0),
                    User(user_id=10, user_name="u10", password="pwd", delete=1),
                    User(user_id=11, user_name="u11", password="pwd", delete=0),
                    User(user_id=12, user_name="u12", password="pwd", delete=0),
                    User(user_id=13, user_name="u13", password="pwd", delete=0),
                    UserTenant(user_id=7, tenant_id=17, status="active", is_active=1),
                    UserTenant(user_id=8, tenant_id=18, status="active", is_active=1),
                    UserTenant(user_id=10, tenant_id=17, status="active", is_active=1),
                    UserTenant(user_id=11, tenant_id=17, status="disabled", is_active=1),
                    UserTenant(user_id=12, tenant_id=17, status="active", is_active=None),
                    UserTenant(user_id=13, tenant_id=17, status="active", is_active=1),
                    Department(id=5, dept_id="dept-5", name="D5", tenant_id=17, path="/5/"),
                    Department(id=6, dept_id="dept-6", name="D6", tenant_id=18, path="/6/"),
                    UserDepartment(id=1, user_id=7, department_id=5),
                    UserDepartment(id=2, user_id=8, department_id=5),
                    UserDepartment(id=3, user_id=8, department_id=6),
                    Group(id=9, group_name="G9", tenant_id=17),
                    Group(id=19, group_name="G19", tenant_id=18),
                    UserGroup(id=1, user_id=7, group_id=9, tenant_id=17),
                    UserGroup(id=2, user_id=8, group_id=9, tenant_id=17),
                    UserGroup(id=3, user_id=8, group_id=19, tenant_id=18),
                    UserGroup(id=4, user_id=13, group_id=9, tenant_id=17, is_group_admin=True),
                ]
            )
    yield engine
    await engine.dispose()


@pytest.fixture
def strict_subject_session_factory(strict_subject_engine, monkeypatch):
    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(bind=strict_subject_engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(database_module, "get_async_db_session", session_factory)


async def test_repository_batch_resolves_only_exact_departments_in_explicit_tenant(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.resolve_exact_department_member_user_ids_batch(
        department_ids={5, 6, 999},
        tenant_id=17,
    ) == {5: {7, 8}}


async def test_repository_batch_resolves_only_user_groups_in_explicit_tenant(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.resolve_user_group_member_user_ids_batch(
        group_ids={9, 19, 999},
        tenant_id=17,
    ) == {9: {7, 8, 13}}


async def test_repository_batch_resolves_only_active_user_group_admins(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.resolve_user_group_admin_user_ids_batch(
        group_ids={9, 19, 999},
        tenant_id=17,
    ) == {9: {13}}


async def test_repository_filters_deleted_disabled_historical_and_cross_tenant_users(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.filter_active_user_ids_in_tenant(
        user_ids={7, 8, 10, 11, 12, 999},
        tenant_id=17,
    ) == {7}


async def test_repository_builds_current_member_and_group_admin_subjects(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.resolve_active_subject_strings_for_user(
        user_id=7,
        tenant_id=17,
    ) == {"user:7", "department:5#member", "user_group:9#member"}
    assert await repository.resolve_active_subject_strings_for_user(
        user_id=13,
        tenant_id=17,
    ) == {"user:13", "user_group:9#member", "user_group:9#admin"}


async def test_repository_global_identity_requires_an_active_tenant_membership(
    strict_subject_session_factory,
):
    repository = GrantSubjectQueryRepository()

    assert await repository.is_active_user_in_any_active_tenant(8) is True
    assert await repository.is_active_user_in_any_active_tenant(10) is False


async def test_strict_relation_users_expands_supported_subjects_and_deduplicates():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.side_effect = [
        [
            {"user": "user:7", "relation": "owner", "object": "knowledge_space:101"},
            {"user": "department:5#member", "relation": "owner", "object": "knowledge_space:101"},
            {"user": "department:6#member", "relation": "owner", "object": "knowledge_space:101"},
        ],
        [
            {"user": "user_group:9#member", "relation": "manager", "object": "knowledge_space:101"},
            {"user": "user_group:10#member", "relation": "manager", "object": "knowledge_space:101"},
            {"user": "user:7", "relation": "manager", "object": "knowledge_space:101"},
        ],
    ]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_exact_department_member_user_ids_batch",
            AsyncMock(return_value={5: {7, 8}, 6: {11}}),
        ) as department_members,
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_user_group_member_user_ids_batch",
            AsyncMock(return_value={9: {8, 10}, 10: {12}}),
        ) as group_members,
        patch.object(
            GrantSubjectQueryRepository,
            "filter_active_user_ids_in_tenant",
            AsyncMock(return_value={7, 8, 10, 11, 12}),
        ) as active_users,
    ):
        result = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner", "manager"),
        )

    assert result == {7, 8, 10, 11, 12}
    assert fga.read_tuples.await_args_list == [
        call(object="knowledge_space:101", relation="owner", consistency="HIGHER_CONSISTENCY"),
        call(object="knowledge_space:101", relation="manager", consistency="HIGHER_CONSISTENCY"),
    ]
    department_members.assert_awaited_once_with(department_ids={5, 6}, tenant_id=17)
    group_members.assert_awaited_once_with(group_ids={9, 10}, tenant_id=17)
    active_users.assert_awaited_once_with(user_ids={7, 8, 10, 11, 12}, tenant_id=17)


async def test_strict_relation_users_excludes_users_outside_the_explicit_tenant():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [
        {"user": "department:5#member", "relation": "owner", "object": "knowledge_space:101"}
    ]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_exact_department_member_user_ids_batch",
            AsyncMock(return_value={5: {7, 8, 10}}),
        ),
        patch.object(
            GrantSubjectQueryRepository,
            "filter_active_user_ids_in_tenant",
            AsyncMock(return_value={7}),
        ),
    ):
        result = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner",),
        )

    assert result == {7}


async def test_strict_relation_users_expands_group_admin_and_member_usersets_separately():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [
        {"user": "user_group:9#admin", "relation": "manager", "object": "knowledge_space:101"},
        {"user": "user_group:10#member", "relation": "manager", "object": "knowledge_space:101"},
    ]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_user_group_admin_user_ids_batch",
            AsyncMock(return_value={9: {7}}),
        ) as group_admins,
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_user_group_member_user_ids_batch",
            AsyncMock(return_value={10: {8, 9}}),
        ) as group_members,
        patch.object(
            GrantSubjectQueryRepository,
            "filter_active_user_ids_in_tenant",
            AsyncMock(return_value={7, 8, 9}),
        ),
    ):
        result = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("manager",),
        )

    assert result == {7, 8, 9}
    group_admins.assert_awaited_once_with(group_ids={9}, tenant_id=17)
    group_members.assert_awaited_once_with(group_ids={10}, tenant_id=17)


@pytest.mark.parametrize(
    ("subject", "repository_method", "repository_kwargs"),
    [
        (
            "department:5#member",
            "resolve_exact_department_member_user_ids_batch",
            {"department_ids": {5}, "tenant_id": 17},
        ),
        (
            "user_group:9#member",
            "resolve_user_group_member_user_ids_batch",
            {"group_ids": {9}, "tenant_id": 17},
        ),
    ],
)
async def test_strict_relation_users_rejects_cross_tenant_usersets(
    subject,
    repository_method,
    repository_kwargs,
):
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [{"user": subject, "relation": "owner", "object": "knowledge_space:101"}]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(GrantSubjectQueryRepository, repository_method, AsyncMock(return_value={})) as resolve_userset,
        pytest.raises(ValueError, match="outside tenant"),
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner",),
        )

    resolve_userset.assert_awaited_once_with(**repository_kwargs)


async def test_strict_relation_users_excludes_stale_direct_user_tuple():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [{"user": "user:7", "relation": "owner", "object": "knowledge_space:101"}]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "filter_active_user_ids_in_tenant",
            AsyncMock(return_value=set()),
        ),
    ):
        result = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner",),
        )

    assert result == set()


async def test_strict_relation_users_returns_empty_only_after_authoritative_empty_reads():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = []

    with patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)):
        result = await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner", "manager"),
        )

    assert result == set()
    assert fga.read_tuples.await_count == 2


@pytest.mark.parametrize("context_tenant", [None, 1])
async def test_strict_relation_users_requires_matching_explicit_tenant_context(context_tenant):
    if context_tenant is not None:
        set_current_tenant_id(context_tenant)

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock()) as get_fga,
        pytest.raises(RuntimeError, match="tenant context"),
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner", "manager"),
        )

    get_fga.assert_not_awaited()


async def test_strict_relation_users_missing_fga_client_fails_closed():
    set_current_tenant_id(17)

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=None)),
        pytest.raises(FGAConnectionError),
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner", "manager"),
        )


async def test_strict_relation_users_propagates_fga_read_failure():
    set_current_tenant_id(17)
    fga = AsyncMock()
    failure = FGAConnectionError("offline")
    fga.read_tuples.side_effect = failure

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        pytest.raises(FGAConnectionError) as exc_info,
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner", "manager"),
        )

    assert exc_info.value is failure


async def test_strict_relation_users_propagates_subject_expansion_failure():
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [
        {"user": "department:5#member", "relation": "owner", "object": "knowledge_space:101"}
    ]
    failure = RuntimeError("department store unavailable")

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        patch.object(
            GrantSubjectQueryRepository,
            "resolve_exact_department_member_user_ids_batch",
            AsyncMock(side_effect=failure),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner",),
        )

    assert exc_info.value is failure


@pytest.mark.parametrize(
    "subject",
    [
        "department:5",
        "user_group:9",
        "user:7#member",
        "team:3#member",
        "not-a-subject",
    ],
)
async def test_strict_relation_users_rejects_malformed_or_unknown_subjects(subject):
    set_current_tenant_id(17)
    fga = AsyncMock()
    fga.read_tuples.return_value = [{"user": subject, "relation": "owner", "object": "knowledge_space:101"}]

    with (
        patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)),
        pytest.raises(ValueError, match="Unsupported OpenFGA subject"),
    ):
        await PermissionService.resolve_resource_relation_user_ids_strict(
            tenant_id=17,
            object_type="knowledge_space",
            object_id="101",
            relations=("owner",),
        )


async def test_existing_resource_permission_read_remains_lenient_when_fga_is_missing():
    with patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=None)):
        assert await PermissionService.get_resource_permissions("knowledge_space", "101") == []


async def test_existing_resource_permission_read_remains_lenient_on_fga_failure():
    fga = AsyncMock()
    fga.read_tuples.side_effect = FGAConnectionError("offline")

    with patch.object(PermissionService, "_aget_fga", AsyncMock(return_value=fga)):
        assert await PermissionService.get_resource_permissions("knowledge_space", "101") == []
