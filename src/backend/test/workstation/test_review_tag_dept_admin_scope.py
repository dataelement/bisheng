"""Unit tests for review-tag authorization by space level and org uploader."""

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

base_service_stub = types.ModuleType("bisheng.common.services.base")


class _BaseService:
    pass


base_service_stub.BaseService = _BaseService
sys.modules["bisheng.common.services.base"] = base_service_stub
workstation_tags_service = importlib.reload(
    importlib.import_module("bisheng.workstation.domain.services.workstation_tags_service")
)

from bisheng.common.errcode.tag import (
    ReviewTagPermissionDeniedError,
    ReviewTagSpaceOutOfScopeError,
)
from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest, ReviewTagScope

WorkStationTagsService = workstation_tags_service.WorkStationTagsService
resolve_review_tag_scope_for_user = workstation_tags_service.resolve_review_tag_scope_for_user
user_can_review_tags = workstation_tags_service.user_can_review_tags


def _build_service(*, is_global_super: bool = False) -> WorkStationTagsService:
    session = AsyncMock()
    session.commit = AsyncMock()
    return WorkStationTagsService(
        request=MagicMock(),
        session=session,
        login_user=SimpleNamespace(
            user_id=9,
            tenant_id=1,
            is_global_super=is_global_super,
            is_admin=lambda: False,
            has_tenant_admin=AsyncMock(return_value=False),
            user_name="reviewer",
        ),
        review_tags_repository=AsyncMock(),
    )


def _login_user():
    return SimpleNamespace(
        user_id=9,
        tenant_id=1,
        is_global_super=False,
        is_admin=lambda: False,
        has_tenant_admin=AsyncMock(return_value=False),
    )


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_denies_ordinary_user():
    login_user = _login_user()
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.common.models.space_channel_member.SpaceChannelMemberDao.async_get_user_managed_members",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[]),
        ),
    ):
        with pytest.raises(ReviewTagPermissionDeniedError):
            await resolve_review_tag_scope_for_user(login_user)


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_for_space_admin_role_libraries_only():
    login_user = _login_user()
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["100", "200", "300"]),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new=AsyncMock(
                return_value={
                    100: SimpleNamespace(level="public"),
                    200: SimpleNamespace(level="team_ks"),
                    300: SimpleNamespace(level="team"),
                }
            ),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[]),
        ),
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.full_tenant is False
    assert scope.role_managed_space_ids == frozenset({100, 200})
    assert scope.org_uploader_ids is None


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_falls_back_to_member_table():
    login_user = _login_user()
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.common.models.space_channel_member.SpaceChannelMemberDao.async_get_user_managed_members",
            new=AsyncMock(return_value=[SimpleNamespace(business_id="100")]),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new=AsyncMock(return_value={100: SimpleNamespace(level="department")}),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[]),
        ),
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({100})


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_for_department_admin_org_uploaders_only():
    login_user = _login_user()
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.common.models.space_channel_member.SpaceChannelMemberDao.async_get_user_managed_members",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[SimpleNamespace(id=10, path="1/10/")]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.aget_dept_admin_scoped_user_ids",
            new=AsyncMock(return_value={42, 43}),
        ),
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.full_tenant is False
    assert scope.role_managed_space_ids == frozenset()
    assert scope.org_uploader_ids == frozenset({42, 43})


@pytest.mark.asyncio
async def test_resolve_review_tag_scope_combines_role_and_org():
    login_user = _login_user()
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.list_accessible_ids",
            new=AsyncMock(return_value=["100"]),
        ),
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_map_by_space_ids",
            new=AsyncMock(return_value={100: SimpleNamespace(level="department")}),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[SimpleNamespace(id=10, path="1/10/")]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.aget_dept_admin_scoped_user_ids",
            new=AsyncMock(return_value={7}),
        ),
    ):
        scope = await resolve_review_tag_scope_for_user(login_user)

    assert scope.role_managed_space_ids == frozenset({100})
    assert scope.org_uploader_ids == frozenset({7})


@pytest.mark.asyncio
async def test_user_can_review_tags():
    login_user = _login_user()
    with patch.object(
        workstation_tags_service,
        "resolve_review_tag_scope_for_user",
        new=AsyncMock(return_value=ReviewTagScope(org_uploader_ids=frozenset({1}))),
    ):
        assert await user_can_review_tags(login_user) is True

    with patch.object(
        workstation_tags_service,
        "resolve_review_tag_scope_for_user",
        new=AsyncMock(side_effect=ReviewTagPermissionDeniedError()),
    ):
        assert await user_can_review_tags(login_user) is False


