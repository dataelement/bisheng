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

from bisheng.common.errcode.knowledge import KnowledgeSpaceTagLibraryInvalidError
from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest, ReviewTagSubmitterTarget

WorkStationTagsService = workstation_tags_service.WorkStationTagsService


def _build_tags_service() -> WorkStationTagsService:
    session = AsyncMock()
    session.commit = AsyncMock()
    return WorkStationTagsService(
        request=MagicMock(),
        session=session,
        login_user=SimpleNamespace(user_id=1, tenant_id=1),
        review_tags_repository=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_approve_review_tag_requires_library_and_knowledge():
    service = _build_tags_service()
    data = ApproveOrRejectRequest(
        tag_name="AI助手功能",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
    )

    with pytest.raises(KnowledgeSpaceTagLibraryInvalidError, match="请选择导入的标签库"):
        await service.approve_or_reject_review_tag(data, tenant_id=1)


@pytest.mark.asyncio
async def test_approve_review_tag_imports_to_selected_library():
    service = _build_tags_service()
    data = ApproveOrRejectRequest(
        tag_name="AI助手功能",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
        tag_library_id=10,
        knowledge_id=100,
    )
    append_review_tag = AsyncMock()
    approve_tag_to_move = AsyncMock(return_value=[])
    service.approve_tag_to_move_operation = approve_tag_to_move
    service.review_tags_repository.approve_review_tag = AsyncMock()
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(
        return_value=[
            ReviewTagSubmitterTarget(
                user_id=42, knowledge_space_id=100, file_id=501, file_name="a.pdf", file_type="pdf"
            )
        ],
    )
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(
        return_value=[SimpleNamespace(business_type="tag_library", business_id="10")],
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService",
        ) as library_service_cls,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService.resolve_bound_library_ids",
            new=AsyncMock(return_value=[10]),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ) as notify_after_decision,
    ):
        library_service_cls.return_value.append_review_tag = append_review_tag
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.list_submitter_notification_targets.assert_awaited_once()
    notify_after_decision.assert_awaited_once()

    append_review_tag.assert_awaited_once_with(
        library_id=10,
        knowledge_id=100,
        tag_name="AI助手功能",
        review_resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
        require_bound_library=True,
    )
    approve_tag_to_move.assert_awaited_once_with(
        "AI助手功能",
        TagResourceTypeEnum.AI_AUTO_TAG,
        1,
        skip_library_add=True,
    )
    service.review_tags_repository.approve_review_tag.assert_awaited_once()
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_review_tag_allows_any_library_when_tag_has_no_library_scope():
    service = _build_tags_service()
    data = ApproveOrRejectRequest(
        tag_name="人工标签",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
        tag_library_id=10,
        knowledge_id=100,
    )
    append_review_tag = AsyncMock()
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
            new=AsyncMock(return_value=[20, 30]),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
            new=AsyncMock(),
        ),
    ):
        library_service_cls.return_value.append_review_tag = append_review_tag
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    append_review_tag.assert_awaited_once_with(
        library_id=10,
        knowledge_id=100,
        tag_name="人工标签",
        review_resource_type=TagResourceTypeEnum.MANUAL_TAG.value,
        require_bound_library=False,
    )


@pytest.mark.asyncio
async def test_reject_review_tag_notifies_submitters():
    service = _build_tags_service()
    data = ApproveOrRejectRequest(
        tag_name="人工标签",
        status=ApproveOrRejectEnum.REJECT,
        reject_reason="名称不规范",
        resource_type=TagResourceTypeEnum.MANUAL_TAG,
    )
    service.review_tags_repository.reject_review_tag = AsyncMock()
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(
        return_value=[
            ReviewTagSubmitterTarget(
                user_id=88, knowledge_space_id=137, file_id=900, file_name="b.docx", file_type="docx"
            )
        ],
    )

    with patch(
        "bisheng.workstation.domain.services.review_tag_notification_service.ReviewTagNotificationService.notify_after_decision",
        new=AsyncMock(),
    ) as notify_after_decision:
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    service.review_tags_repository.reject_review_tag.assert_awaited_once()
    notify_after_decision.assert_awaited_once()
    kwargs = notify_after_decision.await_args.kwargs
    assert kwargs["tag_name"] == "人工标签"
    assert kwargs["reject_reason"] == "名称不规范"
    assert kwargs["submitter_targets"][0].user_id == 88
