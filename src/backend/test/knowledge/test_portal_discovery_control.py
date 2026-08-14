from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.database.alembic.versions import (
    v2_6_0_f080_portal_discovery_enabled as migration,
)
from bisheng.knowledge.api.endpoints.knowledge_space import update_space
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrant
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_space_scope_repository_impl import (
    KnowledgeSpaceScopeRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    KnowledgeSpaceInfoResp,
    KnowledgeSpaceUpdateReq,
    ShougangPortalCategoryFileCountItem,
    ShougangPortalDomainFileCountItem,
    ShougangPortalFileSearchResp,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
    PortalDiscoveryResult,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)


def test_scope_model_has_fail_closed_portal_discovery_column() -> None:
    column = KnowledgeSpaceScope.__table__.c.portal_discovery_enabled

    assert isinstance(column.type, sa.Boolean)
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"


@pytest.mark.parametrize(
    ("level", "is_clinic", "expected"),
    [
        (KnowledgeSpaceLevelEnum.PUBLIC, False, True),
        (KnowledgeSpaceLevelEnum.DEPARTMENT, False, True),
        (KnowledgeSpaceLevelEnum.TEAM_KS, True, False),
        (KnowledgeSpaceLevelEnum.TEAM, False, False),
        (KnowledgeSpaceLevelEnum.PERSONAL, False, False),
    ],
)
def test_new_space_portal_discovery_defaults(
    level: KnowledgeSpaceLevelEnum,
    is_clinic: bool,
    expected: bool,
) -> None:
    assert KnowledgeSpaceService._portal_discovery_default_for_scope(
        level=level,
        is_clinic=is_clinic,
    ) is expected


