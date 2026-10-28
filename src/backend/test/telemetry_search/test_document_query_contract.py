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
    for index, record in enumerate(records):
        record["original_space_name"] = "最初科室库" if index < 2 else "其他原始库"
        for level in ("company", "department", "office", "squad"):
            record[f"original_upload_{level}_name"] = "原始组织A" if index < 2 else "原始组织B"
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
    monkeypatch.setattr(component, "resolve_dimension_labels", AsyncMock(return_value={}))
    for module in (component, dashboard_export_detail):
        monkeypatch.setattr(module, "get_async_db_session", session)
        monkeypatch.setattr(
            module,
            "DashboardDatasetRepositoryImpl",
            lambda session: SimpleNamespace(find_one=AsyncMock(return_value=dataset)),
        )
    return stats, load


@pytest.mark.parametrize("field", ["original_space_name"])
async def test_original_dimensions_group_export_and_preserve_filter_values(setup, field):
    _, load = setup
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == INDEX)
    label = next(item["name"] for item in dataset.schema_config["dimensions"] if item["field"] == field)
    config = ComponentDataConfig(
        dimensions=[{"fieldId": field, "displayName": label}],
        metrics=[{"fieldId": "total_file_count"}],
    )
    result = await component.DataQueryService(dataset_code=INDEX, data_config=config).query_telemetry_data()
    assert len(result.dimensions) == 2
    assert result.value == [[1], [1]]
    totals = [row for row in result.rollups if not row["dimension_indexes"]]
    assert totals[0]["rows"][0]["value"] == 2
    name = "最初科室库" if field == "original_space_name" else "原始组织A"
    detail = await dashboard_export_detail.query_detail_rows(
        dataset_code=INDEX,
        data_config=config,
        dimension_filters=[DimensionQueryFilter(fieldId=field, values=[name])],
        row_limit=100,
    )
    assert any(column.field == field and column.label.startswith("原始") for column in detail.columns)
    assert name in str(load.call_args.args[0])
    assert field in str(load.call_args.args[0])


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


async def test_detail_export_includes_all_documents_beyond_pivot_display_limit(setup):
    _, load = setup
    load.return_value = DocumentStatistics(
        [
            {
                "knowledge_identity": f"document:{index}",
                "file_id": index,
                "timestamp": ts("2026-09-01") / 1000,
                "uploader_department_name": "生产部",
            }
            for index in range(1, 602)
        ],
        {},
    )
    detail = await dashboard_export_detail.query_detail_rows(
        dataset_code=INDEX,
        data_config=ComponentDataConfig(
            dimensions=[{"fieldId": "uploader_department_name"}],
            metrics=[{"fieldId": "total_file_count"}],
            resultLimit={"limitType": "limited", "limit": 1},
        ),
        row_limit=50_000,
    )
    assert len(detail.rows) == 601
    assert {row["knowledge_identity"] for row in detail.rows} == {f"document:{index}" for index in range(1, 602)}


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


@pytest.mark.parametrize("category_mode", [None, "dimension", "stack", "columns", "filter"])
async def test_category_conflict_isolated_from_unrelated_queries_and_exports(setup, category_mode):
    stats, load = setup
    records = [dict(row) for row in stats.records]
    records[0].update(file_category_code="POL", file_category_name="政策")
    records[1].update(file_category_code="STD", file_category_name="标准")
    load.return_value = DocumentStatistics(records, stats.called_at)
    options = {"metrics": [{"fieldId": "total_file_count"}]}
    filters = []
    if category_mode == "dimension":
        options["dimensions"] = [{"fieldId": "file_category_name"}]
    elif category_mode == "stack":
        options["stackDimension"] = {"fieldId": "file_category_name"}
    elif category_mode == "columns":
        options["stackDimensions"] = [{"fieldId": "file_category_name"}]
    elif category_mode == "filter":
        filters = [DimensionQueryFilter(fieldId="file_category_name", values=["政策", "标准"])]
    config = ComponentDataConfig(**options)
    query = component.DataQueryService(dataset_code=INDEX, data_config=config, dimension_filters=filters)
    if category_mode:
        from bisheng.common.errcode.telemetry import DocumentCategoryConflictError

        with pytest.raises(DocumentCategoryConflictError) as error:
            await query.query_telemetry_data()
        assert error.value.Code == 17021
        with pytest.raises(DocumentCategoryConflictError):
            await dashboard_export_detail.query_detail_rows(
                dataset_code=INDEX,
                data_config=config,
                dimension_filters=filters,
                row_limit=100,
            )
    else:
        result = await query.query_telemetry_data()
        assert result.value == [[2]]
        detail = await dashboard_export_detail.query_detail_rows(dataset_code=INDEX, data_config=config, row_limit=100)
        assert len(detail.rows) == 2