@pytest.mark.asyncio
async def test_list_review_tag_by_page_passes_scope():
    service = _build_service()
    scope = ReviewTagScope(org_uploader_ids=frozenset({1}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    service.review_tags_repository.get_review_tag_group_list_by_page = AsyncMock(
        return_value=[{"name": "foo", "resource_type": TagResourceTypeEnum.MANUAL_TAG}]
    )
    service.review_tags_repository.get_review_tag_resource_info_by_tag = AsyncMock(
        return_value={"tag_name": "foo", "resource_files": []}
    )
    service.review_tags_repository.get_review_tag_group_count_by_page = AsyncMock(return_value=1)

    result = await service.list_review_tag_by_page(1, 10, tenant_id=1, keyword="fo")

    assert result["total"] == 1
    service.review_tags_repository.get_review_tag_group_list_by_page.assert_awaited_once_with(
        1, 10, 1, "fo", scope=scope
    )


@pytest.mark.asyncio
async def test_approve_rejects_role_library_outside_scope():
    service = _build_service()
    service.resolve_review_tag_scope = AsyncMock(return_value=ReviewTagScope(role_managed_space_ids=frozenset({100})))
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    data = ApproveOrRejectRequest(
        tag_name="cross",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=1,
        knowledge_id=999,
    )

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_scope.KnowledgeSpaceScopeDao.aget_by_space_id",
            new=AsyncMock(return_value=SimpleNamespace(level="public")),
        ),
        pytest.raises(ReviewTagSpaceOutOfScopeError),
    ):
        await service.approve_or_reject_review_tag(data, tenant_id=1)


@pytest.mark.asyncio
async def test_approve_passes_scope_to_repository():
    service = _build_service()
    scope = ReviewTagScope(role_managed_space_ids=frozenset({100}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    data = ApproveOrRejectRequest(
        tag_name="scoped",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=10,
        knowledge_id=100,
    )
    service.approve_tag_to_move_operation = AsyncMock(return_value=[])
    service.review_tags_repository.approve_review_tag = AsyncMock()
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(business_type="knowledge_space", business_id="100")],
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService",
        ) as library_service_cls,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
    ):
        library_service_cls.return_value.append_review_tag = AsyncMock()
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.approve_review_tag.assert_awaited_once_with(
        "scoped",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        scope=scope,
    )
    service.approve_tag_to_move_operation.assert_awaited_once_with(
        "scoped",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        skip_library_add=True,
        scope=scope,
        target_library_id=10,
    )


@pytest.mark.asyncio
async def test_reject_passes_scope_to_repository():
    service = _build_service()
    scope = ReviewTagScope(org_uploader_ids=frozenset({42}))
    service.resolve_review_tag_scope = AsyncMock(return_value=scope)
    data = ApproveOrRejectRequest(
        tag_name="scoped",
        status=ApproveOrRejectEnum.REJECT,
        reject_reason="bad",
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
    )
    service.review_tags_repository.reject_review_tag = AsyncMock()
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(id=1, business_type="knowledge_space", business_id="100")],
    )
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])

    with (
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
            new=AsyncMock(),
        ),
    ):
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.reject_review_tag.assert_awaited_once_with(
        "scoped",
        "bad",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        scope=scope,
        reviewer_id=9,
    )


@pytest.mark.asyncio
async def test_global_super_has_full_scope():
    service = _build_service(is_global_super=True)
    scope = await service.resolve_review_tag_scope()
    assert scope.full_tenant is True


@pytest.mark.asyncio
async def test_review_tag_scope_allows_predicates():
    scope = ReviewTagScope(
        role_managed_space_ids=frozenset({10}),
        org_uploader_ids=frozenset({5}),
    )
    assert scope.allows_space_for_uploader(space_id=10, level="public", uploader_id=99) is True
    assert scope.allows_space_for_uploader(space_id=20, level="team", uploader_id=5) is True
    assert scope.allows_space_for_uploader(space_id=20, level="team_ks", uploader_id=5) is False
    assert scope.allows_space_for_uploader(space_id=20, level="personal", uploader_id=6) is False
