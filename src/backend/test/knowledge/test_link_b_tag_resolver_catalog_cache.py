"""Tests for Link B tenant catalog cache (P5)."""

from types import SimpleNamespace
from unittest.mock import patch

from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.knowledge.domain.services.link_b_tag_resolver_catalog_cache import (
    LINK_B_CATALOG_CACHE_TTL,
    LinkBTagResolverCatalogCache,
)
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def setup_function():
    LinkBTagResolverCatalogCache.clear_process_cache_for_tests()


def teardown_function():
    LinkBTagResolverCatalogCache.clear_process_cache_for_tests()


def test_load_uses_process_cache_on_second_call():
    payload = {
        "library_by_key": {"行业情报": "行业情报"},
        "pending_rows": [],
        "resource_type": TagResourceTypeEnum.AI_AUTO_TAG.value,
    }

    with patch.object(LinkBTagResolverCatalogCache, "_load_payload_from_db", return_value=payload) as load_db:
        first = LinkBTagResolverCatalogCache.load_sync(1, TagResourceTypeEnum.AI_AUTO_TAG)
        second = LinkBTagResolverCatalogCache.load_sync(1, TagResourceTypeEnum.AI_AUTO_TAG)

    assert load_db.call_count == 1
    assert first.cache_source == "db"
    assert second.cache_source == "process"
    assert second.library_by_key == {"行业情报": "行业情报"}


def test_load_falls_back_to_db_when_redis_unavailable():
    payload = {
        "library_by_key": {"标签A": "标签A"},
        "pending_rows": [],
        "resource_type": TagResourceTypeEnum.AI_AUTO_TAG.value,
    }

    with (
        patch.object(LinkBTagResolverCatalogCache, "_get_redis_cache", return_value=None),
        patch.object(LinkBTagResolverCatalogCache, "_set_redis_cache") as set_redis,
        patch.object(LinkBTagResolverCatalogCache, "_load_payload_from_db", return_value=payload),
    ):
        snapshot = LinkBTagResolverCatalogCache.load_sync(2, TagResourceTypeEnum.AI_AUTO_TAG)

    assert snapshot.cache_source == "db"
    assert snapshot.library_by_key == {"标签A": "标签A"}
    set_redis.assert_called_once()


def test_invalidate_clears_process_and_redis():
    payload = {
        "library_by_key": {"标签B": "标签B"},
        "pending_rows": [],
        "resource_type": TagResourceTypeEnum.AI_AUTO_TAG.value,
    }

    with (
        patch.object(LinkBTagResolverCatalogCache, "_load_payload_from_db", return_value=payload),
        patch.object(LinkBTagResolverCatalogCache, "_delete_redis_cache") as delete_redis,
    ):
        LinkBTagResolverCatalogCache.load_sync(3, TagResourceTypeEnum.AI_AUTO_TAG)
        LinkBTagResolverCatalogCache.invalidate_sync(3)
        reloaded = LinkBTagResolverCatalogCache.load_sync(3, TagResourceTypeEnum.AI_AUTO_TAG)

    delete_redis.assert_called_once_with(3)
    assert reloaded.cache_source == "db"


def test_tag_library_service_load_delegates_to_cache():
    snapshot = SimpleNamespace(
        library_by_key={"正式": "正式"},
        pending_catalog=[],
        library_names=["正式"],
        cache_source="redis",
    )
    with patch.object(LinkBTagResolverCatalogCache, "load_sync", return_value=snapshot) as load_sync:
        result = TagLibraryTagService.load_link_b_tenant_catalog_sync(9, TagResourceTypeEnum.AI_AUTO_TAG)

    load_sync.assert_called_once_with(9, TagResourceTypeEnum.AI_AUTO_TAG)
    assert result is snapshot


def test_invalidate_link_b_tenant_catalog_cache_sync_delegates():
    with patch.object(LinkBTagResolverCatalogCache, "invalidate_sync") as invalidate:
        TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_sync(5)

    invalidate.assert_called_once_with(5)


def test_cache_ttl_within_p5_range():
    assert 60 <= LINK_B_CATALOG_CACHE_TTL <= 300
