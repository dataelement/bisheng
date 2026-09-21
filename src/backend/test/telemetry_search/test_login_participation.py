"""登录参与率按期间去重, 并回溯查询开始日期以前的登录人员。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.telemetry import LoginParticipationDataError, LoginParticipationFilterError
from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.models.dashboard_dataset import MetricConfig
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    FilterExpression,
    RangeOp,
    RangeValue,
    TermOp,
    TermsOp,
)
from bisheng.telemetry_search.domain.services import login_participation as module
from bisheng.telemetry_search.domain.services.dashboard_export_detail import _deduplicate_field, _metric_filter
from bisheng.telemetry_search.domain.services.login_participation import (
    LoginPopulation,
    LoginSelection,
    midnight,
    query_login_participation,
    read_login_records,
)


def record(user, day, **extra):
    return {
        "user_id": user,
        "timestamp": midnight(date.fromisoformat(day)) // 1000,
        "logged_in": True,
        "metric_source": "participation",
        **extra,
    }


def date_filters(start="2026-08-01", end="2026-09-21"):
    return [
        FilterExpression(
            bool_operator="must",
            filters=[
                RangeOp(
                    field="timestamp",
                    value=RangeValue(
                        gte=midnight(date.fromisoformat(start)),
                        lte=midnight(date.fromisoformat(end)) + 86_399_000,
                    ),
                )
            ],
        )
    ]


def time_dimension(granularity):
    return AggregationExpression(field="timestamp", type="date_histogram", time_interval=granularity)


RECORDS = [
    record(1, "2026-07-01"),
    record(2, "2026-07-02"),
    record(1, "2026-08-01"),
    record(1, "2026-08-01"),
    record(1, "2026-08-02"),
    record(3, "2026-09-21"),
    record(4, "2026-09-22"),
    record(5, "2026-08-01", logged_in=False),
    record(6, "2026-08-01", metric_source="active_user"),
]


@pytest.mark.parametrize(
    "granularity, expected",
    [
        (None, [(None, 2 / 3, 2)]),
        ("month", [("2026-08-01", 1 / 2, 1), ("2026-09-01", 1 / 3, 1)]),
        ("year", [("2026-01-01", 2 / 3, 2)]),
    ],
)
def test_period_deduplication_and_historical_denominator(granularity, expected):
    population = LoginPopulation([time_dimension(granularity)] if granularity else [], LoginSelection(date_filters()))
    for source in RECORDS:
        population.add(source)
    rates, counts = population.rows("participation_rate"), population.rows("logged_in_employee_count")
    assert [row[-1] for row in rates] == pytest.approx([value for _, value, _ in expected])
    assert [row[-1] for row in counts] == [count for _, _, count in expected]
    if granularity:
        assert [row[0] for row in rates] == [midnight(date.fromisoformat(day)) for day, _, _ in expected]


def test_daily_cumulative_population_zero_days_and_zero_denominator():
    population = LoginPopulation([time_dimension("day")], LoginSelection(date_filters()))
    for source in RECORDS:
        population.add(source)
    rates = dict(population.rows("participation_rate"))
    assert rates[midnight(date(2026, 8, 1))] == 0.5
    assert rates[midnight(date(2026, 8, 2))] == 0.5
    assert rates[midnight(date(2026, 8, 3))] == 0
    assert rates[midnight(date(2026, 9, 21))] == 1 / 3
    assert len(rates) == 52
    empty = LoginPopulation([], LoginSelection(date_filters()))
    assert empty.rows("participation_rate") == [[0.0]]


def test_china_week_boundary_and_department_group_population():
    dims = [AggregationExpression(field="primary_department_name", type="terms"), time_dimension("week")]
    population = LoginPopulation(dims, LoginSelection(date_filters("2026-08-02", "2026-08-03")))
    for user, day, dept in [
        (1, "2026-07-01", "一部"),
        (2, "2026-07-01", "一部"),
        (1, "2026-08-02", "一部"),
        (3, "2026-08-03", "一部"),
        (4, "2026-08-03", "二部"),
    ]:
        population.add(record(user, day, primary_department_name=dept))
    rows = {(row[0], row[1]): row[2] for row in population.rows("participation_rate")}
    assert rows["一部", midnight(date(2026, 7, 27))] == 0.5
    assert rows["一部", midnight(date(2026, 8, 3))] == 1 / 3
    assert rows["二部", midnight(date(2026, 8, 3))] == 1


def test_filters_preserve_organization_but_remove_history_lower_bound():
    filters = date_filters()
    organization = FilterExpression(
        bool_operator="should",
        filters=[
            TermOp(field="primary_department_id", value="1"),
            TermOp(field="primary_department_id", value="2"),
        ],
    )
    selection = LoginSelection([*filters, organization])
    history = selection.query(history=True)["bool"]["filter"]
    assert {"bool": organization.to_dsl()} in history
    assert {"term": {"metric_source": "participation"}} in history
    assert {"term": {"logged_in": True}} in history
    bounds = next(item["range"]["timestamp"] for item in history if "range" in item)
    assert bounds == {"lt": midnight(date(2026, 9, 22))}
    period_query = selection.query(history=False)["bool"]["filter"]
    assert next(item["range"]["timestamp"] for item in period_query if "range" in item)["gte"] == midnight(
        date(2026, 8, 1)
    )


def test_drilldown_month_and_nested_pairs():
    selection = LoginSelection(
        [FilterExpression(bool_operator="must", filters=[TermsOp(field="timestamp", value=["2026-08"])])]
    )
    assert selection.start == date(2026, 8, 1)
    assert selection.end == date(2026, 8, 31)
    source = {
        "user_department_infos": [
            {"department_id": 1, "department_name": "一部"},
            {"department_id": 2, "department_name": "二部"},
        ]
    }
    assert module.dimension_keys(
        source, ["user_department_infos.department_id", "user_department_infos.department_name"]
    ) == {
        (1, "一部"),
        (2, "二部"),
    }


def test_reject_ambiguous_time_or_and_hour_grain():
    with pytest.raises(LoginParticipationFilterError):
        LoginSelection(
            [
                FilterExpression(
                    bool_operator="should",
                    filters=[
                        TermsOp(field="local_date", value=["2026-08-01"]),
                        TermOp(field="user_id", value=1),
                    ],
                )
            ]
        )
    with pytest.raises(LoginParticipationFilterError):
        LoginPopulation([time_dimension("hour")], LoginSelection(date_filters()))


async def test_chart_entry_point_shares_snapshot_and_formats_china_month(monkeypatch):
    from bisheng.telemetry_search.domain.services import component as component_module

    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == "mid_user_increment")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(component_module, "get_async_db_session", Session)
    monkeypatch.setattr(
        component_module,
        "DashboardDatasetRepositoryImpl",
        lambda _: SimpleNamespace(
            find_one=AsyncMock(return_value=dataset),
        ),
    )
    scans = []

    async def records(index, query, fields):
        scans.append(query)
        for source in RECORDS:
            yield source

    monkeypatch.setattr(module, "read_login_records", records)
    service = component_module.DataQueryService(
        dataset_code="mid_user_increment",
        data_config=ComponentDataConfig(
            metrics=[{"fieldId": "participation_rate"}, {"fieldId": "logged_in_employee_count"}],
            dimensions=[{"fieldId": "timestamp", "timeGranularity": "month"}],
            timeFilter={
                "mode": "fixed",
                "startDate": midnight(date(2026, 8, 1)) // 1000,
                "endDate": midnight(date(2026, 9, 21)) // 1000 + 86399,
            },
        ),
    )
    result = await service.query_telemetry_data()
    assert result.dimensions == [["2026-08"], ["2026-09"]]
    assert result.value == [[0.5, 1], [1 / 3, 1]]
    assert len(scans) == 1


async def test_month_drilldown_exports_unique_login_users(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard_export_detail as detail

    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == "mid_user_increment")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(detail, "get_async_db_session", Session)
    monkeypatch.setattr(
        detail,
        "DashboardDatasetRepositoryImpl",
        lambda _: SimpleNamespace(
            find_one=AsyncMock(return_value=dataset),
        ),
    )
    monkeypatch.setattr(detail, "get_es_connection", AsyncMock())
    queries = []

    async def scan(*_args, **kwargs):
        queries.append(kwargs["query"]["query"])
        yield {"_source": record(1, "2026-08-01", user_name="张三")}
        yield {"_source": record(1, "2026-08-02", user_name="张三")}

    monkeypatch.setattr(detail, "async_scan", scan)
    result = await detail.query_detail_rows(
        dataset_code="mid_user_increment",
        data_config=ComponentDataConfig(
            metrics=[{"fieldId": "participation_rate"}],
            dimensions=[{"fieldId": "timestamp", "timeGranularity": "month"}],
        ),
        dimension_filters=[{"fieldId": "timestamp", "values": ["2026-08"]}],
        row_limit=100,
    )
    assert len(result.rows) == 1
    query_text = str(queries[0])
    assert "participation" in query_text and "logged_in" in query_text
    assert str(midnight(date(2026, 8, 1))) in query_text
    assert str(midnight(date(2026, 9, 1))) in query_text


async def test_query_keeps_history_and_applies_the_current_period(monkeypatch):
    calls = []

    async def records(index, query, fields):
        calls.append((index, query, fields))
        for source in RECORDS:
            yield source

    monkeypatch.setattr(module, "read_login_records", records)
    assert await query_login_participation(
        "participation_rate", index_name="users", dimensions=[], stack_dimension=None, filters=date_filters()
    ) == [[2 / 3]]
    assert calls[0][0] == "users"
    assert "gte" not in str(calls[0][1])


@pytest.mark.parametrize("failure", [None, "timeout", "shards", "incomplete", "cursor"])
async def test_pit_pagination_is_complete_and_always_closed(monkeypatch, failure):
    page = {
        "pit_id": "new-pit",
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {"sort": [1], "_source": RECORDS[0]},
            ],
        },
    }
    second = {"hits": {"hits": [{"sort": [2], "_source": RECORDS[1]}]}}
    if failure == "timeout":
        second["timed_out"] = True
    if failure == "shards":
        second["_shards"] = {"failed": 1}
    if failure == "incomplete":
        second["hits"]["hits"] = []
    if failure == "cursor":
        second["hits"]["hits"][0]["sort"] = [1]
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.side_effect = [page, second, {"hits": {"hits": []}}]
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=client))
    if failure:
        with pytest.raises(LoginParticipationDataError):
            [row async for row in read_login_records("users", {}, {"user_id"})]
    else:
        rows = [row async for row in read_login_records("users", {}, {"user_id"})]
        assert len(rows) == 2
        assert client.search.call_args_list[1].kwargs["body"]["search_after"] == [1]
    client.close_point_in_time.assert_awaited_once_with(body={"id": "new-pit"})


@pytest.mark.parametrize("code", ["mid_user_increment", "mid_user_daily_participation"])
def test_participation_configuration_uses_cumulative_login_population(code):
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == code)
    metrics = {item["field"]: MetricConfig(**item) for item in dataset.schema_config["metrics"]}
    for field in ("participation_rate", "logged_in_employee_count"):
        metric = metrics[field]
        assert metric.calculation == "login_participation"
        assert metric.formula is None
        assert _metric_filter(metric).to_dsl() == {
            "must": [
                {"term": {"metric_source": "participation"}},
                {"term": {"logged_in": True}},
            ]
        }
        assert _deduplicate_field(ComponentDataConfig(), metric) == "user_id"
    assert metrics["active_employee_count"].calculation is None
    assert metrics["login_count"].is_virtual is False
