from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.services import component as component_module
from bisheng.telemetry_search.domain.services.component import DataQueryService


def _dimension(field_id: str, display_name: str, time_granularity: str | None = None) -> dict:
    return {
        "fieldId": field_id,
        "fieldName": display_name,
        "fieldCode": field_id,
        "displayName": display_name,
        "sort": None,
        "timeGranularity": time_granularity,
    }


def _dataset_config() -> SimpleNamespace:
    return SimpleNamespace(
        es_index_name="pivot-index",
        schema_config={
            "dimensions": [
                {"name": "上传人", "field": "uploader_name", "field_type": "string"},
                {
                    "name": "日期",
                    "field": "timestamp",
                    "field_type": "date",
                    "time_granularitys": ["day"],
                },
                {"name": "分类", "field": "category_name", "field_type": "string"},
            ],
            "metrics": [
                {
                    "name": "新增文件数",
                    "field": "new_file_count",
                    "field_type": "number",
                }
            ],
        },
    )


def _install_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class FakeRepository:
        def __init__(self, session):
            self.session = session

        async def find_one(self, **kwargs):
            return _dataset_config()

    monkeypatch.setattr(component_module, "get_async_db_session", FakeSessionContext)
    monkeypatch.setattr(
        component_module,
        "DashboardDatasetRepositoryImpl",
        FakeRepository,
    )


@pytest.mark.asyncio
async def test_two_pivot_column_dimensions_follow_row_dimensions(monkeypatch):
    _install_repository(monkeypatch)
    captured = {}
    day_timestamp = int(datetime(2026, 8, 20).timestamp() * 1000)

    async def fake_query_all_metrics(self, metric_map, dimension_index, **kwargs):
        captured["dimension_index"] = dimension_index
        captured["dimensions"] = [item.field for item in kwargs["dimensions"]]
        captured["stack_dimension"] = kwargs["stack_dimension"]
        return [["张三", day_timestamp, "政策制度", 3]]

    monkeypatch.setattr(DataQueryService, "query_all_metrics", fake_query_all_metrics)

    config = ComponentDataConfig.model_validate(
        {
            "dimensions": [_dimension("uploader_name", "上传人")],
            "stackDimensions": [
                _dimension("timestamp", "时间(日)", "day"),
                _dimension("category_name", "知识分类"),
            ],
            "metrics": [
                {
                    "fieldId": "new_file_count",
                    "fieldName": "新增文件数",
                    "aggregation": "sum",
                }
            ],
        }
    )

    result = await DataQueryService(
        dataset_code="pivot-test",
        data_config=config,
    ).query_telemetry_data()

    assert captured == {
        "dimension_index": 2,
        "dimensions": ["uploader_name", "timestamp", "category_name"],
        "stack_dimension": None,
    }
    assert result.dimensions == [["张三", "2026-08-20", "政策制度"]]
    assert result.value == [[3]]


@pytest.mark.asyncio
async def test_legacy_single_stack_dimension_keeps_existing_query_path(monkeypatch):
    _install_repository(monkeypatch)
    captured = {}

    async def fake_query_all_metrics(self, metric_map, dimension_index, **kwargs):
        captured["dimension_index"] = dimension_index
        captured["dimensions"] = [item.field for item in kwargs["dimensions"]]
        captured["stack_dimension"] = kwargs["stack_dimension"].field
        return [["张三", "政策制度", 2]]

    monkeypatch.setattr(DataQueryService, "query_all_metrics", fake_query_all_metrics)

    config = ComponentDataConfig.model_validate(
        {
            "dimensions": [_dimension("uploader_name", "上传人")],
            "stackDimension": _dimension("category_name", "知识分类"),
            "metrics": [
                {
                    "fieldId": "new_file_count",
                    "fieldName": "新增文件数",
                    "aggregation": "sum",
                }
            ],
        }
    )

    result = await DataQueryService(
        dataset_code="pivot-test",
        data_config=config,
    ).query_telemetry_data()

    assert captured == {
        "dimension_index": 1,
        "dimensions": ["uploader_name"],
        "stack_dimension": "category_name",
    }
    assert result.dimensions == [["张三", "政策制度"]]
    assert result.value == [[2]]