def test_migration_backfills_only_public_and_valid_department_spaces() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    scope = sa.Table(
        "knowledge_space_scope",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("space_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("owner_type", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
    )
    binding = sa.Table(
        "department_knowledge_space",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("space_id", sa.Integer(), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            scope.insert(),
            [
                {
                    "id": 1,
                    "tenant_id": 1,
                    "space_id": 10,
                    "level": "public",
                    "owner_type": "tenant_root_department",
                    "owner_id": 1,
                },
                {
                    "id": 2,
                    "tenant_id": 1,
                    "space_id": 20,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 2,
                },
                {
                    "id": 3,
                    "tenant_id": 1,
                    "space_id": 30,
                    "level": "department",
                    "owner_type": "department",
                    "owner_id": 3,
                },
                {"id": 4, "tenant_id": 1, "space_id": 40, "level": "team_ks", "owner_type": "user", "owner_id": 8},
                {"id": 5, "tenant_id": 1, "space_id": 50, "level": "team", "owner_type": "user", "owner_id": 8},
                {"id": 6, "tenant_id": 1, "space_id": 60, "level": "personal", "owner_type": "user", "owner_id": 8},
            ],
        )
        connection.execute(
            binding.insert(),
            [
                {"id": 1, "tenant_id": 1, "department_id": 2, "space_id": 20},
                {"id": 2, "tenant_id": 1, "department_id": 4, "space_id": 40},
            ],
        )
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            rows = connection.execute(
                sa.text(
                    "SELECT space_id, portal_discovery_enabled "
                    "FROM knowledge_space_scope ORDER BY space_id"
                )
            ).all()
            assert rows == [(10, 1), (20, 1), (30, 0), (40, 0), (50, 0), (60, 0)]

            migration.downgrade()
        finally:
            migration.op = original_op

        columns = {item["name"] for item in sa.inspect(connection).get_columns("knowledge_space_scope")}
        assert "portal_discovery_enabled" not in columns

    engine.dispose()


@pytest.mark.asyncio
async def test_scope_repository_updates_and_reads_in_batches() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "CREATE TABLE knowledge_space_scope ("
                "id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, space_id INTEGER NOT NULL, "
                "level VARCHAR(32) NOT NULL, owner_type VARCHAR(64) NOT NULL, owner_id INTEGER NOT NULL, "
                "created_by INTEGER NOT NULL DEFAULT 0, create_time DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "update_time DATETIME DEFAULT CURRENT_TIMESTAMP, "
                "portal_discovery_enabled BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        await connection.execute(
            sa.text(
                "INSERT INTO knowledge_space_scope "
                "(id, tenant_id, space_id, level, owner_type, owner_id, portal_discovery_enabled) "
                "VALUES (1, 7, 101, 'public', 'tenant_root_department', 9, 0), "
                "(2, 7, 102, 'department', 'department', 10, 1)"
            )
        )

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = KnowledgeSpaceScopeRepositoryImpl(session)
        before = await repository.find_by_space_ids([101, 102])
        assert {int(item.space_id): bool(item.portal_discovery_enabled) for item in before} == {
            101: False,
            102: True,
        }

        updated = await repository.set_portal_discovery_enabled(
            space_id=101,
            enabled=True,
        )
        assert updated.portal_discovery_enabled is True

        candidates = await repository.list_portal_candidates(tenant_id=7)
        assert [int(item.space_id) for item in candidates] == [101, 102]

    await engine.dispose()


@pytest.mark.asyncio
async def test_atomic_space_and_switch_update_rolls_back_the_shared_transaction() -> None:
    scope = _discovery_scope(
        101,
        KnowledgeSpaceLevelEnum.PUBLIC,
        KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
        1,
        False,
    )
    result = Mock(first=Mock(return_value=scope))
    session = Mock(
        exec=AsyncMock(return_value=result),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(side_effect=RuntimeError("commit failed")),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )
    repository = KnowledgeSpaceScopeRepositoryImpl(session)
    space = Knowledge(
        id=101,
        name="更新后名称",
        description="更新后描述",
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=7,
        tenant_id=1,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await repository.update_space_and_portal_discovery(
            space=space,
            enabled=True,
        )

    assert [item.args[0] for item in session.add.call_args_list] == [space, scope]
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_awaited_once()
    session.refresh.assert_not_awaited()


def test_discovery_snapshot_is_deterministic_and_value_sensitive() -> None:
    left = KnowledgeSpaceScopeRepositoryImpl.build_discovery_snapshot(
        scopes=[("department", 20, True), ("public", 10, True)],
        explicit_space_ids=[31, 30],
        explicit_file_ids=[91, 90],
    )
    reordered = KnowledgeSpaceScopeRepositoryImpl.build_discovery_snapshot(
        scopes=[("public", 10, True), ("department", 20, True)],
        explicit_space_ids=[30, 31],
        explicit_file_ids=[90, 91],
    )
    changed = KnowledgeSpaceScopeRepositoryImpl.build_discovery_snapshot(
        scopes=[("public", 10, False), ("department", 20, True)],
        explicit_space_ids=[30, 31],
        explicit_file_ids=[90, 91],
    )

    assert left == reordered
    assert left != changed


def test_edit_contract_exposes_optional_portal_discovery_switch() -> None:
    assert KnowledgeSpaceUpdateReq(portal_discovery_enabled=True).portal_discovery_enabled is True
    payload = KnowledgeSpaceInfoResp(
        id=10,
        name="公共知识库",
        user_id=7,
        type=KnowledgeTypeEnum.SPACE.value,
        portal_discovery_enabled=False,
    )
    assert payload.portal_discovery_enabled is False


@pytest.mark.asyncio
async def test_update_endpoint_forwards_switch_and_returns_authoritative_info() -> None:
    service = Mock()
    service.update_knowledge_space = AsyncMock(return_value={"id": 10})
    service.get_space_info = AsyncMock(
        return_value={"id": 10, "portal_discovery_enabled": True}
    )

    response = await update_space(
        space_id=10,
        req=KnowledgeSpaceUpdateReq(portal_discovery_enabled=True),
        svc=service,
    )

    assert service.update_knowledge_space.await_args.kwargs["portal_discovery_enabled"] is True
    service.get_space_info.assert_awaited_once_with(10)
    assert response.data["portal_discovery_enabled"] is True


@pytest.mark.parametrize(
    ("scope", "binding", "expected"),
    [
        (
            KnowledgeSpaceScope(
                space_id=10,
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
                owner_id=1,
            ),
            None,
            "public",
        ),
        (
            KnowledgeSpaceScope(
                space_id=20,
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=2,
            ),
            DepartmentKnowledgeSpace(space_id=20, department_id=2),
            "department",
        ),
        (
            KnowledgeSpaceScope(
                space_id=30,
                level=KnowledgeSpaceLevelEnum.TEAM_KS,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
                owner_id=7,
            ),
            DepartmentKnowledgeSpace(space_id=30, department_id=3),
            "clinic",
        ),
        (
            KnowledgeSpaceScope(
                space_id=40,
                level=KnowledgeSpaceLevelEnum.TEAM,
                owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
                owner_id=7,
            ),
            None,
            None,
        ),
        (
            KnowledgeSpaceScope(
                space_id=50,
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=5,
            ),
            DepartmentKnowledgeSpace(space_id=50, department_id=6),
            None,
        ),
    ],
)
def test_portal_discovery_kind_uses_persisted_scope_and_binding(
    scope: KnowledgeSpaceScope,
    binding: DepartmentKnowledgeSpace | None,
    expected: str | None,
) -> None:
    assert KnowledgeSpaceService._portal_discovery_kind(scope, binding) == expected


@pytest.mark.asyncio
async def test_update_switch_reuses_edit_permission_and_persists_authoritative_value() -> None:
    login_user = Mock(user_id=7, user_name="管理员", tenant_id=1)
    login_user.is_admin.return_value = False
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=10,
        level=KnowledgeSpaceLevelEnum.PUBLIC,
        owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
        owner_id=1,
        portal_discovery_enabled=False,
    )
    updated_scope = scope.model_copy(update={"portal_discovery_enabled": True})
    service.knowledge_space_scope_repo = Mock(
        find_by_space_id=AsyncMock(return_value=scope),
        update_space_and_portal_discovery=AsyncMock(return_value=updated_scope),
    )
    space = Knowledge(
        id=10,
        name="公共知识库",
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=7,
        tenant_id=1,
    )

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock) as require_permission,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ) as update_space,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.AuditLogDao.ainsert_v2",
            new_callable=AsyncMock,
        ) as write_audit,
    ):
        await service.update_knowledge_space(
            space_id=10,
            portal_discovery_enabled=True,
        )

    require_permission.assert_awaited_once_with("knowledge_space", 10, "edit_space")
    service.knowledge_space_scope_repo.update_space_and_portal_discovery.assert_awaited_once_with(
        space=space,
        enabled=True,
        department_binding=None,
    )
    update_space.assert_not_awaited()
    assert write_audit.await_args.kwargs["metadata"]["old_value"] is False
    assert write_audit.await_args.kwargs["metadata"]["new_value"] is True


