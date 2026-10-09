from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_space import PortalManualRecommendationInvalidError
from bisheng.knowledge.domain.repositories.interfaces.portal_manual_recommendation_repository import ManualFileRecord
from bisheng.knowledge.domain.services.portal_manual_recommendation_service import PortalManualRecommendationService


def record(file_id=1, space_id=10, document_id=100):
    file = SimpleNamespace(
        id=file_id,
        knowledge_id=space_id,
        file_name="推荐.pdf",
        abstract="安全摘要",
        update_time=None,
        create_time=None,
        file_subcategory_code=None,
        file_encoding=None,
        entry_type=None,
        entry_status=None,
        file_level_path=None,
        object_name="secret-object",
        preview_url="secret-url",
    )
    return ManualFileRecord(file, "公开知识库", "department", document_id, None)


async def test_manual_save_resolves_identity_and_rejects_forged_or_unavailable_new_items():
    repo = SimpleNamespace(find_references=AsyncMock(return_value=[record()]))
    service = PortalManualRecommendationService(repo)
    result = await service.validate_items([{"space_id": 10, "file_id": 1}], [])
    assert result == [{"space_id": 10, "file_id": 1, "canonical_document_id": 100}]
    with pytest.raises(PortalManualRecommendationInvalidError):
        await service.validate_items([{"space_id": 10, "file_id": 1, "canonical_document_id": 999}], [])
    with pytest.raises(PortalManualRecommendationInvalidError):
        await service.validate_items([{"space_id": 20, "file_id": 2}], [])
    stale = {"space_id": 20, "file_id": 2}
    assert await service.validate_items([stale], [stale]) == [stale]


async def test_manual_save_rejects_two_entries_of_same_document_and_metadata_is_safe():
    repo = SimpleNamespace(find_references=AsyncMock(return_value=[record(), record(2, 20)]))
    service = PortalManualRecommendationService(repo)
    refs = [{"space_id": 10, "file_id": 1}, {"space_id": 20, "file_id": 2}]
    with pytest.raises(PortalManualRecommendationInvalidError):
        await service.validate_items(refs, [])
    result = await service.resolve_items(refs[:1])
    assert result[0]["title"] == "推荐"
    assert result[0]["content_access"] == "check_required"
    assert result[0]["can_download"] is False
    assert "object_name" not in result[0]
    assert "preview_url" not in result[0]
    assert result[0]["canonical_document_id"] == 100


@pytest.mark.parametrize(
    "items",
    [
        [{"space_id": 10, "file_id": True}],
        [{"space_id": 10, "file_id": 1}, {"space_id": 10, "file_id": 1}],
        [{"space_id": 10, "file_id": n} for n in range(1, 22)],
    ],
)
def test_config_rejects_invalid_identity_duplicate_and_over_limit(items):
    from pydantic import ValidationError

    from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import PortalRecommendationConfig

    with pytest.raises(ValidationError):
        PortalRecommendationConfig(
            provider="tag_feed", home_strategy="old", detail_strategy="related", manual_items=items
        )


async def test_manual_prefix_spans_pages_deduplicates_and_rejects_old_config_cursor():
    from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileBrowseReq

    refs = [{"space_id": 10, "file_id": 1}]
    service = PortalManualRecommendationService(SimpleNamespace(find_references=AsyncMock(return_value=[record()])))
    automatic = [
        {"id": 2, "space_id": 20, "canonical_document_id": 100},
        {"id": 3, "space_id": 10, "canonical_document_id": 103},
        {"id": 4, "space_id": 10, "canonical_document_id": 104},
    ]

    async def fetch(req):
        if req.cursor is None:
            return {"data": automatic[:2], "has_more": True, "next_cursor": "automatic-page-2"}
        return {"data": automatic[1:], "has_more": False, "next_cursor": None}

    req = ShougangPortalFileBrowseReq(recommendation="latest_selected", limit=1)
    pages, cursor = [], None
    while True:
        result = await service.recommend(
            req.model_copy(update={"cursor": cursor}),
            refs,
            fetch,
            config_version=1,
            tenant_id=1,
            user_id=7,
            total_count=20,
        )
        pages += result["data"]
        cursor = result["next_cursor"]
        if not result["has_more"]:
            break
    assert [row["id"] for row in pages] == [1, 3, 4]
    first = await service.recommend(req, refs, fetch, config_version=1, tenant_id=1, user_id=7, total_count=20)
    with pytest.raises(KnowledgeInvalidCursorError):
        await service.recommend(
            req.model_copy(update={"cursor": first["next_cursor"]}),
            refs,
            fetch,
            config_version=2,
            tenant_id=1,
            user_id=7,
            total_count=20,
        )


