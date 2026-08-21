"""Tests for server-side ack_similar enforcement on review-tag approve."""

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

from bisheng.common.errcode.tag import ReviewTagSimilarAckRequiredError
from bisheng.database.models.review_tags import ApproveOrRejectEnum, TagResourceTypeEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ApproveOrRejectRequest

WorkStationTagsService = workstation_tags_service.WorkStationTagsService


def _build_tags_service() -> WorkStationTagsService:
    session = AsyncMock()
    session.commit = AsyncMock()
    return WorkStationTagsService(
        request=MagicMock(),
        session=session,
        login_user=SimpleNamespace(
            user_id=1,
            tenant_id=1,
            is_global_super=True,
            is_admin=lambda: True,
            user_name="admin",
        ),
        review_tags_repository=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_ensure_review_tag_similar_acknowledged_blocks_without_ack():
    service = _build_tags_service()
    with patch.object(
        WorkStationTagsService,
        "_load_similar_matches_for_tag",
        new=AsyncMock(
            return_value=[{"name": "机器学习-模型训练", "match_kind": "substring", "score": None}],
        ),
    ):
        with pytest.raises(ReviewTagSimilarAckRequiredError):
            await service.ensure_review_tag_similar_acknowledged(
                tag_name="机器学习",
                tag_library_id=10,
                tenant_id=1,
                ack_similar=False,
            )


@pytest.mark.asyncio
async def test_ensure_review_tag_similar_acknowledged_allows_with_ack():
    service = _build_tags_service()
    with patch.object(
        WorkStationTagsService,
        "_load_similar_matches_for_tag",
        new=AsyncMock(
            return_value=[{"name": "机器学习-模型训练", "match_kind": "substring", "score": None}],
        ),
    ):
        await service.ensure_review_tag_similar_acknowledged(
            tag_name="机器学习",
            tag_library_id=10,
            tenant_id=1,
            ack_similar=True,
        )


@pytest.mark.asyncio
async def test_approve_review_tag_requires_ack_similar_when_matches_exist():
    service = _build_tags_service()
    data = ApproveOrRejectRequest(
        tag_name="机器学习",
        status=ApproveOrRejectEnum.APPROVE,
        resource_type=TagResourceTypeEnum.AI_AUTO_TAG,
        tag_library_id=10,
        knowledge_id=100,
        ack_similar=False,
    )
    service.review_tags_repository.get_review_tag_list_by_tag_name = AsyncMock(return_value=[SimpleNamespace()])
    service.review_tags_repository.list_submitter_notification_targets = AsyncMock(return_value=[])
    ensure_ack = AsyncMock(side_effect=ReviewTagSimilarAckRequiredError(msg="blocked"))

    with (
        patch.object(service, "resolve_review_tag_scope", new=AsyncMock(return_value=SimpleNamespace(full_tenant=True))),
        patch.object(service, "_ensure_knowledge_in_scope", new=AsyncMock()),
        patch.object(service, "ensure_review_tag_similar_acknowledged", new=ensure_ack),
    ):
        with pytest.raises(ReviewTagSimilarAckRequiredError):
            await service.approve_or_reject_review_tag(data, tenant_id=1)

    ensure_ack.assert_awaited_once_with(
        tag_name="机器学习",
        tag_library_id=10,
        tenant_id=1,
        ack_similar=False,
    )


@pytest.mark.asyncio
async def test_check_review_tag_similar_in_library_returns_matches():
    """AC: similar check returns grouped exact/similar matches for the target library."""
    service = _build_tags_service()
    library = SimpleNamespace(id=10, tenant_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_tag_library.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_config_service.resolve_review_tag_similarity_threshold_async",
            new=AsyncMock(return_value=0.85),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.check_review_tag_similar_in_library_sync",
            return_value=([], [("机器学习-模型训练", "substring", None)]),
        ),
    ):
        result = await service.check_review_tag_similar_in_library(
            tag_name="机器学习",
            tag_library_id=10,
            tenant_id=1,
        )

    assert result.similarity_threshold == 0.85
    assert len(result.similar_matches) == 1
    assert result.similar_matches[0].name == "机器学习-模型训练"
    assert result.similar_matches[0].match_kind == "substring"


@pytest.mark.asyncio
async def test_check_review_tag_similar_in_library_batch_returns_per_tag_items():
    """AC: batch similar check returns one item per tag with similar matches."""
    service = _build_tags_service()
    library = SimpleNamespace(id=10, tenant_id=1)

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge_space_tag_library.KnowledgeSpaceTagLibraryDao.aget",
            new=AsyncMock(return_value=library),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_config_service.resolve_review_tag_similarity_threshold_async",
            new=AsyncMock(return_value=0.85),
        ),
        patch(
            "bisheng.knowledge.domain.services.tag_library_tag_service.TagLibraryTagService.check_review_tag_similar_in_library_batch_sync",
            return_value=[
                ("机器学习", [], [("机器学习-模型训练", "substring", None)]),
                ("深度学习", [], []),
            ],
        ),
    ):
        result = await service.check_review_tag_similar_in_library_batch(
            tag_names=["机器学习", "深度学习"],
            tag_library_id=10,
            tenant_id=1,
        )

    assert result.similarity_threshold == 0.85
    assert result.similar_tag_count == 1
    assert len(result.items) == 2
    assert result.items[0].tag_name == "机器学习"
    assert result.items[0].similar_matches[0].name == "机器学习-模型训练"