@pytest.mark.asyncio
async def test_update_switch_repository_failure_keeps_value_and_records_failed_audit() -> None:
    login_user = Mock(user_id=7, user_name="管理员", tenant_id=1)
    login_user.is_admin.return_value = False
    service = KnowledgeSpaceService(
        request=Mock(headers={"X-Request-ID": "request-1"}),
        login_user=login_user,
    )
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=10,
        level=KnowledgeSpaceLevelEnum.PUBLIC,
        owner_type=KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
        owner_id=1,
        portal_discovery_enabled=False,
    )
    service.knowledge_space_scope_repo = Mock(
        find_by_space_id=AsyncMock(return_value=scope),
        update_space_and_portal_discovery=AsyncMock(side_effect=RuntimeError("write failed")),
    )
    space = Knowledge(
        id=10,
        name="公共知识库",
        type=KnowledgeTypeEnum.SPACE.value,
        user_id=7,
        tenant_id=1,
    )

    with (
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ) as update_space,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.AuditLogDao.ainsert_v2",
            new_callable=AsyncMock,
        ) as write_audit,
    ):
        with pytest.raises(RuntimeError, match="write failed"):
            await service.update_knowledge_space(
                space_id=10,
                description="描述不应先提交",
                portal_discovery_enabled=True,
            )

    assert scope.portal_discovery_enabled is False
    update_space.assert_not_awaited()
    write_audit.assert_awaited_once()
    metadata = write_audit.await_args.kwargs["metadata"]
    assert metadata == {
        "old_value": False,
        "new_value": True,
        "result": "failed",
        "request_id": "request-1",
        "error_type": "RuntimeError",
    }


def _discovery_scope(
    space_id: int,
    level: KnowledgeSpaceLevelEnum,
    owner_type: KnowledgeSpaceOwnerTypeEnum,
    owner_id: int,
    enabled: bool,
    created_by: int = 0,
) -> KnowledgeSpaceScope:
    return KnowledgeSpaceScope(
        id=space_id,
        tenant_id=1,
        space_id=space_id,
        level=level,
        owner_type=owner_type,
        owner_id=owner_id,
        created_by=created_by,
        portal_discovery_enabled=enabled,
    )


