from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.telemetry import QueryMetricNotFoundError
from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.services import component


@pytest.fixture
def query_datasets(monkeypatch):
    datasets = {dataset.dataset_code: dataset for dataset in DASHBOARD_DATASET}
    find_one = AsyncMock(side_effect=lambda dataset_code: datasets.get(dataset_code))

    @asynccontextmanager
    async def session():
        yield None

    monkeypatch.setattr(component, "get_async_db_session", session)
    monkeypatch.setattr(component.DashboardDatasetRepositoryImpl, "find_one", find_one)
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(component.DataQueryService, "query_one_metric", search)
    return find_one, search


@pytest.mark.parametrize(
    ("old_dataset", "correct_dataset", "metrics"),
    [
        (
            "mid_doc_parse_dtl",
            "mid_knowledge_increment",
            ["total_document_knowledge_base_count", "total_qa_knowledge_base_count"],
        ),
        ("mid_doc_parse_dtl", "mid_knowledge_increment", ["total_qa_knowledge_base_count"]),
        ("mid_session_run_dtl", "mid_user_increment", ["new_user_count"]),
    ],
)
async def test_legacy_chart_queries_its_original_metric_dataset(query_datasets, old_dataset, correct_dataset, metrics):
    _, search = query_datasets
    query = component.DataQueryService(
        dataset_code=old_dataset,
        data_config=ComponentDataConfig(
            metrics=[{"fieldId": field, "aggregation": "sum"} for field in metrics],
            dimensions=[{"fieldId": "timestamp", "timeGranularity": "day"}],
        ),
    )
    await query.query_telemetry_data()
    assert [call.args[0].field for call in search.await_args_list] == metrics
    assert {call.kwargs["index_name"] for call in search.await_args_list} == {correct_dataset}


async def test_unrecognized_metric_is_not_redirected(query_datasets):
    find_one, search = query_datasets
    query = component.DataQueryService(
        dataset_code="mid_doc_parse_dtl",
        data_config=ComponentDataConfig(metrics=[{"fieldId": "unknown_metric", "aggregation": "sum"}]),
    )
    with pytest.raises(QueryMetricNotFoundError):
        await query.query_telemetry_data()
    find_one.assert_awaited_once_with(dataset_code="mid_doc_parse_dtl")
    search.assert_not_awaited()
