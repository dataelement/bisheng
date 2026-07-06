"""Unit tests for tag_library duplicate-name helpers."""

from types import SimpleNamespace

from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def _tag(name: str, resource_type: str, tag_id: int = 1):
    return SimpleNamespace(id=tag_id, name=name, resource_type=resource_type)


def test_dedupe_non_ai_tag_name_lists_prefers_system_names():
    system, manual = TagLibraryTagService.dedupe_non_ai_tag_name_lists(
        ["安全", "制度"],
        ["安全", "人工"],
    )
    assert system == ["安全", "制度"]
    assert manual == ["人工"]


def test_dedupe_library_tags_by_name_prefers_system_over_manual():
    tags = [
        _tag("安全", "manual_tag", 1),
        _tag("安全", "system_tag", 2),
        _tag("AI标签", "ai_auto_tag", 3),
    ]
    deduped = TagLibraryTagService.dedupe_library_tags_by_name(tags)
    assert len(deduped) == 2
    by_name = {tag.name: tag for tag in deduped}
    assert by_name["安全"].resource_type == "system_tag"
    assert by_name["AI标签"].resource_type == "ai_auto_tag"


def test_dedupe_library_tags_by_name_prefers_ai_over_manual():
    tags = [
        _tag("智能", "manual_tag", 1),
        _tag("智能", "ai_auto_tag", 2),
    ]
    deduped = TagLibraryTagService.dedupe_library_tags_by_name(tags)
    assert len(deduped) == 1
    assert deduped[0].resource_type == "ai_auto_tag"


def test_repair_legacy_returns_deduped_when_system_and_manual_share_name():
    tags = [
        _tag("制度", "system_tag", 10),
        _tag("制度", "manual_tag", 11),
    ]
    repaired = TagLibraryTagService._repair_legacy_library_resource_types_sync(tags)
    assert len(repaired) == 1
    assert repaired[0].resource_type == "system_tag"
    assert repaired[0].id == 10