@pytest.mark.asyncio
async def test_explicit_binding_filter_does_not_treat_public_default_as_explicit() -> None:
    bindings = [
        {
            "resource_type": "knowledge_space",
            "resource_id": "12",
            "subject_type": "user",
            "subject_id": 7,
            "relation": "viewer",
            "include_children": False,
        },
        {
            "resource_type": "knowledge_space",
            "resource_id": "13",
            "subject_type": "user",
            "subject_id": 8,
            "relation": "viewer",
            "include_children": False,
        },
    ]
    login_user = Mock(user_id=7)
    with (
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
            new_callable=AsyncMock,
            return_value=bindings,
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_current_user_subject_strings",
            new=AsyncMock(return_value={"user:7"}),
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_binding_department_paths",
            new=AsyncMock(return_value={}),
        ),
        patch.object(
            FineGrainedPermissionService,
            "get_current_user_department_paths",
            new=AsyncMock(return_value={}),
        ),
    ):
        result = await FineGrainedPermissionService.filter_object_ids_by_explicit_binding_async(
            login_user,
            "knowledge_space",
            [12, 13, 14],
        )

    assert result == ["12"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("explicit_binding_ids", "expected_explicit_space_ids", "expected_query_space_ids"),
    [
        ([], [11, 20, 40, 50], [10, 11, 20, 21, 30, 40, 50]),
        (["12"], [11, 12, 20, 40, 50], [10, 11, 12, 20, 21, 30, 40, 50]),
    ],
)
async def test_portal_discovery_resolver_separates_configured_spaces_and_single_file_grants(
    explicit_binding_ids: list[str],
    expected_explicit_space_ids: list[int],
    expected_query_space_ids: list[int],
) -> None:
    login_user = Mock(user_id=7, user_name="访问者", tenant_id=1)
    login_user.is_admin.return_value = False
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    scopes = [
        _discovery_scope(10, KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, 1, True),
        _discovery_scope(11, KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, 1, False),
        _discovery_scope(12, KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, 1, False),
        _discovery_scope(20, KnowledgeSpaceLevelEnum.DEPARTMENT, KnowledgeSpaceOwnerTypeEnum.DEPARTMENT, 2, True),
        _discovery_scope(21, KnowledgeSpaceLevelEnum.DEPARTMENT, KnowledgeSpaceOwnerTypeEnum.DEPARTMENT, 3, False),
        _discovery_scope(30, KnowledgeSpaceLevelEnum.TEAM_KS, KnowledgeSpaceOwnerTypeEnum.USER, 8, True),
        _discovery_scope(40, KnowledgeSpaceLevelEnum.TEAM, KnowledgeSpaceOwnerTypeEnum.USER, 8, False),
        _discovery_scope(50, KnowledgeSpaceLevelEnum.PERSONAL, KnowledgeSpaceOwnerTypeEnum.USER, 8, False),
    ]
    bindings = [
        DepartmentKnowledgeSpace(tenant_id=1, space_id=20, department_id=2),
        DepartmentKnowledgeSpace(tenant_id=1, space_id=21, department_id=3),
        DepartmentKnowledgeSpace(tenant_id=1, space_id=30, department_id=4),
    ]
    service.knowledge_space_scope_repo = Mock(list_portal_candidates=AsyncMock(return_value=scopes))
    service.department_space_binding_repo = Mock(find_by_space_ids=AsyncMock(return_value=bindings))
    service.department_file_view_access_service = Mock(
        evaluate_files=AsyncMock(
            return_value={2101: Mock(status="allowed")},
        ),
        grant_repository=Mock(
            list_active_by_user=AsyncMock(
                return_value=[
                    DepartmentFileViewGrant(
                        tenant_id=1,
                        user_id=7,
                        space_id=21,
                        file_id=2101,
                        department_id=3,
                        approval_instance_id=99,
                    )
                ]
            )
        )
    )
    memberships = [Mock(business_id="11"), Mock(business_id="20"), Mock(business_id="40")]

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_get_user_space_members",
            new_callable=AsyncMock,
            return_value=memberships,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.list_accessible_ids",
            new_callable=AsyncMock,
            side_effect=[["11", "12", "50"], []],
        ) as list_accessible_ids,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.filter_object_ids_by_explicit_binding_async",
            new_callable=AsyncMock,
            return_value=explicit_binding_ids,
        ) as filter_explicit_bindings,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
            new_callable=AsyncMock,
            return_value=[
                Mock(id=2, tenant_id=1, status="active", is_deleted=0),
                Mock(id=3, tenant_id=1, status="active", is_deleted=0),
                Mock(id=4, tenant_id=1, status="active", is_deleted=0),
            ],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
            new_callable=AsyncMock,
            return_value=[Mock(id=2101, knowledge_id=21)],
        ),
    ):
        result = await service.resolve_portal_discovery(scope="portal_configured")

    assert result.discoverable_space_ids == [10, 20, 30]
    assert result.explicitly_visible_space_ids == expected_explicit_space_ids
    assert result.explicitly_visible_file_ids == [2101]
    assert result.grant_parent_space_ids == [21]
    assert result.query_space_ids == expected_query_space_ids
    assert result.space_kind_by_id == {
        10: "public",
        11: "public",
        12: "public",
        20: "department",
        21: "department",
        30: "clinic",
        40: "team",
        50: "personal",
    }
    assert [call.kwargs["relation"] for call in list_accessible_ids.await_args_list] == [
        "can_read",
        "can_manage",
    ]
    service.knowledge_space_scope_repo.list_portal_candidates.assert_awaited_once_with(
        tenant_id=1,
    )
    service.department_space_binding_repo.find_by_space_ids.assert_awaited_once_with(
        [10, 11, 12, 20, 21, 30, 40, 50],
    )
    filter_explicit_bindings.assert_awaited_once_with(
        login_user,
        "knowledge_space",
        [12],
    )
    grant_repository = service.department_file_view_access_service.grant_repository
    grant_repository.list_active_by_user.assert_awaited_once_with(tenant_id=1, user_id=7)
    service.department_file_view_access_service.evaluate_files.assert_awaited_once()


