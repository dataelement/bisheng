from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceAmbiguousError,
)
from bisheng.core.database.alembic.versions import (
    v2_6_0_f060_department_multiple_spaces as migration,
)
from bisheng.knowledge.domain.models.department_knowledge_space import (
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
)
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService,
)
from bisheng.knowledge.domain.services.department_space_target_resolver import (
    DepartmentSpaceTargetResolver,
)


def _binding(department_id: int, space_id: int) -> SimpleNamespace:
    return SimpleNamespace(department_id=department_id, space_id=space_id)


def _scope(
    space_id: int,
    *,
    level: KnowledgeSpaceLevelEnum,
    owner_type: KnowledgeSpaceOwnerTypeEnum,
    owner_id: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        space_id=space_id,
        level=level,
        owner_type=owner_type,
        owner_id=owner_id,
    )


def test_department_binding_model_only_keeps_space_unique_constraint() -> None:
    constraint_names = {
        constraint.name for constraint in DepartmentKnowledgeSpace.__table__.constraints if constraint.name
    }

    assert "uk_dks_department_id" not in constraint_names
    assert "uk_dks_space_id" in constraint_names


@pytest.mark.asyncio
async def test_resolver_prefers_single_department_space_over_legacy_binding() -> None:
    bindings = [_binding(3, 100), _binding(3, 101)]
    scopes = [
        _scope(
            100,
            level=KnowledgeSpaceLevelEnum.TEAM,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=9,
        ),
        _scope(
            101,
            level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            owner_id=3,
        ),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=bindings),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "KnowledgeSpaceScopeDao.aget_by_space_ids",
            new=AsyncMock(return_value=scopes),
        ),
    ):
        assert await DepartmentSpaceTargetResolver.resolve([3, 1]) == 101


@pytest.mark.asyncio
async def test_resolver_walks_to_nearest_ancestor_without_candidates() -> None:
    bindings = [_binding(2, 200), _binding(1, 100)]
    scopes = [
        _scope(
            200,
            level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            owner_id=2,
        ),
        _scope(
            100,
            level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            owner_id=1,
        ),
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=bindings),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "KnowledgeSpaceScopeDao.aget_by_space_ids",
            new=AsyncMock(return_value=scopes),
        ),
    ):
        assert await DepartmentSpaceTargetResolver.resolve([3, 2, 1]) == 200


@pytest.mark.asyncio
async def test_resolver_rejects_multiple_department_space_candidates() -> None:
    bindings = [_binding(3, 100), _binding(3, 101)]
    scopes = [
        _scope(
            space_id,
            level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
            owner_id=3,
        )
        for space_id in (100, 101)
    ]

    with (
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=bindings),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "KnowledgeSpaceScopeDao.aget_by_space_ids",
            new=AsyncMock(return_value=scopes),
        ),
    ):
        with pytest.raises(DepartmentKnowledgeSpaceAmbiguousError):
            await DepartmentSpaceTargetResolver.resolve([3, 1])


@pytest.mark.asyncio
async def test_resolver_accepts_one_legacy_candidate_and_rejects_multiple() -> None:
    def legacy_scope(space_id: int) -> SimpleNamespace:
        return _scope(
            space_id,
            level=KnowledgeSpaceLevelEnum.TEAM,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER,
            owner_id=9,
        )

    with (
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(3, 100)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "KnowledgeSpaceScopeDao.aget_by_space_ids",
            new=AsyncMock(return_value=[legacy_scope(100)]),
        ),
    ):
        assert await DepartmentSpaceTargetResolver.resolve([3]) == 100

    with (
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(3, 100), _binding(3, 101)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_space_target_resolver."
            "KnowledgeSpaceScopeDao.aget_by_space_ids",
            new=AsyncMock(return_value=[legacy_scope(100), legacy_scope(101)]),
        ),
    ):
        with pytest.raises(DepartmentKnowledgeSpaceAmbiguousError):
            await DepartmentSpaceTargetResolver.resolve([3])


