"""Unit tests for department-admin scoped review-tag authorization."""

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
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest

WorkStationTagsService = workstation_tags_service.WorkStationTagsService


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
            user_name="dept-admin",
        ),
        review_tags_repository=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_resolve_reviewable_space_ids_denies_ordinary_user():
    service = _build_service()
    with patch(
        "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(ReviewTagPermissionDeniedError):
            await service.resolve_reviewable_space_ids()


@pytest.mark.asyncio
async def test_resolve_reviewable_space_ids_for_department_admin():
    service = _build_service()
    admin_dept = SimpleNamespace(id=10, path="1/10/")
    with (
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[admin_dept]),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(return_value=[10, 11]),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(
                return_value=[
                    SimpleNamespace(space_id=100),
                    SimpleNamespace(space_id=101),
                ]
            ),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.aget_dept_admin_scoped_user_ids",
            new=AsyncMock(return_value={42, 43}),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.aget_member_personal_space_ids",
            new=AsyncMock(return_value={165, 166}),
        ),
    ):
        space_ids = await service.resolve_reviewable_space_ids()

    assert space_ids == {100, 101, 165, 166}


@pytest.mark.asyncio
async def test_resolve_reviewable_space_ids_includes_member_personal_spaces_only_when_scoped_users_exist():
    service = _build_service()
    admin_dept = SimpleNamespace(id=10, path="1/10/")
    with (
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
            new=AsyncMock(return_value=[admin_dept]),
        ),
        patch(
            "bisheng.database.models.department.DepartmentDao.aget_subtree_ids",
            new=AsyncMock(return_value=[10]),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new=AsyncMock(return_value=[SimpleNamespace(space_id=100)]),
        ),
        patch(
            "bisheng.knowledge.domain.services.department_admin_member_access.aget_dept_admin_scoped_user_ids",
            new=AsyncMock(return_value=set()),
        ),
    ):
        space_ids = await service.resolve_reviewable_space_ids()

    assert space_ids == {100}


@pytest.mark.asyncio
async def test_list_review_tag_by_page_passes_space_scope():
    service = _build_service()
    service.resolve_reviewable_space_ids = AsyncMock(return_value={100})
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
        1, 10, 1, "fo", space_ids={100}
    )
    service.review_tags_repository.get_review_tag_resource_info_by_tag.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_rejects_knowledge_outside_scope():
    service = _build_service()
    service.resolve_reviewable_space_ids = AsyncMock(return_value={100})
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    data = ApproveOrRejectRequest(
        tag_name="cross",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=1,
        knowledge_id=999,
    )

    with pytest.raises(ReviewTagSpaceOutOfScopeError):
        await service.approve_or_reject_review_tag(data, tenant_id=1)


@pytest.mark.asyncio
async def test_approve_passes_space_ids_to_repository():
    service = _build_service()
    service.resolve_reviewable_space_ids = AsyncMock(return_value={100})
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
        space_ids={100},
    )
    service.approve_tag_to_move_operation.assert_awaited_once_with(
        "scoped",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        skip_library_add=True,
        space_ids={100},
    )


@pytest.mark.asyncio
async def test_reject_passes_space_ids_to_repository():
    service = _build_service()
    service.resolve_reviewable_space_ids = AsyncMock(return_value={100})
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

    # reviewer_id added by F079 so rejected tags record who rejected them.
    service.review_tags_repository.reject_review_tag.assert_awaited_once_with(
        "scoped",
        "bad",
        TagResourceTypeEnum.MANUAL_TAG,
        1,
        space_ids={100},
        reviewer_id=9,
    )


@pytest.mark.asyncio
async def test_global_super_has_full_scope():
    service = _build_service(is_global_super=True)
    assert await service.resolve_reviewable_space_ids() is None