@pytest.mark.asyncio
async def test_portal_configured_admin_only_keeps_owned_joined_or_explicit_private_spaces(
) -> None:
    login_user = Mock(user_id=7, user_name="管理员", tenant_id=1)
    login_user.is_admin.return_value = True
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    scopes = [
        _discovery_scope(
            10,
            KnowledgeSpaceLevelEnum.PUBLIC,
            KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT,
            1,
            True,
        ),
        _discovery_scope(
            40,
            KnowledgeSpaceLevelEnum.TEAM,
            KnowledgeSpaceOwnerTypeEnum.USER,
            8,
            False,
        ),
        _discovery_scope(
            41,
            KnowledgeSpaceLevelEnum.TEAM,
            KnowledgeSpaceOwnerTypeEnum.USER,
            7,
            False,
            7,
        ),
        _discovery_scope(
            42,
            KnowledgeSpaceLevelEnum.TEAM,
            KnowledgeSpaceOwnerTypeEnum.USER,
            8,
            False,
        ),
        _discovery_scope(
            43,
            KnowledgeSpaceLevelEnum.TEAM,
            KnowledgeSpaceOwnerTypeEnum.USER,
            8,
            False,
        ),
        _discovery_scope(
            50,
            KnowledgeSpaceLevelEnum.PERSONAL,
            KnowledgeSpaceOwnerTypeEnum.USER,
            8,
            False,
            8,
        ),
        _discovery_scope(
            51,
            KnowledgeSpaceLevelEnum.PERSONAL,
            KnowledgeSpaceOwnerTypeEnum.USER,
            7,
            False,
            7,
        ),
    ]
    service.knowledge_space_scope_repo = Mock(
        list_portal_candidates=AsyncMock(return_value=scopes)
    )
    service.department_space_binding_repo = Mock(
        find_by_space_ids=AsyncMock(return_value=[])
    )
    service.department_file_view_access_service = Mock(grant_repository=None)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_get_user_space_members",
            new_callable=AsyncMock,
            return_value=[Mock(business_id="42"), Mock(business_id="50")],
        ) as get_memberships,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "PermissionService.list_accessible_ids",
            new_callable=AsyncMock,
        ) as list_accessible_ids,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.filter_object_ids_by_explicit_binding_async",
            new_callable=AsyncMock,
            return_value=["43"],
        ) as filter_explicit_bindings,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await service.resolve_portal_discovery(scope="portal_configured")

    assert result.discoverable_space_ids == [10]
    assert result.explicitly_visible_space_ids == [41, 42, 43, 51]
    assert result.query_space_ids == [10, 41, 42, 43, 51]
    get_memberships.assert_awaited_once_with(7)
    list_accessible_ids.assert_not_awaited()
    filter_explicit_bindings.assert_awaited_once_with(
        login_user,
        "knowledge_space",
        [40, 43],
    )