def test_category_dependency_checks_nested_filters_not_filter_values():
    from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, TermOp
    from bisheng.telemetry_search.domain.services.knowledge_document_statistics import uses_category_fields

    nested = FilterExpression(
        bool_operator="must",
        filters=[
            FilterExpression(bool_operator="should", filters=[TermOp(field="file_subcategory_code", value="POL-01")]),
        ],
    )
    assert uses_category_fields([], [nested])
    assert not uses_category_fields(
        [],
        [
            FilterExpression(
                bool_operator="must",
                filters=[TermOp(field="file_name", value="file_category_code")],
            )
        ],
    )


@pytest.mark.parametrize(
    "values, expected",
    [
        ([None], {"bool": {"must_not": [{"exists": {"field": "uploader_department_name"}}]}}),
        (["未分类"], {"terms": {"uploader_department_name": ["未分类"]}}),
        ([""], {"terms": {"uploader_department_name": [""]}}),
        (
            [None, "生产部"],
            {
                "bool": {
                    "should": [
                        {"terms": {"uploader_department_name": ["生产部"]}},
                        {"bool": {"must_not": [{"exists": {"field": "uploader_department_name"}}]}},
                    ]
                }
            },
        ),
    ],
)
async def test_missing_department_export_preserves_missing_semantics_and_other_filters(setup, values, expected):
    _, load = setup
    filters = [
        DimensionQueryFilter(fieldId="uploader_department_name", values=values),
        DimensionQueryFilter(fieldId="belonging_company_name", values=["首钢"]),
    ]
    config = ComponentDataConfig(
        dimensions=[{"fieldId": "uploader_department_name"}],
        metrics=[{"fieldId": "total_file_count"}],
    )
    await dashboard_export_detail.query_detail_rows(
        dataset_code=INDEX,
        data_config=config,
        dimension_filters=filters,
        row_limit=100,
    )
    clauses = load.call_args.args[0]
    assert clauses[0] == {
        "bool": {
            "must": [
                expected,
                {"terms": {"belonging_company_name": ["首钢"]}},
            ]
        }
    }
    assert {"term": {"tenant_id": 1}} in clauses
    assert {"terms": {"space_level": ["public", "department", "team", "team_ks", "personal"]}} in clauses


@pytest.mark.parametrize(
    "values, identities",
    [
        ([None], ["document:1"]),
        (["未分类"], ["document:3"]),
        ([""], ["document:4"]),
        ([None, "未分类"], ["document:1", "document:3"]),
    ],
)
async def test_missing_department_query_and_detail_select_same_documents(setup, monkeypatch, values, identities):
    from test.telemetry_search.test_document_reader import ES

    records = [
        {"file_id": 1, "knowledge_identity": "document:1"},
        {"file_id": 2, "knowledge_identity": "document:1", "uploader_department_name": None},
        {"file_id": 3, "knowledge_identity": "document:3", "uploader_department_name": "未分类"},
        {"file_id": 4, "knowledge_identity": "document:4", "uploader_department_name": ""},
        {"file_id": 5, "knowledge_identity": "document:5", "tenant_id": 2},
        {"file_id": 6, "knowledge_identity": "document:6", "belonging_company_name": "其他公司"},
        {"file_id": 7, "knowledge_identity": "document:7", "timestamp": ts("2026-10-01") / 1000},
    ]
    records = [
        {
            "record_type": "file",
            "file_type": 1,
            "tenant_id": 1,
            "space_level": "public",
            "belonging_company_name": "首钢",
            "timestamp": ts("2026-09-02") / 1000,
            **record,
        }
        for record in records
    ]

    @asynccontextmanager
    async def reader(index):
        yield knowledge_document_reader.DocumentReader(ES(records), index)

    monkeypatch.setattr(knowledge_document_reader, "document_reader", reader)
    filters = [
        DimensionQueryFilter(fieldId="uploader_department_name", values=values),
        DimensionQueryFilter(fieldId="belonging_company_name", values=["首钢"]),
    ]
    config = ComponentDataConfig(
        dimensions=[{"fieldId": "uploader_department_name"}],
        metrics=[{"fieldId": "total_file_count"}],
        timeFilter={
            "mode": "fixed",
            "type": "custom",
            "startDate": ts("2026-09-01") // 1000,
            "endDate": ts("2026-09-30T23:59:59") // 1000,
        },
    )
    query = await component.DataQueryService(
        dataset_code=INDEX,
        data_config=config,
        dimension_filters=filters,
    ).query_telemetry_data()
    detail = await dashboard_export_detail.query_detail_rows(
        dataset_code=INDEX,
        data_config=config,
        dimension_filters=filters,
        row_limit=100,
    )
    assert [row["knowledge_identity"] for row in detail.rows] == identities
    assert sum(row[0] for row in query.value) == len(identities)
