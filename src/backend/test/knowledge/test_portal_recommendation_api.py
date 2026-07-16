from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileBrowseReq
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_personalized_v1_browse_is_independently_dispatched_and_has_no_cursor_pagination():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=10)]
    service._get_shougang_portal_visible_search_spaces = AsyncMock(return_value=spaces)
    service._recommend_shougang_portal_files = AsyncMock(
        return_value={
            "data": [{"id": 100, "space_id": 10, "title": "doc"}],
            "has_more": False,
            "next_cursor": None,
        }
    )
    service._list_shougang_portal_hot_read_files = AsyncMock()
    service._list_shougang_portal_files_without_keyword = AsyncMock()

    request = ShougangPortalFileBrowseReq(
        recommendation="personalized_v1",
        limit=20,
        cursor="ignored",
    )
    result = await service._browse_shougang_portal_files_impl(request)

    assert result["has_more"] is False
    assert result["next_cursor"] is None
    service._recommend_shougang_portal_files.assert_awaited_once_with(req=request, spaces=spaces)
    service._list_shougang_portal_hot_read_files.assert_not_awaited()
    service._list_shougang_portal_files_without_keyword.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_latest_selected_browse_path_is_unchanged():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=10)]
    service._get_shougang_portal_visible_search_spaces = AsyncMock(return_value=spaces)
    service._recommend_shougang_portal_files = AsyncMock()
    service._list_shougang_portal_hot_read_files = AsyncMock(
        return_value={"data": [], "has_more": True, "next_cursor": "old-cursor"}
    )

    request = ShougangPortalFileBrowseReq(recommendation="latest_selected", sort="relevance", limit=20)
    result = await service._browse_shougang_portal_files_impl(request)

    assert result["has_more"] is True
    assert result["next_cursor"] == "old-cursor"
    service._recommend_shougang_portal_files.assert_not_awaited()


def test_public_fast_path_uses_live_acl_and_rejects_stale_inherited_projection():
    file = SimpleNamespace(id=100, knowledge_id=10, file_level_path="/8")
    stale_projection = SimpleNamespace(permission_scope="inherited")
    live_bindings = [
        {"resource_type": "knowledge_file", "resource_id": "100", "relation": "viewer"},
    ]

    assert stale_projection.permission_scope == "inherited"
    assert KnowledgeSpaceService._can_fast_allow_public_recommendation(
        file,
        public_space_ids={10},
        live_bindings=live_bindings,
    ) is False


def test_non_public_file_never_uses_public_fast_path_after_permission_revocation():
    file = SimpleNamespace(id=101, knowledge_id=11, file_level_path=None)

    assert KnowledgeSpaceService._can_fast_allow_public_recommendation(
        file,
        public_space_ids={10},
        live_bindings=[],
    ) is False


def test_public_fast_path_rejects_current_space_level_custom_binding():
    file = SimpleNamespace(id=101, knowledge_id=10, file_level_path=None)

    assert KnowledgeSpaceService._can_fast_allow_public_recommendation(
        file,
        public_space_ids={10},
        live_bindings=[{"resource_type": "knowledge_space", "resource_id": "10"}],
    ) is False


@pytest.mark.parametrize("request_limit", [1, 10_000])
def test_personalized_target_ignores_request_limit_and_uses_configured_top_n(request_limit):
    assert KnowledgeSpaceService._personalized_recommendation_target_count(
        configured_count=23,
        request_limit=request_limit,
    ) == 23


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tag", "安全"),
        ("space_ids", [10]),
        ("space_level", "public"),
        ("file_ext", "pdf"),
        ("document_type", "STD"),
        ("file_subcategory_code", "RULE"),
        ("business_domain_code", "SC"),
    ],
)
def test_personalized_filter_request_is_not_allowed_to_reuse_base_topn_cache(field, value):
    filtered = ShougangPortalFileBrowseReq(
        recommendation="personalized_v1",
        **{field: value},
    )
    plain = ShougangPortalFileBrowseReq(recommendation="personalized_v1")

    assert KnowledgeSpaceService._personalized_recommendation_uses_base_cache(filtered) is False
    assert KnowledgeSpaceService._personalized_recommendation_uses_base_cache(plain) is True


def test_visible_space_scope_is_stable_and_isolates_different_candidate_sets():
    first = ShougangPortalFileBrowseReq(
        recommendation="personalized_v1",
        space_ids=[20, 10, 20],
        space_level="public",
    )
    same = ShougangPortalFileBrowseReq(
        recommendation="personalized_v1",
        space_ids=[10, 20],
        space_level="public",
    )
    different = ShougangPortalFileBrowseReq(
        recommendation="personalized_v1",
        space_ids=[10],
        space_level="public",
    )

    first_scope = KnowledgeSpaceService._personalized_recommendation_cache_scope(first)
    assert first_scope == KnowledgeSpaceService._personalized_recommendation_cache_scope(same)
    assert first_scope != KnowledgeSpaceService._personalized_recommendation_cache_scope(different)
