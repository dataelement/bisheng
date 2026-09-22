"""查询、服务端合计和明细导出使用同一文档集合。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_CONTENT_STAT_INDEX as INDEX
from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig, DimensionQueryFilter
from bisheng.telemetry_search.domain.services import component, dashboard_export_detail, knowledge_document_reader
from bisheng.telemetry_search.domain.services.knowledge_document_statistics import DocumentStatistics
from test.telemetry_search.test_document_statistics import ts


@pytest.fixture
def setup(monkeypatch):
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == INDEX)
    records = [
        {
            "knowledge_identity": "document:1",
            "file_id": 1,
            "timestamp": ts("2026-08-01") / 1000,
            "uploader_department_name": "A",
        },
        {
            "knowledge_identity": "document:1",
            "file_id": 2,
            "timestamp": ts("2026-09-01") / 1000,
            "uploader_department_name": "B",
        },
        {
            "knowledge_identity": "file:3",
            "file_id": 3,
            "timestamp": ts("2026-09-02") / 1000,
            "uploader_department_name": "B",
        },
    ]
    stats = DocumentStatistics(records, {"document:1": ts("2026-08-03")})
    load = AsyncMock(return_value=stats)

    @asynccontextmanager
    async def reader(index):
        assert index == INDEX
        yield SimpleNamespace(load=load)

    @asynccontextmanager
    async def session():
        yield None

    monkeypatch.setattr(knowledge_document_reader, "document_reader", reader)
    for module in (component, dashboard_export_detail):
        monkeypatch.setattr(module, "get_async_db_session", session)
        monkeypatch.setattr(
            module,
            "DashboardDatasetRepositoryImpl",
            lambda session: SimpleNamespace(find_one=AsyncMock(return_value=dataset)),
        )
    return stats, load


async def test_query_rollups_export_match_with_shared_references(setup):
    _, load = setup
    config = ComponentDataConfig(
        dimensions=[{"fieldId": "uploader_department_name"}],
        metrics=[{"fieldId": field} for field in ("total_file_count", "called_document_count", "document_usage_ratio")],
    )
    query = component.DataQueryService(dataset_code=INDEX, data_config=config)
    result = await query.query_telemetry_data()
    assert result.dimensions == [["A"], ["B"]]
    assert result.value == [[1, 1, 1.0], [2, 1, 0.5]]
    totals = {row["metric_index"]: row["rows"][0]["value"] for row in result.rollups if not row["dimension_indexes"]}
    assert totals == {0: 2, 1: 1, 2: 0.5}
    assert load.call_args.kwargs["include_usage"] is True
    assert {"term": {"tenant_id": 1}} in load.call_args.args[0]
    export = await dashboard_export_detail.query_detail_rows(dataset_code=INDEX, data_config=config, row_limit=100)
    assert len(export.rows) == totals[0]
    shared = next(row for row in export.rows if row["knowledge_identity"] == "document:1")
    assert shared["file_id"] == "1 / 2"
    assert shared["uploader_department_name"] == "A / B"


async def test_month_drilldown_does_not_count_later_share_as_new(setup):
    config = ComponentDataConfig(
        dimensions=[{"fieldId": "timestamp", "timeGranularity": "month"}],
        metrics=[{"fieldId": "new_file_count"}],
    )
    filters = [DimensionQueryFilter(fieldId="timestamp", values=["2026-09"])]
    query = component.DataQueryService(dataset_code=INDEX, data_config=config, dimension_filters=filters)
    result = await query.query_telemetry_data()
    assert result.dimensions == [["2026-09"]]
    assert result.value == [[1]]
    detail = await dashboard_export_detail.query_detail_rows(
        dataset_code=INDEX, data_config=config, dimension_filters=filters, row_limit=100
    )
    assert [row["knowledge_identity"] for row in detail.rows] == ["file:3"]


async def test_export_over_limit_fails_instead_of_truncating(setup):
    from bisheng.common.errcode.telemetry import DashboardExportLimitExceededError

    with pytest.raises(DashboardExportLimitExceededError):
        await dashboard_export_detail.query_detail_rows(
            dataset_code=INDEX,
            data_config=ComponentDataConfig(metrics=[{"fieldId": "total_file_count"}]),
            row_limit=1,
        )


async def test_dynamic_filter_uses_china_day_boundaries(setup):
    from datetime import datetime

    from bisheng.telemetry_search.domain.services.knowledge_document_statistics import CHINA

    config = ComponentDataConfig(
        metrics=[{"fieldId": "document_usage_ratio"}],
        timeFilter={"mode": "dynamic", "type": "recent_days", "recentDays": 1},
    )
    query = component.DataQueryService(dataset_code=INDEX, data_config=config)
    await query.query_telemetry_data()
    start, end = query._document_bounds
    assert datetime.fromtimestamp(start / 1000, CHINA).strftime("%H:%M:%S") == "00:00:00"
    assert datetime.fromtimestamp(end / 1000, CHINA).strftime("%H:%M:%S") == "23:59:59"
