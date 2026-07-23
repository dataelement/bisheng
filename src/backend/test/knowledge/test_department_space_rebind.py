from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from bisheng.knowledge.api.endpoints.knowledge_space import update_space
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.implementations.department_space_binding_repository_impl import (
    DepartmentSpaceBindingRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.department_space_binding_repository import (
    DepartmentSpaceRebindPlan,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceUpdateReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService


class _UnauthorizedTestError(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__(msg)


class _BusinessRuleTestError(Exception):
    def __init__(self, exception=None, msg: str | None = None, **_kwargs) -> None:
        super().__init__(msg or str(exception))


def _result(value):
    result = Mock()
    result.first.return_value = value
    result.all.return_value = value if isinstance(value, list) else []
    return result


def _make_repository_session(*results):
    return SimpleNamespace(
        exec=AsyncMock(side_effect=[_result(value) for value in results]),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
        delete=AsyncMock(),
    )


def _make_service(*, is_admin: bool) -> KnowledgeSpaceService:
    login_user = SimpleNamespace(
        user_id=7,
        user_name="系统管理员",
        tenant_id=1,
        is_admin=Mock(return_value=is_admin),
    )
    service = KnowledgeSpaceService(request=Mock(), login_user=login_user)
    service.department_space_binding_repo = AsyncMock()
    service.department_file_view_lifecycle_service = AsyncMock()
    service._require_permission_id = AsyncMock()
    return service


def _make_space() -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        type=KnowledgeTypeEnum.SPACE.value,
        is_favorite=False,
        name="部门资料库",
        description="",
        icon=None,
        auth_type="public",
        is_released=False,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        tenant_id=1,
        user_id=7,
    )


def test_update_schema_accepts_only_positive_department_id() -> None:
    assert KnowledgeSpaceUpdateReq(department_id=2).department_id == 2
    with pytest.raises(ValidationError):
        KnowledgeSpaceUpdateReq(department_id=0)


@pytest.mark.asyncio
async def test_update_endpoint_forwards_department_id() -> None:
    detail = {"id": 11, "department_id": 2, "owner_id": 2}
    service = SimpleNamespace(
        update_knowledge_space=AsyncMock(return_value={"id": 11}),
        get_space_info=AsyncMock(return_value=detail),
    )

    await update_space(
        space_id=11,
        req=KnowledgeSpaceUpdateReq(department_id=2),
        svc=service,
    )

    assert service.update_knowledge_space.await_args.kwargs["department_id"] == 2
    service.get_space_info.assert_awaited_once_with(11)


@pytest.mark.asyncio
async def test_admin_can_rebind_department_space_and_preserves_manual_manager() -> None:
    service = _make_service(is_admin=True)
    service._send_space_event_notification = AsyncMock()
    space = _make_space()
    scope = SimpleNamespace(
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        tenant_id=1,
    )
    target_department = SimpleNamespace(id=2, dept_id="new", status="active", is_deleted=0)
    old_department = SimpleNamespace(id=1, dept_id="old", status="active", is_deleted=0)
    service.department_space_binding_repo.prepare_rebind_department.return_value = _rebind_plan()
    service.department_space_binding_repo.commit_prepared_rebind.return_value = SimpleNamespace(
        department_id=2,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=scope,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            side_effect=[target_department, old_department],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentService.aget_admins",
            new_callable=AsyncMock,
            side_effect=[[{"user_id": 10}], [{"user_id": 20}]],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.has_explicit_relation_binding",
            new_callable=AsyncMock,
            side_effect=[False, True],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        await service.update_knowledge_space(11, department_id=2)

    service.department_space_binding_repo.prepare_rebind_department.assert_awaited_once_with(
        space_id=11,
        department_id=2,
        operator_id=7,
        creator_user_id=7,
        old_admin_user_ids={10},
        new_admin_user_ids={20},
        revoke_old_department_viewer=True,
    )
    service.department_file_view_lifecycle_service.prepare_department_rebind.assert_awaited_once_with(
        tenant_id=1,
        space_id=11,
        old_department_id=1,
        new_department_id=2,
        operator_id=7,
        operator_name="系统管理员",
    )
    assert {
        (item.subject_type, item.subject_id)
        for item in authorize.await_args.kwargs["revokes"]
    } == {("department", 1)}
    service._send_space_event_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_admin_cannot_rebind_department_space() -> None:
    service = _make_service(is_admin=False)
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.UnAuthorizedError",
            _UnauthorizedTestError,
        ),
    ):
        with pytest.raises(_UnauthorizedTestError):
            await service.update_knowledge_space(11, department_id=2)

    service.department_space_binding_repo.rebind_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_without_department_id_keeps_existing_flow() -> None:
    service = _make_service(is_admin=False)
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        await service.update_knowledge_space(11, description="更新说明")

    service._require_permission_id.assert_awaited_once_with("knowledge_space", 11, "edit_space")
    service.department_space_binding_repo.rebind_department.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        None,
        SimpleNamespace(
            level=KnowledgeSpaceLevelEnum.TEAM,
            owner_type=KnowledgeSpaceOwnerTypeEnum.USER_GROUP,
            owner_id=1,
            tenant_id=1,
        ),
    ],
    ids=["missing", "team"],
)
async def test_rebind_rejects_invalid_scope(scope) -> None:
    service = _make_service(is_admin=True)
    space = _make_space()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=scope,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceInvalidScopeOwnerError",
            _BusinessRuleTestError,
        ),
    ):
        with pytest.raises(_BusinessRuleTestError, match="仅部门知识库"):
            await service.update_knowledge_space(11, department_id=2)

    service.department_space_binding_repo.rebind_department.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "department",
    [None, SimpleNamespace(id=2, status="archived", is_deleted=1)],
    ids=["missing", "archived"],
)
async def test_rebind_rejects_invalid_department(department) -> None:
    service = _make_service(is_admin=True)
    space = _make_space()
    scope = SimpleNamespace(
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        tenant_id=1,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=scope,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=department,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceInvalidScopeOwnerError",
            _BusinessRuleTestError,
        ),
    ):
        with pytest.raises(_BusinessRuleTestError, match="不存在或已归档"):
            await service.update_knowledge_space(11, department_id=2)

    service.department_space_binding_repo.rebind_department.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_updates_both_relations_and_preserves_binding_config() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    binding = DepartmentKnowledgeSpace(
        id=2,
        tenant_id=1,
        department_id=1,
        space_id=11,
        created_by=3,
        approval_enabled=False,
        sensitive_check_enabled=True,
    )
    session = _make_repository_session(scope, None, binding)
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    result = await repository.rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
    )

    assert scope.level == KnowledgeSpaceLevelEnum.DEPARTMENT
    assert scope.owner_type == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
    assert scope.owner_id == 2
    assert result is binding
    assert binding.department_id == 2
    assert binding.space_id == 11
    assert binding.created_by == 3
    assert binding.approval_enabled is False
    assert binding.sensitive_check_enabled is True
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_rolls_back_when_relation_write_fails() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    binding = DepartmentKnowledgeSpace(
        id=2,
        tenant_id=1,
        department_id=1,
        space_id=11,
        created_by=3,
    )
    session = _make_repository_session(scope, None, binding)
    session.flush.side_effect = RuntimeError("write failed")
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    with pytest.raises(RuntimeError, match="write failed"):
        await repository.rebind_department(
            space_id=11,
            department_id=2,
            operator_id=7,
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_repository_creates_missing_binding_in_same_commit() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    session = _make_repository_session(scope, None, None)
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    binding = await repository.rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
    )

    assert binding.department_id == 2
    assert binding.space_id == 11
    assert binding.created_by == 7
    assert binding.approval_enabled is True
    assert binding.sensitive_check_enabled is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repository_allows_department_bound_to_another_space() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    conflicting_binding = DepartmentKnowledgeSpace(
        id=4,
        tenant_id=1,
        department_id=2,
        space_id=99,
        created_by=8,
    )
    session = _make_repository_session(scope, [conflicting_binding], None)
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    binding = await repository.rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
    )

    assert binding.department_id == 2
    assert binding.space_id == 11
    assert conflicting_binding.department_id == 2
    assert conflicting_binding.space_id == 99
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_rebind_to_current_department_is_idempotent() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=2,
        created_by=3,
    )
    binding = DepartmentKnowledgeSpace(
        id=2,
        tenant_id=1,
        department_id=2,
        space_id=11,
        created_by=3,
    )
    session = _make_repository_session(scope, binding, binding)
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    result = await repository.rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
    )

    assert result is binding
    assert binding.department_id == 2
    assert binding.created_by == 3
    session.commit.assert_awaited_once()


