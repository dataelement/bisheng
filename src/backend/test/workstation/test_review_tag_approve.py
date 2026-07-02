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
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest

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

    with patch(
        "bisheng.knowledge.domain.services.knowledge_space_tag_library_service.KnowledgeSpaceTagLibraryService",
    ) as library_service_cls:
        library_service_cls.return_value.append_review_tag = append_review_tag
        await service.approve_or_reject_review_tag(data, tenant_id=1)

    append_review_tag.assert_awaited_once_with(
        library_id=10,
        knowledge_id=100,
        tag_name="AI助手功能",
        review_resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value,
    )
    approve_tag_to_move.assert_awaited_once_with(
        "AI助手功能",
        TagResourceTypeEnum.AI_AUTO_TAG,
        1,
        skip_library_add=True,
    )
    service.review_tags_repository.approve_review_tag.assert_awaited_once()
    service.session.commit.assert_awaited_once()