@pytest.mark.asyncio
async def test_admin_changes_are_synchronized_to_every_bound_space() -> None:
    login_user = SimpleNamespace(user_id=1, tenant_id=1)
    bindings = [_binding(3, 20), _binding(3, 10), _binding(3, 20)]

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=bindings),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_added_admin",
            new=AsyncMock(),
        ) as sync_added,
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_removed_admin",
            new=AsyncMock(),
        ) as sync_removed,
    ):
        await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
            request=None,
            login_user=login_user,
            department_id=3,
            added_user_ids=[8],
            removed_user_ids=[9],
        )

    added_space_ids = [one.kwargs["space_id"] for one in sync_added.await_args_list]
    removed_space_ids = [one.kwargs["space_id"] for one in sync_removed.await_args_list]
    assert added_space_ids == [10, 20]
    assert removed_space_ids == [10, 20]
    assert [one.kwargs["user_id"] for one in sync_added.await_args_list] == [8, 8]
    assert [one.kwargs["user_id"] for one in sync_removed.await_args_list] == [9, 9]
    assert (
        sync_added.await_args_list[0].kwargs["space_service"] is (sync_added.await_args_list[1].kwargs["space_service"])
    )


@pytest.mark.asyncio
async def test_admin_sync_propagates_an_unrecoverable_space_failure() -> None:
    login_user = SimpleNamespace(user_id=1, tenant_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[_binding(3, 10), _binding(3, 20)]),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_added_admin",
            new=AsyncMock(side_effect=[None, RuntimeError("authorization failed")]),
        ) as sync_added,
    ):
        with pytest.raises(RuntimeError, match="authorization failed"):
            await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
                request=None,
                login_user=login_user,
                department_id=3,
                added_user_ids=[8],
                removed_user_ids=[],
            )

    assert [one.kwargs["space_id"] for one in sync_added.await_args_list] == [10, 20]


def test_migration_upgrade_drops_department_unique_and_keeps_lookup_index() -> None:
    connection = SimpleNamespace()
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(
            migration,
            "table_exists",
            return_value=True,
        ),
        patch.object(
            migration,
            "constraint_exists",
            side_effect=lambda _conn, _table, name: name == "uk_dks_department_id",
        ),
        patch.object(
            migration,
            "index_exists",
            side_effect=lambda _conn, _table, name: name == "idx_dks_department_id",
        ),
        patch.object(migration.op, "drop_constraint") as drop_constraint,
        patch.object(
            migration.op,
            "create_index",
        ) as create_index,
    ):
        migration.upgrade()

    drop_constraint.assert_called_once_with(
        "uk_dks_department_id",
        "department_knowledge_space",
        type_="unique",
    )
    create_index.assert_not_called()


def test_migration_downgrade_refuses_to_delete_duplicate_bindings() -> None:
    result = SimpleNamespace(first=lambda: (3,))
    connection = SimpleNamespace(execute=lambda _statement: result)
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(
            migration,
            "table_exists",
            return_value=True,
        ),
        patch.object(migration, "constraint_exists", return_value=False),
        patch.object(
            migration,
            "index_exists",
            return_value=False,
        ),
        patch.object(migration.op, "create_unique_constraint") as create_unique,
    ):
        with pytest.raises(RuntimeError, match="resolve multiple bindings"):
            migration.downgrade()

    create_unique.assert_not_called()


def test_migration_downgrade_restores_department_unique_without_duplicates() -> None:
    result = SimpleNamespace(first=lambda: None)
    connection = SimpleNamespace(execute=lambda _statement: result)
    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration, "table_exists", return_value=True),
        patch.object(migration, "constraint_exists", return_value=False),
        patch.object(migration, "index_exists", return_value=False),
        patch.object(migration.op, "create_unique_constraint") as create_unique,
    ):
        migration.downgrade()

    create_unique.assert_called_once_with(
        "uk_dks_department_id",
        "department_knowledge_space",
        ["department_id"],
    )
