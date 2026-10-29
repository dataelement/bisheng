# ruff: noqa: RUF002, RUF003
"""独立业务期望：引用、时间和分组之间不能重复累计同一文档。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from bisheng.telemetry_search.domain.services.knowledge_document_statistics import DocumentStatistics


def ts(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)


def test_documents_across_groups_dates_and_external_usage():
    records = [
        {"knowledge_identity": "document:10", "timestamp": ts("2026-08-01") / 1000, "file_id": 1, "org": "A"},
        {"knowledge_identity": "document:10", "timestamp": ts("2026-09-01") / 1000, "file_id": 2, "org": "B"},
        {"knowledge_identity": "file:10", "timestamp": ts("2026-09-02") / 1000, "file_id": 10, "org": "B"},
    ]
    stats = DocumentStatistics(records, {"document:10": ts("2026-08-03")})
    assert stats.aggregate([], "total_file_count") == [[2]]
    assert stats.aggregate([("org", None)], "total_file_count") == [["A", 1], ["B", 2]]
    assert stats.aggregate([], "called_document_count") == [[1]]
    assert stats.aggregate([], "document_usage_ratio") == [[0.5]]
    assert stats.aggregate([], "new_file_count", start=ts("2026-09-01"), end=ts("2026-09-30")) == [[1]]
    timeline = stats.aggregate(
        [("timestamp", "month")], "total_file_count", start=ts("2026-08-01"), end=ts("2026-09-30")
    )
    assert timeline == [[ts("2026-08-01"), 1], [ts("2026-09-01"), 2]]
    # 组织 A 的知识在 B 中调用仍计入，只限制库存所属组织。
    assert DocumentStatistics(records[:1], stats.called_at).aggregate([], "document_usage_ratio") == [[1.0]]


def test_contribution_ratio_assigns_each_document_to_its_earliest_group():
    stats = DocumentStatistics(
        [
            {"knowledge_identity": "document:1", "timestamp": ts("2026-08-01") / 1000, "file_id": 1, "level": "科室库"},
            {"knowledge_identity": "document:1", "timestamp": ts("2026-09-01") / 1000, "file_id": 2, "level": "公共库"},
            {"knowledge_identity": "document:2", "timestamp": ts("2026-09-02") / 1000, "file_id": 3, "level": "公共库"},
        ],
        {},
    )
    rows = stats.aggregate([("level", None)], "knowledge_contribution_ratio")
    assert rows == [["公共库", 0.5], ["科室库", 0.5]]
    assert sum(row[-1] for row in rows) == 1


def test_empty_and_missing_identity():
    import pytest

    assert DocumentStatistics([], {}).aggregate([], "document_usage_ratio") == [[0.0]]
    with pytest.raises(ValueError, match="重建"):
        DocumentStatistics([{"file_id": 1, "timestamp": 1}], {})


def test_category_conflict_including_missing_category_is_not_silently_split():
    import pytest

    for second in (None, "STD"):
        stats = DocumentStatistics(
            [
                {"knowledge_identity": "document:1", "file_id": 1, "timestamp": 1, "file_category_code": "POL"},
                {"knowledge_identity": "document:1", "file_id": 2, "timestamp": 1, "file_category_code": second},
            ],
            {},
        )
        assert stats.aggregate([], "total_file_count") == [[1]]
        assert len(stats.detail("total_file_count", start=None, end=None)) == 1
        from bisheng.common.errcode.telemetry import DocumentCategoryConflictError

        with pytest.raises(DocumentCategoryConflictError):
            stats.aggregate([("file_category_code", None)], "total_file_count")
        assert stats.conflict_samples()[0]["file_ids"] == [1, 2]


def test_category_codes_are_normalized_without_mutating_input():
    records = [
        {"knowledge_identity": "document:1", "timestamp": 1, "file_category_code": " pol "},
        {"knowledge_identity": "document:1", "timestamp": 1, "file_category_code": "POL"},
    ]
    stats = DocumentStatistics(records, {})
    assert stats.aggregate([("file_category_code", None)], "total_file_count") == [["POL", 1]]
    assert records[0]["file_category_code"] == " pol "


def test_time_boundaries_contribution_and_call_union():
    import pytest

    stats = DocumentStatistics(
        [
            {"knowledge_identity": "document:1", "timestamp": ts("2026-08-01") / 1000, "org": "A"},
            {"knowledge_identity": "document:1", "timestamp": ts("2026-08-02") / 1000, "org": "B"},
        ],
        {"document:1": ts("2026-08-03")},
    )
    assert stats.aggregate([], "called_document_count", end=ts("2026-08-02T23:59:59")) == [[0]]
    assert stats.aggregate([], "called_document_count", end=ts("2026-08-03T23:59:59")) == [[1]]
    # 同一文档两个入口只归最早的组织, 占比合计为 100%.
    assert stats.aggregate([("org", None)], "knowledge_contribution_ratio") == [["A", 1.0]]
    assert stats.aggregate([], "knowledge_contribution_ratio") == [[1.0]]
    assert stats.aggregate([], "total_file_count", start=2, end=1) == []
    with pytest.raises(ValueError, match="日统计"):
        stats.aggregate([("timestamp", "hour")], "called_document_count")