@pytest.mark.asyncio
async def test_portal_public_resolver_only_returns_enabled_public_spaces() -> None:
    login_user = Mock(user_id=0, user_name="", tenant_id=1)
    login_user.is_admin.return_value = False
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    scopes = [
        _discovery_scope(10, KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, 1, True),
        _discovery_scope(11, KnowledgeSpaceLevelEnum.PUBLIC, KnowledgeSpaceOwnerTypeEnum.TENANT_ROOT_DEPARTMENT, 1, False),
        _discovery_scope(20, KnowledgeSpaceLevelEnum.DEPARTMENT, KnowledgeSpaceOwnerTypeEnum.DEPARTMENT, 2, True),
    ]
    service.knowledge_space_scope_repo = Mock(list_portal_candidates=AsyncMock(return_value=scopes))
    service.department_space_binding_repo = Mock(
        find_by_space_ids=AsyncMock(
            return_value=[DepartmentKnowledgeSpace(tenant_id=1, space_id=20, department_id=2)]
        )
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
        new_callable=AsyncMock,
        return_value=[Mock(id=2, tenant_id=1, status="active", is_deleted=0)],
    ):
        result = await service.resolve_portal_discovery(scope="portal_public")

    assert result.discoverable_space_ids == [10]
    assert result.query_space_ids == [10]
    assert result.explicitly_visible_space_ids == []
    assert result.explicitly_visible_file_ids == []


@pytest.mark.asyncio
async def test_portal_discovery_fails_closed_for_archived_binding_department() -> None:
    login_user = Mock(user_id=7, user_name="访问者", tenant_id=1)
    login_user.is_admin.return_value = False
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    scopes = [
        _discovery_scope(
            20,
            KnowledgeSpaceLevelEnum.DEPARTMENT,
            KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            2,
            True,
        ),
        _discovery_scope(
            30,
            KnowledgeSpaceLevelEnum.TEAM_KS,
            KnowledgeSpaceOwnerTypeEnum.USER,
            8,
            True,
        ),
    ]
    service.knowledge_space_scope_repo = Mock(
        list_portal_candidates=AsyncMock(return_value=scopes),
    )
    service.department_space_binding_repo = Mock(
        find_by_space_ids=AsyncMock(
            return_value=[
                DepartmentKnowledgeSpace(tenant_id=1, space_id=20, department_id=2),
                DepartmentKnowledgeSpace(tenant_id=1, space_id=30, department_id=3),
            ],
        ),
    )

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_ids",
        new_callable=AsyncMock,
        return_value=[
            Mock(id=2, tenant_id=1, status="active", is_deleted=0),
            Mock(id=3, tenant_id=1, status="archived", is_deleted=0),
        ],
    ):
        result = await service.resolve_portal_discovery(scope="portal_public")

    assert result.discoverable_space_ids == []
    assert result.space_kind_by_id == {20: "department"}


@pytest.mark.asyncio
async def test_portal_counts_keep_grant_only_parent_at_exact_file_scope() -> None:
    login_user = Mock(user_id=7, user_name="访问者", tenant_id=1)
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    discovery = PortalDiscoveryResult(
        discoverable_space_ids=[10],
        explicitly_visible_space_ids=[20],
        explicitly_visible_file_ids=[3101],
        explicit_file_space_by_id={3101: 30},
        grant_parent_space_ids=[30],
        query_space_ids=[10, 20, 30],
        space_kind_by_id={10: "public", 20: "department", 30: "clinic"},
        snapshot="snapshot-1",
    )

    with (
        patch.object(
            service,
            "resolve_portal_discovery",
            new_callable=AsyncMock,
            return_value=discovery,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_files_by_domain_scopes",
            new_callable=AsyncMock,
            return_value={"PM": 3},
        ) as count_domains,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_files_by_category_scopes",
            new_callable=AsyncMock,
            return_value={"STD": 2},
        ) as count_categories,
    ):
        domain_result = await service.count_shougang_portal_domain_files(
            [ShougangPortalDomainFileCountItem(code="PM", space_ids=[10, 20, 30])],
            discovery_scope="portal_configured",
        )
        category_result = await service.count_shougang_portal_category_files(
            [ShougangPortalCategoryFileCountItem(code="STD", space_ids=[10, 20, 30])],
            discovery_scope="portal_configured",
        )

    assert domain_result == {"PM": 3}
    assert category_result == {"STD": 2}
    count_domains.assert_awaited_once_with(
        {"PM": {10, 20}},
        {"PM": {3101}},
    )
    count_categories.assert_awaited_once_with(
        {"STD": {10, 20}},
        {"STD": {3101}},
    )