async def test_personalized_manual_results_keep_limit_and_filter_metadata_without_read_permission():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileSearchReq

    service = PortalManualRecommendationService(SimpleNamespace(find_references=AsyncMock(return_value=[record()])))

    async def fetch(req):
        assert req.response_scene == "list"
        return {"data": [{"id": 3, "space_id": 10, "canonical_document_id": 103}], "has_more": False}

    req = ShougangPortalFileSearchReq(recommendation="personalized_v1", q="不存在", limit=1)
    result = await service.recommend(
        req, [{"space_id": 10, "file_id": 1}], fetch, config_version=1, tenant_id=1, user_id=7, total_count=2
    )
    assert [row["id"] for row in result["data"]] == [3]


@pytest.mark.parametrize("mode", ["latest_selected", "personalized_v1"])
async def test_real_recommendation_boundary_uses_shared_prefix_for_anonymous_public_home(monkeypatch, mode):
    from contextlib import asynccontextmanager

    from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
        ShougangPortalFileBrowseReq,
        ShougangPortalFileItemResp,
    )
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
        ManualRecommendationRef,
        ShougangPortalAdminConfig,
    )
    from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService
    from test.shougang_portal_config.test_personalized_recommendation_config import _config_payload

    config = ShougangPortalAdminConfig.model_validate(_config_payload())
    config.portal.recommendation.manual_items = [
        ManualRecommendationRef(space_id=10, file_id=1, canonical_document_id=100)
    ]
    monkeypatch.setattr(ShougangPortalConfigService, "get_config", AsyncMock(return_value=config))

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr("bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session", session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.portal_manual_recommendation_repository_impl."
        "PortalManualRecommendationRepositoryImpl.find_references",
        AsyncMock(return_value=[record()]),
    )
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, tenant_id=1)
    service.resolve_portal_discovery = AsyncMock(return_value=SimpleNamespace(snapshot="public-v1"))

    async def automatic(req):
        return {
            "data": [
                {"id": 2, "space_id": 20, "canonical_document_id": 100},
                {"id": 3, "space_id": 10, "title": "自动推荐", "canonical_document_id": 103},
            ],
            "has_more": False,
        }

    req = ShougangPortalFileBrowseReq(
        recommendation=mode, response_scene="home", discovery_scope="portal_public", space_level="public"
    )
    result = await service._with_portal_manual_recommendations(req, automatic)
    assert [item["id"] for item in result["data"]] == [1, 3]
    safe = ShougangPortalFileItemResp.model_validate(result["data"][0]).model_dump(mode="json")
    assert safe["canonical_document_id"] == 100
    assert safe["can_download"] is False
    assert "manager_file_id" not in safe and "file_size" not in safe


async def test_manual_reference_failure_returns_only_automatic_metadata():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileBrowseReq

    service = PortalManualRecommendationService(
        SimpleNamespace(find_references=AsyncMock(side_effect=RuntimeError("offline")))
    )

    async def automatic(req):
        return {"data": [{"id": 3, "space_id": 10, "title": "自动推荐"}], "has_more": False}

    result = await service.recommend(
        ShougangPortalFileBrowseReq(recommendation="latest_selected"),
        [{"space_id": 10, "file_id": 1}],
        automatic,
        config_version=1,
        tenant_id=1,
        user_id=7,
        total_count=20,
    )
    assert [item["id"] for item in result["data"]] == [3]


async def test_recommendation_count_uses_namespaced_logical_identity():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileCountReq
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = object.__new__(KnowledgeSpaceService)
    service.browse_shougang_portal_files = AsyncMock(
        return_value={
            "data": [
                {"id": 1, "space_id": 10, "canonical_document_id": 100},
                {"id": 100, "space_id": 10},
            ],
            "has_more": False,
        }
    )
    result = await service.count_shougang_portal_files(
        ShougangPortalFileCountReq(query_type="recommendation", recommendation="latest_selected")
    )
    assert result["total"] == 2
