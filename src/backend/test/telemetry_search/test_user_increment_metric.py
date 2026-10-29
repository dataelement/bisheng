from copy import deepcopy

import pytest

from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.models.dashboard_dataset import SchemaConfig
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, RangeOp, RangeValue, TermOp
from bisheng.telemetry_search.domain.services import component
from bisheng.telemetry_search.domain.services.dashboard_export_detail import _metric_filter
from bisheng.telemetry_search.domain.services.search_engine_service import QueryBuilder


def metrics():
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == "mid_user_increment")
    return {metric.field: metric for metric in SchemaConfig(**dataset.schema_config).metrics}


async def test_new_users_excludes_existing_users_activity_and_preserves_chart_filters(monkeypatch):
    records = [
        {"user_id": 1, "metric_source": "increment", "primary_department_id": "A"},
        {"user_id": 2, "metric_source": "active_user", "primary_department_id": "A"},
        {"user_id": 3, "metric_source": "participation", "primary_department_id": "A"},
        {"user_id": 4, "metric_source": "increment", "primary_department_id": "B"},
    ]
    filters = [
        FilterExpression(
            bool_operator="must",
            filters=[
                TermOp(field="primary_department_id", value="A"),
                RangeOp(field="timestamp", value=RangeValue(gte=1000, lt=2000)),
            ],
        )
    ]
    original_filters = deepcopy(filters)

    async def search(service):
        query = QueryBuilder(service.parameters).build_query_dsl()["query"]["bool"]["must"]
        assert {"term": {"primary_department_id": "A"}} in query
        assert {"range": {"timestamp": {"gte": 1000, "lt": 2000}}} in query
        terms = [item["term"] for item in query if "term" in item]
        users = {
            row["user_id"]
            for row in records
            if all(row.get(field) == value for term in terms for field, value in term.items())
        }
        return [[len(users)]]

    monkeypatch.setattr(component.SearchEngineService, "search", search)
    service = component.DataQueryService(dataset_code="mid_user_increment", data_config=ComponentDataConfig())
    result = await service.query_one_metric(
        metrics()["new_user_count"],
        "sum",
        -1,
        index_name="mid_user_engagement_stat",
        dimensions=[],
        stack_dimension=None,
        filters=filters,
    )
    assert result == [[1]]
    assert filters == original_filters


def test_new_user_export_uses_creation_source_and_active_metric_uses_logins():
    metric_map = metrics()
    assert _metric_filter(metric_map["new_user_count"]).to_dsl() == {
        "must": [{"term": {"metric_source": "increment"}}],
    }
    assert _metric_filter(metric_map["active_user_count"]).to_dsl() == {
        "must": [
            {"term": {"metric_source": "participation"}},
            {"term": {"logged_in": True}},
        ],
    }
    assert metric_map["active_user_count"].aggregations[0].type == "cardinality"
    assert metric_map["active_user_count"].aggregations[0].field == "user_id"


@pytest.mark.parametrize("code", ["mid_user_increment", "mid_user_daily_participation"])
def test_login_metric_only_changes_name(code):
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == code)
    metric = next(item for item in dataset.schema_config["metrics"] if item["field"] == "logged_in_employee_count")
    assert metric["name"] == "累计登录人次"
    assert metric["calculation"] == "login_participation"
