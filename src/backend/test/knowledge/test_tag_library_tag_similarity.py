"""Unit tests for Link B tag resolver helpers."""

from types import SimpleNamespace

from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def test_normalize_tag_name_key_strips_spaces_and_nfkc():
    assert TagLibraryTagService.normalize_tag_name_key("  行业情报  ") == "行业情报"
    assert TagLibraryTagService.normalize_tag_name_key("ＡＢＣ") == "ABC"


def test_find_exact_tag_name_matches_normalized_key():
    catalog = {TagLibraryTagService.normalize_tag_name_key("行业情报"): "行业情报"}
    canonical, kind = TagLibraryTagService.find_exact_tag_name(" 行业情报 ", catalog)
    assert canonical == "行业情报"
    assert kind == "exact"


def test_find_exact_tag_name_does_not_fuzzy_match():
    catalog = {TagLibraryTagService.normalize_tag_name_key("行业情报"): "行业情报"}
    canonical, kind = TagLibraryTagService.find_exact_tag_name("行业情报分析", catalog)
    assert canonical is None
    assert kind == "new"


def test_find_similar_tag_name_substring_match():
    entries = [
        ("机器学习-模型训练", TagLibraryTagService.normalize_tag_name_key("机器学习-模型训练")),
    ]
    canonical, kind, score = TagLibraryTagService.find_similar_tag_name("机器学习", entries)
    assert canonical == "机器学习-模型训练"
    assert kind == "substring"
    assert score is None


def test_find_similar_tag_name_similarity_match():
    canonical_label = "机器学习模型训练方法"
    entries = [
        (canonical_label, TagLibraryTagService.normalize_tag_name_key(canonical_label)),
    ]
    canonical, kind, score = TagLibraryTagService.find_similar_tag_name("机器学习模型训炼方法", entries)
    assert canonical == canonical_label
    assert kind == "similarity"
    assert score is not None
    assert score >= 0.85


def test_resolve_prefers_approved_over_pending():
    library_by_key = {TagLibraryTagService.normalize_tag_name_key("行业情报"): "行业情报"}
    pending_catalog = [
        SimpleNamespace(id=1, name="行业情报", resource_type="ai_auto_tag"),
    ]
    batch = TagLibraryTagService.resolve_link_b_tag_candidates_sync(
        tenant_id=1,
        candidates=["行业情报"],
        library_by_key=library_by_key,
        pending_catalog=pending_catalog,
    )
    assert len(batch.entries) == 1
    assert batch.entries[0].target == "approved"
    assert batch.entries[0].canonical_name == "行业情报"


def test_resolve_pending_similar_and_new():
    pending_catalog = [
        SimpleNamespace(id=2, name="机器学习-模型训练", resource_type="ai_auto_tag"),
    ]
    batch = TagLibraryTagService.resolve_link_b_tag_candidates_sync(
        tenant_id=1,
        candidates=["机器学习", "全新概念标签"],
        library_by_key={},
        pending_catalog=pending_catalog,
    )
    assert [entry.canonical_name for entry in batch.entries] == ["机器学习-模型训练", "全新概念标签"]
    assert batch.entries[0].target == "pending"
    assert batch.entries[0].match_kind == "substring"
    assert batch.entries[1].match_kind == "new"


def test_pick_best_library_tag_from_rows_prefers_system_tag():
    tags = [
        SimpleNamespace(id=1, name="安全", resource_type="manual_tag"),
        SimpleNamespace(id=2, name="安全", resource_type="system_tag"),
    ]
    picked = TagLibraryTagService._pick_best_library_tag_from_rows(tags)
    assert picked.resource_type == "system_tag"
    assert picked.id == 2