def _rebind_plan(*, noop: bool = False) -> DepartmentSpaceRebindPlan:
    return DepartmentSpaceRebindPlan(
        space_id=11,
        old_department_id=1 if not noop else 2,
        new_department_id=2,
        manager_grant_user_ids=(20,),
        manager_revoke_user_ids=(10,),
        is_noop=noop,
    )


@pytest.mark.asyncio
async def test_rebind_migrates_department_viewer_and_automatic_admin_permissions() -> None:
    service = _make_service(is_admin=True)
    space = _make_space()
    space.user_id = 7
    service.department_space_binding_repo.prepare_rebind_department.return_value = _rebind_plan()
    service.department_space_binding_repo.commit_prepared_rebind.return_value = SimpleNamespace(
        department_id=2,
    )
    old_department = SimpleNamespace(id=1, dept_id="old", status="active", is_deleted=0)
    new_department = SimpleNamespace(id=2, dept_id="new", status="active", is_deleted=0)

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=1,
                tenant_id=1,
            ),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            side_effect=[new_department, old_department],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentService.aget_admins",
            new_callable=AsyncMock,
            side_effect=[[{"user_id": 10}], [{"user_id": 20}]],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.has_explicit_relation_binding",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        await service.update_knowledge_space(11, department_id=2)

    call = authorize.await_args
    assert call.kwargs["enforce_fga_success"] is True
    assert {
        (item.subject_type, item.subject_id, item.relation, item.include_children)
        for item in call.kwargs["grants"]
    } == {
        ("department", 2, "viewer", True),
        ("user", 20, "manager", False),
    }
    assert {
        (item.subject_type, item.subject_id, item.relation, item.include_children)
        for item in call.kwargs["revokes"]
    } == {
        ("department", 1, "viewer", True),
        ("user", 10, "manager", False),
    }
    service.department_space_binding_repo.commit_prepared_rebind.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebind_rolls_back_prepared_database_changes_when_fga_fails() -> None:
    service = _make_service(is_admin=True)
    space = _make_space()
    space.user_id = 7
    service.department_space_binding_repo.prepare_rebind_department.return_value = _rebind_plan()

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=1,
                tenant_id=1,
            ),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            side_effect=[
                SimpleNamespace(id=2, dept_id="new", status="active", is_deleted=0),
                SimpleNamespace(id=1, dept_id="old", status="active", is_deleted=0),
            ],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentService.aget_admins",
            new_callable=AsyncMock,
            side_effect=[[{"user_id": 10}], [{"user_id": 20}]],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("fga failed"), None],
        ) as authorize,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.has_explicit_relation_binding",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        with pytest.raises(RuntimeError, match="fga failed"):
            await service.update_knowledge_space(11, department_id=2)

    service.department_space_binding_repo.rollback_prepared_rebind.assert_awaited_once()
    service.department_space_binding_repo.commit_prepared_rebind.assert_not_awaited()
    assert authorize.await_count == 2
    compensation = authorize.await_args_list[1].kwargs
    assert {(item.subject_type, item.subject_id) for item in compensation["grants"]} == {
        ("department", 1),
        ("user", 10),
    }
    assert {(item.subject_type, item.subject_id) for item in compensation["revokes"]} == {
        ("department", 2),
        ("user", 20),
    }


