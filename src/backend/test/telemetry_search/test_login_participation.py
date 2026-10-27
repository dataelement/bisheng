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
    record(2, "2026-07-02", active_employee=0),
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
        (None, [(None, 2 / 3, 3, 3, 2)]),
        ("month", [("2026-08-01", 1 / 2, 2, 2, 1), ("2026-09-01", 1 / 3, 1, 3, 1)]),
        ("year", [("2026-01-01", 2 / 3, 3, 3, 2)]),
    ],
)
def test_period_deduplication_and_historical_denominator(granularity, expected):
    population = LoginPopulation([time_dimension(granularity)] if granularity else [], LoginSelection(date_filters()))
    for source in RECORDS:
        population.add(source)
    counts = population.rows("logged_in_employee_count")
    rates = population.rows("participation_rate", active_rows=[
        [*row[:-1], active] for row, (_, _, _, _, active) in zip(counts, expected, strict=True)
    ])
    assert [row[-1] for row in rates] == pytest.approx([value for _, value, _, _, _ in expected])
    assert [row[-1] for row in counts] == [count for _, _, count, _, _ in expected]
    assert [row[-1] for row in population.rows("active_employee_count")] == [total for _, _, _, total, _ in expected]
    if granularity:
        assert [row[0] for row in rates] == [midnight(date.fromisoformat(day)) for day, _, _, _, _ in expected]


@pytest.mark.parametrize("granularity, expected", [(None, [5]), ("day", [1, 1, 1, 1, 1, 0, 0]), ("week", [2, 3])])
def test_cumulative_logins_count_user_days_within_selected_week(granularity, expected):
    population = LoginPopulation(
        [time_dimension(granularity)] if granularity else [],
        LoginSelection(date_filters("2026-08-01", "2026-08-07")),
    )
    for day in range(1, 6):
        for _ in range(5):
            population.add(record(1, f"2026-08-{day:02d}", login_count=5))
    population.add(record(1, "2026-07-31"))
    population.add(record(1, "2026-08-08"))
    population.add(record(2, "2026-08-01", logged_in=False))
    population.add(record(3, "2026-08-01", metric_source="active_user"))
    assert [row[-1] for row in population.rows("logged_in_employee_count")] == expected


