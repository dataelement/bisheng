from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig, DimensionField, TimeFilter
from bisheng.telemetry_search.domain.schemas.query_builder import AggregationExpression, FilterExpression, TermOp
from bisheng.telemetry_search.domain.services import component, login_participation
from bisheng.telemetry_search.domain.services.search_engine_service import QueryBuilder
from test.telemetry_search.test_login_participation import date_filters, midnight, record, time_dimension


@pytest.fixture
def user_statistics(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def dataset(**kwargs):
        return next(item for item in DASHBOARD_DATASET if item.dataset_code == kwargs["dataset_code"])

    monkeypatch.setattr(component, "get_async_db_session", Session)
    monkeypatch.setattr(component, "DashboardDatasetRepositoryImpl", lambda _: SimpleNamespace(find_one=dataset))
    history_queries, active_queries = [], []

    async def records(index, query, fields):
        history_queries.append(query)
        for user, day in [(1, "2026-07-01"), (2, "2026-07-02"), (3, "2026-08-01"), (2, "2026-08-02")]:
            yield record(user, day, primary_department_name="A")

    async def active_search(service):
        query = QueryBuilder(service.parameters).build_query_dsl()
        active_queries.append(query)
        assert service.parameters.metrics[0].field == "user_id"
        assert service.parameters.metrics[0].type == "cardinality"
        assert {"term": {"metric_source": "participation"}} in query["query"]["bool"]["must"]
        assert {"term": {"logged_in": True}} in query["query"]["bool"]["must"]
        assert "primary_department_name" in str(query["query"])
        assert str(midnight(date(2026, 8, 1))) in str(query["query"])
        return [[2]]

    monkeypatch.setattr(login_participation, "read_login_records", records)
    monkeypatch.setattr(component.SearchEngineService, "search", active_search)
    return history_queries, active_queries


def query(fields, *, dataset="mid_user_increment"):
    return component.DataQueryService(
        dataset_code=dataset,
        data_config=ComponentDataConfig(
            metrics=[{"fieldId": field} for field in fields],
            timeFilter={
                "mode": "fixed",
                "startDate": midnight(date(2026, 8, 1)) // 1000,
                "endDate": midnight(date(2026, 8, 31)) // 1000 + 86399,
            },
        ),
        dimension_filters=[{"fieldId": "primary_department_name", "values": ["A"]}],
    )


@pytest.mark.parametrize(
    "dataset, fields, expected",
    [
        (
            "mid_user_increment",
            ["participation_rate", "active_user_count", "active_employee_count", "logged_in_employee_count"],
            [2 / 3, 2, 3, 2],
        ),
        ("mid_user_increment", ["active_user_count", "participation_rate"], [2, 2 / 3]),
        ("mid_user_daily_participation", ["participation_rate"], [2 / 3]),
    ],
)
async def test_ratio_reuses_filtered_active_users_across_entries(user_statistics, dataset, fields, expected):
    result = await query(fields, dataset=dataset).query_telemetry_data()
    assert result.value[0] == pytest.approx(expected)
    history, active = user_statistics
    assert len(history) == len(active) == 1
    assert "gte" not in str(history[0])


async def test_direct_ratio_query_uses_active_user_aggregation(user_statistics):
    filters = date_filters("2026-08-01", "2026-08-31")
    filters.append(FilterExpression(bool_operator="must", filters=[TermOp(field="primary_department_name", value="A")]))
    result = await login_participation.query_login_participation(
        "participation_rate",
        index_name="users",
        dimensions=[],
        stack_dimension=None,
        filters=filters,
    )
    assert result == [[2 / 3]]
    assert len(user_statistics[1]) == 1


async def test_ratio_does_not_hide_active_query_failure(user_statistics, monkeypatch):
    monkeypatch.setattr(
        component.SearchEngineService, "search", AsyncMock(side_effect=RuntimeError("active query failed"))
    )
    with pytest.raises(RuntimeError, match="active query failed"):
        await query(["participation_rate"]).query_telemetry_data()


def test_ratio_matches_group_and_date_keys_and_handles_empty_population():
    population = login_participation.LoginPopulation(
        [AggregationExpression(field="primary_department_name", type="terms"), time_dimension("day")],
        login_participation.LoginSelection(date_filters("2026-08-01", "2026-08-02")),
    )
    population.add(record(1, "2026-07-01", primary_department_name="A"))
    population.add(record(2, "2026-08-01", primary_department_name="A"))
    rows = population.rows(
        "participation_rate",
        active_rows=[
            ["B", midnight(date(2026, 8, 1)), 4],
            ["A", midnight(date(2026, 8, 2)), 2],
        ],
    )
    assert {(row[0], row[1]): row[-1] for row in rows} == {
        ("A", midnight(date(2026, 8, 1))): 0,
        ("A", midnight(date(2026, 8, 2))): 1,
        ("B", midnight(date(2026, 8, 1))): 0,
    }
    empty = login_participation.LoginPopulation([], login_participation.LoginSelection(date_filters()))
    assert empty.rows("participation_rate", active_rows=[[2]]) == [[0]]


async def test_standalone_active_and_ratio_use_same_recent_dates_and_timezone(user_statistics, monkeypatch):
    active_queries = []

    async def search(service):
        active_queries.append(QueryBuilder(service.parameters).build_query_dsl())
        return [[midnight(login_participation.LoginSelection([]).end), 2]]

    monkeypatch.setattr(component.SearchEngineService, "search", search)
    for fields in (["active_user_count"], ["participation_rate"]):
        service = query(fields)
        service.data_config.time_filter = TimeFilter(type="recent_days", mode="dynamic", recentDays=7)
        service.data_config.dimensions = [DimensionField(fieldId="timestamp", timeGranularity="day")]
        await service.query_telemetry_data()
    assert active_queries[0] == active_queries[1]
    assert active_queries[0]["aggs"]["dimension_0"]["date_histogram"]["time_zone"] == "+08:00"


@pytest.mark.parametrize("b_logged_in, expected_active", [(False, 1), (True, 2)])
async def test_created_accounts_only_count_successful_period_logins(
    user_statistics, monkeypatch, b_logged_in, expected_active
):
    stamp = midnight(date(2026, 8, 1))
    rows = [
        {"user_id": 1, "user_name": "ceshiA", "metric_source": "increment", "timestamp": stamp},
        {"user_id": 2, "user_name": "ceshiB", "metric_source": "increment", "timestamp": stamp},
        {"user_id": 1, "metric_source": "participation", "logged_in": True, "timestamp": stamp},
        {"user_id": 1, "metric_source": "participation", "logged_in": True, "timestamp": stamp + 86_400_000},
        {"user_id": 2, "metric_source": "participation", "logged_in": b_logged_in, "timestamp": stamp},
        {"user_id": 2, "metric_source": "active_user", "timestamp": stamp},
        {"user_id": 2, "metric_source": "participation", "logged_in": True, "timestamp": midnight(date(2026, 9, 1))},
        {"user_id": 3, "metric_source": "participation", "logged_in": True, "timestamp": midnight(date(2026, 7, 31))},
        {
            "user_id": 4,
            "metric_source": "participation",
            "logged_in": True,
            "timestamp": stamp,
            "primary_department_name": "B",
        },
    ]
    for row in rows:
        row.setdefault("primary_department_name", "A")

    async def search(service):
        clauses = QueryBuilder(service.parameters).build_query_dsl()["query"]["bool"]["must"]
        selected = rows
        for clause in clauses:
            if "term" in clause:
                selected = [
                    row for row in selected if all(row.get(key) == value for key, value in clause["term"].items())
                ]
            elif "terms" in clause:
                selected = [
                    row for row in selected if all(row.get(key) in values for key, values in clause["terms"].items())
                ]
            elif "range" in clause:
                bounds = clause["range"]["timestamp"]
                selected = [
                    row
                    for row in selected
                    if (bounds.get("gte") is None or row["timestamp"] >= bounds["gte"])
                    and (bounds.get("lte") is None or row["timestamp"] <= bounds["lte"])
                    and (bounds.get("lt") is None or row["timestamp"] < bounds["lt"])
                ]
        return [[len({row["user_id"] for row in selected})]]

    monkeypatch.setattr(component.SearchEngineService, "search", search)
    result = await query(["new_user_count", "active_user_count"]).query_telemetry_data()
    assert result.value == [[2, expected_active]]
