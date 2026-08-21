from unittest.mock import AsyncMock

import pytest

from bisheng.telemetry_search.domain.models.dashboard_dataset import (
    FormulaEnum,
    MetricConfig,
    VirtualMetricCalculationEnum,
)
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    AggsTypeEnum,
    FilterExpression,
    RangeOp,
    RangeValue,
    TermOp,
    TermsOp,
)
from bisheng.telemetry_search.domain.services import component as component_module
from bisheng.telemetry_search.domain.services.component import DataQueryService


def _dimension(field: str) -> AggregationExpression:
    return AggregationExpression(name=field, type=AggsTypeEnum.TERMS, field=field)


def _share_metric() -> MetricConfig:
    return MetricConfig(
        field="knowledge_contribution_ratio",
        name="知识贡献占比",
        is_virtual=True,
        calculation=VirtualMetricCalculationEnum.SHARE_OF_TOTAL,
        filter=FilterExpression(
            bool_operator="must",
            filters=[TermOp(field="record_type", value="file")],
        ),
        aggregations=[
            AggregationExpression(
                name="knowledge_contribution_count",
                type=AggsTypeEnum.VALUE_COUNT,
                field="file_id",
            )
        ],
    )


def _service() -> DataQueryService:
    return DataQueryService(dataset_code="test", data_config=ComponentDataConfig())


def _install_search_results(monkeypatch, *results):
    calls = []
    pending_results = iter(results)

    class FakeSearchEngineService:
        def __init__(self, parameters):
            calls.append(parameters)

        async def search(self):
            return next(pending_results)

    monkeypatch.setattr(component_module, "SearchEngineService", FakeSearchEngineService)
    return calls


@pytest.mark.parametrize(
    "dimension_field",
    [
        "category_name",
        "business_domain_name",
        "space_name",
        "uploader_name",
        "belonging_department_name",
    ],
)
@pytest.mark.asyncio
async def test_share_of_total_uses_current_filtered_file_total_for_any_single_dimension(
    monkeypatch,
    dimension_field,
):
    calls = _install_search_results(
        monkeypatch,
        [["A", 30], ["B", 20]],
        [[100]],
    )

    result = await _service().query_one_metric(
        _share_metric(),
        aggregation="sum",
        dimension_index=0,
        index_name="test-index",
        dimensions=[_dimension(dimension_field)],
        stack_dimension=None,
        filters=None,
    )

    assert result == [["A", 0.3], ["B", 0.2]]
    assert [dimension.field for dimension in calls[0].dimensions] == [dimension_field]
    assert calls[1].dimensions == []
    assert calls[1].stack_dimension is None
    assert sum(row[-1] for row in result) == 0.5


@pytest.mark.asyncio
async def test_share_of_total_removes_all_dimensions_and_stack_only_from_denominator(monkeypatch):
    calls = _install_search_results(
        monkeypatch,
        [
            ["2026-08", "炼钢", "一部", 15],
            ["2026-08", "炼钢", "二部", 5],
            ["2026-08", "轧钢", "一部", 10],
        ],
        [[100]],
    )

    result = await _service().query_one_metric(
        _share_metric(),
        aggregation="sum",
        dimension_index=2,
        index_name="test-index",
        dimensions=[_dimension("timestamp"), _dimension("business_domain_name")],
        stack_dimension=_dimension("belonging_department_name"),
        filters=None,
    )

    assert result == [
        ["2026-08", "炼钢", "一部", 0.15],
        ["2026-08", "炼钢", "二部", 0.05],
        ["2026-08", "轧钢", "一部", 0.1],
    ]
    assert [dimension.field for dimension in calls[0].dimensions] == [
        "timestamp",
        "business_domain_name",
    ]
    assert calls[0].stack_dimension.field == "belonging_department_name"
    assert calls[1].dimensions == []
    assert calls[1].stack_dimension is None


@pytest.mark.asyncio
async def test_share_of_total_keeps_dataset_dashboard_link_and_time_filters(monkeypatch):
    calls = _install_search_results(monkeypatch, [["炼钢", 25]], [[100]])
    runtime_filters = [
        FilterExpression(
            bool_operator="must",
            filters=[TermsOp(field="space_id", value=["space-1", "space-2"])],
        ),
        FilterExpression(
            bool_operator="must",
            filters=[
                RangeOp(
                    field="timestamp",
                    value=RangeValue(gte=1_785_513_600_000, lte=1_788_105_599_000),
                )
            ],
        ),
    ]

    result = await _service().query_one_metric(
        _share_metric(),
        aggregation="sum",
        dimension_index=0,
        index_name="test-index",
        dimensions=[_dimension("business_domain_name")],
        stack_dimension=None,
        filters=runtime_filters,
    )

    assert result == [["炼钢", 0.25]]
    numerator_filters = [item.model_dump() for item in calls[0].filters]
    denominator_filters = [item.model_dump() for item in calls[1].filters]
    assert numerator_filters == denominator_filters
    assert len(numerator_filters) == 3
    assert numerator_filters[-1]["filters"][0]["field"] == "record_type"


@pytest.mark.asyncio
@pytest.mark.parametrize("denominator_result", [[], [[0]]])
async def test_share_of_total_returns_zero_when_denominator_is_missing_or_zero(
    monkeypatch,
    denominator_result,
):
    _install_search_results(monkeypatch, [["一部", 2], ["二部", 1]], denominator_result)

    result = await _service().query_one_metric(
        _share_metric(),
        aggregation="sum",
        dimension_index=0,
        index_name="test-index",
        dimensions=[_dimension("belonging_department_name")],
        stack_dimension=None,
        filters=None,
    )

    assert result == [["一部", 0], ["二部", 0]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("numerator_result", "denominator_result", "expected"),
    [
        ([[100]], [[100]], [[1.0]]),
        ([[0]], [[0]], [[0]]),
    ],
)
async def test_share_of_total_without_dimensions_returns_overall_ratio(
    monkeypatch,
    numerator_result,
    denominator_result,
    expected,
):
    calls = _install_search_results(monkeypatch, numerator_result, denominator_result)

    result = await _service().query_one_metric(
        _share_metric(),
        aggregation="sum",
        dimension_index=-1,
        index_name="test-index",
        dimensions=[],
        stack_dimension=None,
        filters=None,
    )

    assert result == expected
    assert calls[0].dimensions == calls[1].dimensions == []


@pytest.mark.asyncio
async def test_existing_divide_metric_still_uses_formula_query_path(monkeypatch):
    service = _service()
    query_formula_metric = AsyncMock(return_value=[[0.5]])
    monkeypatch.setattr(DataQueryService, "query_formula_metric", query_formula_metric)
    metric = MetricConfig(
        field="existing_ratio",
        name="既有占比",
        is_virtual=True,
        formula=FormulaEnum.DIVIDE,
        aggregations=[
            AggregationExpression(name="first", type=AggsTypeEnum.VALUE_COUNT, field="file_id"),
            AggregationExpression(name="second", type=AggsTypeEnum.VALUE_COUNT, field="file_id"),
        ],
    )

    result = await service.query_one_metric(metric, aggregation="sum", dimension_index=-1)

    assert result == [[0.5]]
    query_formula_metric.assert_awaited_once()