@pytest.mark.asyncio
async def test_rebind_compensates_permissions_when_database_commit_fails() -> None:
    service = _make_service(is_admin=True)
    space = _make_space()
    space.user_id = 7
    service.department_space_binding_repo.prepare_rebind_department.return_value = _rebind_plan()
    service.department_space_binding_repo.commit_prepared_rebind.side_effect = RuntimeError("db failed")

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=1,
                tenant_id=1,
            ),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            side_effect=[
                SimpleNamespace(id=2, dept_id="new", status="active", is_deleted=0),
                SimpleNamespace(id=1, dept_id="old", status="active", is_deleted=0),
            ],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentService.aget_admins",
            new_callable=AsyncMock,
            side_effect=[[{"user_id": 10}], [{"user_id": 20}]],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "FineGrainedPermissionService.has_explicit_relation_binding",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        with pytest.raises(RuntimeError, match="db failed"):
            await service.update_knowledge_space(11, department_id=2)

    assert authorize.await_count == 2
    compensation = authorize.await_args_list[1].kwargs
    assert compensation["enforce_fga_success"] is True
    assert {(item.subject_type, item.subject_id) for item in compensation["grants"]} == {
        ("department", 1),
        ("user", 10),
    }
    assert {(item.subject_type, item.subject_id) for item in compensation["revokes"]} == {
        ("department", 2),
        ("user", 20),
    }