def test_cumulative_logins_use_only_selected_non_contiguous_china_days():
    population = LoginPopulation([], LoginSelection([
        FilterExpression(bool_operator="must", filters=[TermsOp(
            field="local_date", value=["2026-08-01", "2026-08-03"],
        )]),
    ]))
    population.add(record(1, "2026-08-01"))
    population.add(record(1, "2026-08-02"))
    population.add(record(1, "2026-08-02", timestamp=midnight(date(2026, 8, 2)) // 1000 - 1))
    population.add(record(1, "2026-08-03"))
    population.add(record(2, "2026-08-03"))
    assert population.rows("logged_in_employee_count") == [[3]]


def test_daily_cumulative_population_zero_days_and_zero_denominator():
    population = LoginPopulation([time_dimension("day")], LoginSelection(date_filters()))
    for source in RECORDS:
        population.add(source)
    rates = dict(population.rows("participation_rate", active_rows=population.rows("logged_in_employee_count")))
    assert rates[midnight(date(2026, 8, 1))] == 0.5
    assert rates[midnight(date(2026, 8, 2))] == 0.5
    assert rates[midnight(date(2026, 8, 3))] == 0
    assert rates[midnight(date(2026, 9, 21))] == 1 / 3
    assert len(rates) == 52
    effective = dict(population.rows("active_employee_count"))
    assert effective[midnight(date(2026, 8, 3))] == 2
    assert effective[midnight(date(2026, 9, 21))] == 3
    empty = LoginPopulation([], LoginSelection(date_filters()))
    assert empty.rows("participation_rate", active_rows=[]) == [[0.0]]
    assert empty.rows("active_employee_count") == [[0]]


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
    rows = {(row[0], row[1]): row[2] for row in population.rows(
        "participation_rate", active_rows=population.rows("logged_in_employee_count"),
    )}
    assert rows["一部", midnight(date(2026, 7, 27))] == 0.5
    assert rows["一部", midnight(date(2026, 8, 3))] == 1 / 3
    assert rows["二部", midnight(date(2026, 8, 3))] == 1
    effective = {(row[0], row[1]): row[2] for row in population.rows("active_employee_count")}
    assert effective["一部", midnight(date(2026, 7, 27))] == 2
    assert effective["一部", midnight(date(2026, 8, 3))] == 3
    assert effective["二部", midnight(date(2026, 8, 3))] == 1


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
    monkeypatch.setattr(component_module, "query_active_users", AsyncMock(return_value=[
        [midnight(date(2026, 8, 1)), 2], [midnight(date(2026, 9, 1)), 1],
    ]))
    service = component_module.DataQueryService(
        dataset_code="mid_user_increment",
        data_config=ComponentDataConfig(
            metrics=[
                {"fieldId": "participation_rate"}, {"fieldId": "logged_in_employee_count"},
                {"fieldId": "active_employee_count"},
            ],
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
    assert result.value == [[1.0, 2, 2], [1 / 3, 1, 3]]
    assert len(scans) == 1


@pytest.mark.parametrize("field, history", [
    ("participation_rate", False), ("active_user_count", False),
    ("logged_in_employee_count", False), ("active_employee_count", True),
])
@pytest.mark.parametrize("dataset_code", ["mid_user_increment", "mid_user_daily_participation"])
async def test_month_drilldown_exports_unique_login_users(monkeypatch, field, history, dataset_code):
    from bisheng.telemetry_search.domain.services import dashboard_export_detail as detail

    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == dataset_code)

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
        yield {"_source": record(
            1, "2026-08-01", user_name="张三", login_count=5,
            timestamp=midnight(date(2026, 8, 1)) + 60_000, local_date="2026-07-31",
        )}
        yield {"_source": record(1, "2026-08-02", user_name="张三")}
        if history:
            yield {"_source": record(2, "2026-07-02", user_name="李四")}
        if "logged_in" not in str(queries[-1]):
            yield {"_source": record(3, "2026-08-01", user_name="王五", logged_in=False, metric_source="active_user")}

    monkeypatch.setattr(detail, "async_scan", scan)
    result = await detail.query_detail_rows(
        dataset_code=dataset_code,
        data_config=ComponentDataConfig(
            metrics=[{"fieldId": field}],
            dimensions=[{"fieldId": "timestamp", "timeGranularity": "month"}],
        ),
        dimension_filters=[{"fieldId": "timestamp", "values": ["2026-08"]}],
        row_limit=100,
    )
    assert len(result.rows) == (2 if history or field == "logged_in_employee_count" else 1)
    if field == "logged_in_employee_count":
        assert {row["local_date"] for row in result.rows} == {"2026-08-01", "2026-08-02"}
        assert "local_date" in {column.field for column in result.columns}
    query_text = str(queries[0])
    bounds = next(item["range"]["timestamp"] for item in queries[0]["bool"]["filter"] if "range" in item)
    assert ("gte" not in bounds) is history
    assert "participation" in query_text and "logged_in" in query_text
    if not history:
        assert str(midnight(date(2026, 8, 1))) in query_text
    assert str(midnight(date(2026, 9, 1))) in query_text


async def test_query_keeps_history_and_applies_the_current_period(monkeypatch):
    calls = []

    async def records(index, query, fields):
        calls.append((index, query, fields))
        for source in RECORDS:
            yield source

    monkeypatch.setattr(module, "read_login_records", records)
    monkeypatch.setattr(module, "query_active_users", AsyncMock(return_value=[[2]]))
    assert await query_login_participation(
        "participation_rate", index_name="users", dimensions=[], stack_dimension=None, filters=date_filters()
    ) == [[2 / 3]]
    assert calls[0][0] == "users"
    assert "gte" not in str(calls[0][1])


@pytest.mark.parametrize(
    "failure",
    [None, "timeout", "shards", "terminated", "missing_cursor", "cursor", "backward", "grow", "shrink"],
)
async def test_index_pagination_without_pit_checks_errors_and_accepts_refresh_changes(monkeypatch, failure):
    page = {
        "hits": {
            "total": {"value": 1 if failure == "grow" else 3 if failure == "shrink" else 2, "relation": "eq"},
            "hits": [
                {"sort": [1, 1, "1"], "_source": RECORDS[0]},
            ],
        },
    }
    second = {"hits": {"hits": [{"sort": [1, 1, "2"], "_source": RECORDS[1]}]}}
    if failure == "timeout":
        second["timed_out"] = True
    if failure == "shards":
        second["_shards"] = {"failed": 1}
    if failure == "terminated":
        second["terminated_early"] = True
    if failure == "missing_cursor":
        second["hits"]["hits"][0].pop("sort")
    if failure == "cursor":
        second["hits"]["hits"][0]["sort"] = [1, 1, "1"]
    if failure == "backward":
        second["hits"]["hits"][0]["sort"] = [0, 1, "2"]
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit"}
    client.search.side_effect = [page, second, {"hits": {"hits": []}}]
    monkeypatch.setattr(module, "get_es_connection", AsyncMock(return_value=client))
    if failure not in {None, "grow", "shrink"}:
        with pytest.raises(LoginParticipationDataError):
            [row async for row in read_login_records("users", {}, {"user_id"})]
    else:
        rows = [row async for row in read_login_records("users", {}, {"user_id"})]
        assert len(rows) == 2
        assert client.search.call_args_list[1].kwargs["body"]["search_after"] == [1, 1, "1"]
    for call in client.search.await_args_list:
        assert call.kwargs["index"] == "users"
        assert call.kwargs["allow_partial_search_results"] is False
        assert "pit" not in call.kwargs["body"]
        assert call.kwargs["body"]["sort"] == [{"timestamp": "asc"}, {"tenant_id": "asc"}, {"user_id": "asc"}]
        assert call.kwargs["body"]["track_total_hits"] is False
    client.open_point_in_time.assert_not_awaited()
    client.close_point_in_time.assert_not_awaited()


@pytest.mark.parametrize("code", ["mid_user_increment", "mid_user_daily_participation"])
def test_participation_configuration_uses_cumulative_login_population(code):
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == code)
    metrics = {item["field"]: MetricConfig(**item) for item in dataset.schema_config["metrics"]}
    for field in ("logged_in_employee_count", "active_employee_count"):
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
    assert metrics["participation_rate"].calculation == "login_participation"
    assert _metric_filter(metrics["participation_rate"]) is None
    assert metrics["active_employee_count"].name == "全员有效用户数"
    assert metrics["login_count"].is_virtual is False