@pytest.mark.asyncio
async def test_portal_counts_keep_explicit_empty_card_scope_empty() -> None:
    login_user = Mock(user_id=7, user_name="访问者", tenant_id=1)
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    discovery = PortalDiscoveryResult(
        discoverable_space_ids=[10, 20],
        explicitly_visible_space_ids=[],
        explicitly_visible_file_ids=[],
        explicit_file_space_by_id={},
        grant_parent_space_ids=[],
        query_space_ids=[10, 20],
        space_kind_by_id={10: "public", 20: "department"},
        snapshot="snapshot-1",
    )

    with (
        patch.object(
            service,
            "resolve_portal_discovery",
            new_callable=AsyncMock,
            return_value=discovery,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_files_by_domain_scopes",
            new_callable=AsyncMock,
            return_value={"PM": 0},
        ) as count_domains,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.async_count_files_by_category_scopes",
            new_callable=AsyncMock,
            return_value={"STD": 0},
        ) as count_categories,
    ):
        await service.count_shougang_portal_domain_files(
            [ShougangPortalDomainFileCountItem(code="PM", space_ids=[])],
            discovery_scope="portal_configured",
        )
        await service.count_shougang_portal_category_files(
            [ShougangPortalCategoryFileCountItem(code="STD", space_ids=[])],
            discovery_scope="portal_configured",
        )

    count_domains.assert_awaited_once_with({"PM": set()}, {"PM": set()})
    count_categories.assert_awaited_once_with({"STD": set()}, {"STD": set()})


def test_portal_file_response_preserves_discovery_snapshot() -> None:
    response = ShougangPortalFileSearchResp(
        data=[],
        has_more=False,
        next_cursor=None,
        discovery_snapshot="snapshot-1",
    )

    assert response.model_dump(mode="json")["discovery_snapshot"] == "snapshot-1"


def test_safe_projection_only_redacts_discoverable_space_without_explicit_permission() -> None:
    login_user = Mock(user_id=7, user_name="访问者", tenant_id=1)
    service = KnowledgeSpaceService(request=Mock(headers={}), login_user=login_user)
    service._portal_unchecked_department_file_ids = {101}
    item = {
        "id": 101,
        "file_name": "检修方案.pdf",
        "abstract": "完整摘要",
        "file_size": 1024,
        "file_encoding": "GF-STD-PM-001",
        "source_path": "设备部/检修方案.pdf",
    }

    service._portal_discovery_result = PortalDiscoveryResult(
        discoverable_space_ids=[20],
        explicitly_visible_space_ids=[],
        explicitly_visible_file_ids=[],
        explicit_file_space_by_id={},
        grant_parent_space_ids=[],
        query_space_ids=[20],
        space_kind_by_id={20: "department"},
        snapshot="without-permission",
    )
    redacted = service._map_shougang_portal_file_item(20, item)

    service._portal_discovery_result = PortalDiscoveryResult(
        discoverable_space_ids=[20],
        explicitly_visible_space_ids=[20],
        explicitly_visible_file_ids=[],
        explicit_file_space_by_id={},
        grant_parent_space_ids=[],
        query_space_ids=[20],
        space_kind_by_id={20: "department"},
        snapshot="with-permission",
    )
    authorized = service._map_shougang_portal_file_item(20, item)

    assert redacted.summary == ""
    assert redacted.file_size == ""
    assert redacted.file_encoding == ""
    assert redacted.source_path == ""
    assert authorized.summary == "完整摘要"
    assert authorized.file_size == "1024"
    assert authorized.file_encoding == "GF-STD-PM-001"
    assert authorized.source_path == "设备部/检修方案.pdf"