@pytest.mark.asyncio
async def test_repository_prepares_automatic_admin_changes_without_touching_manual_admins() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    binding = DepartmentKnowledgeSpace(
        id=2,
        tenant_id=1,
        department_id=1,
        space_id=11,
        created_by=3,
    )
    old_automatic_admin = SimpleNamespace(
        user_id=10,
        user_role="admin",
        status="ACTIVE",
        membership_source="department_admin",
        department_admin_promoted_from_role=None,
    )
    old_manual_admin = SimpleNamespace(
        user_id=11,
        user_role="admin",
        status="ACTIVE",
        membership_source="manual",
        department_admin_promoted_from_role=None,
    )
    new_manual_member = SimpleNamespace(
        user_id=20,
        user_role="member",
        status="ACTIVE",
        membership_source="manual",
        department_admin_promoted_from_role=None,
    )
    shared_automatic_admin = SimpleNamespace(
        user_id=30,
        user_role="admin",
        status="ACTIVE",
        membership_source="department_admin",
        department_admin_promoted_from_role=None,
    )
    session = _make_repository_session(
        scope,
        None,
        binding,
        [old_automatic_admin, old_manual_admin, new_manual_member, shared_automatic_admin],
    )
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    plan = await repository.prepare_rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
        creator_user_id=7,
        old_admin_user_ids={10, 11, 30},
        new_admin_user_ids={20, 30},
    )

    assert plan.manager_revoke_user_ids == (10,)
    assert plan.manager_grant_user_ids == (20,)
    session.delete.assert_awaited_once_with(old_automatic_admin)
    assert old_manual_admin.membership_source == "manual"
    assert old_manual_admin.user_role == "admin"
    assert new_manual_member.membership_source == "department_admin"
    assert new_manual_member.user_role == "admin"
    assert new_manual_member.department_admin_promoted_from_role == "member"
    assert shared_automatic_admin.membership_source == "department_admin"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_removes_automatic_admin_row_but_preserves_duplicate_manual_admin() -> None:
    scope = KnowledgeSpaceScope(
        id=1,
        tenant_id=1,
        space_id=11,
        level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
        owner_id=1,
        created_by=3,
    )
    binding = DepartmentKnowledgeSpace(
        id=2,
        tenant_id=1,
        department_id=1,
        space_id=11,
        created_by=3,
    )
    automatic_admin = SimpleNamespace(
        user_id=12,
        user_role="admin",
        status="ACTIVE",
        membership_source="department_admin",
        department_admin_promoted_from_role=None,
    )
    manual_admin = SimpleNamespace(
        user_id=12,
        user_role="admin",
        status="ACTIVE",
        membership_source="manual",
        department_admin_promoted_from_role=None,
    )
    session = _make_repository_session(scope, None, binding, [automatic_admin, manual_admin])
    repository = DepartmentSpaceBindingRepositoryImpl(session)

    plan = await repository.prepare_rebind_department(
        space_id=11,
        department_id=2,
        operator_id=7,
        creator_user_id=7,
        old_admin_user_ids={12},
        new_admin_user_ids=set(),
    )

    assert plan.manager_revoke_user_ids == ()
    session.delete.assert_awaited_once_with(automatic_admin)
    assert manual_admin.user_role == "admin"
    assert manual_admin.membership_source == "manual"


@pytest.mark.asyncio
async def test_rebind_to_same_department_skips_permission_migration() -> None:
    service = _make_service(is_admin=True)
    space = _make_space()
    space.user_id = 7
    service.department_space_binding_repo.prepare_rebind_department.return_value = _rebind_plan(noop=True)
    service.department_space_binding_repo.commit_prepared_rebind.return_value = SimpleNamespace(
        department_id=2,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceScopeDao.aget_by_space_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                owner_type=KnowledgeSpaceOwnerTypeEnum.DEPARTMENT,
                owner_id=2,
                tenant_id=1,
            ),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentDao.aget_by_id",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=2, dept_id="same", status="active", is_deleted=0),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.DepartmentService.aget_admins",
            new_callable=AsyncMock,
            return_value=[{"user_id": 20}],
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
            return_value=space,
        ),
    ):
        await service.update_knowledge_space(11, department_id=2)

    authorize.assert_not_awaited()
    service.department_space_binding_repo.commit_prepared_rebind.assert_awaited_once()


def test_manual_old_department_viewer_is_not_revoked_or_recreated_by_compensation() -> None:
    plan = DepartmentSpaceRebindPlan(
        space_id=11,
        old_department_id=1,
        new_department_id=2,
        revoke_old_department_viewer=False,
    )

    forward_grants, forward_revokes = KnowledgeSpaceService._department_rebind_permission_items(plan)
    reverse_grants, reverse_revokes = KnowledgeSpaceService._department_rebind_permission_items(
        plan,
        reverse=True,
    )

    assert {(item.subject_type, item.subject_id) for item in forward_grants} == {("department", 2)}
    assert forward_revokes == []
    assert reverse_grants == []
    assert {(item.subject_type, item.subject_id) for item in reverse_revokes} == {("department", 2)}


@pytest.mark.asyncio
async def test_explicit_department_viewer_binding_is_detected() -> None:
    with patch(
        "bisheng.permission.domain.services.fine_grained_permission_service._get_bindings",
        new_callable=AsyncMock,
        return_value=[
            {
                "resource_type": "knowledge_space",
                "resource_id": "11",
                "subject_type": "department",
                "subject_id": 1,
                "relation": "viewer",
                "include_children": True,
                "model_id": "manual-viewer",
            },
        ],
    ):
        exists = await FineGrainedPermissionService.has_explicit_relation_binding(
            object_type="knowledge_space",
            object_id=11,
            subject_type="department",
            subject_id=1,
            relation="viewer",
            include_children=True,
        )

    assert exists is True
