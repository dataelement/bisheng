# ruff: noqa: RUF002, RUF003
"""验证累计分母、首末时间、真实数据库边界及 ES 完整分页契约。"""

import csv
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, event
from sqlmodel import Session

from scripts.export_user_daily_activity import (
    CHINA,
    Activity,
    ActivityRepository,
    collect_es,
    composite_pages,
    create_dashboard_client,
    create_telemetry_client,
    dashboard_total_users,
    midnight,
    print_summary,
    write_report,
)


def ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=CHINA).timestamp()


def user_metric():
    return {
        "field": "total_user_count",
        "name": "总用户数",
        "is_virtual": True,
        "sum_field": "user_id",
        "sum_type": "cardinality",
    }


def test_dashboard_dataset_configuration_uses_saved_index_and_metric():
    from sqlalchemy import JSON

    engine = create_engine("sqlite://")
    metadata = MetaData()
    dataset = Table(
        "dashboard_dataset",
        metadata,
        Column("dataset_code", String),
        Column("es_index_name", String),
        Column("schema_config", JSON),
    )
    metadata.create_all(engine)
    metric = user_metric()
    metric["filter"] = {
        "bool_operator": "must",
        "filters": [{"operator": "term", "field": "metric_source", "value": "increment"}],
    }
    try:
        with Session(engine) as session:
            repository = ActivityRepository(session, CHINA)
            with pytest.raises(ValueError, match="未找到看板"):
                repository.dashboard_user_metric()
            session.execute(
                dataset.insert(),
                {
                    "dataset_code": "mid_user_increment",
                    "es_index_name": "custom_user_alias",
                    "schema_config": {"metrics": [metric], "dimensions": []},
                },
            )
            index, config = repository.dashboard_user_metric()
            assert index == "custom_user_alias"
            assert config["sum_field"] == "user_id" and config["filter"] == metric["filter"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("tenant_id", [None, 7])
async def test_dashboard_count_matches_dashboard_metric_query(tenant_id, monkeypatch):
    from bisheng.telemetry_search.domain.models.dashboard_dataset import MetricConfig
    from bisheng.telemetry_search.domain.schemas.component import AggregationType, ComponentDataConfig
    from bisheng.telemetry_search.domain.services.component import DataQueryService
    from bisheng.telemetry_search.domain.services.search_engine_service import SearchEngineService

    queries = []

    async def search(service):
        queries.append(service.build_search_query())
        return [[123]]

    monkeypatch.setattr(SearchEngineService, "search", search)
    config = user_metric()
    config["filter"] = {
        "bool_operator": "must",
        "filters": [{"operator": "term", "field": "metric_source", "value": "increment"}],
    }
    service = DataQueryService(dataset_code="mid_user_increment", data_config=ComponentDataConfig())
    result = await service.query_one_metric(
        MetricConfig(**config),
        AggregationType.SUM,
        -1,
        index_name="custom_user_alias",
        dimensions=[],
        stack_dimension=None,
        filters=None,
    )
    assert result == [[123]]
    captured = []
    client = SimpleNamespace(
        indices=SimpleNamespace(exists=lambda **kwargs: True),
        search=lambda **kwargs: captured.append(kwargs) or {"aggregations": {"metric_0": {"value": 123}}},
    )
    assert (
        dashboard_total_users(client, "custom_user_alias", config, ts("2026-08-04 12:00"), tenant_id, verbose=False)
        == 123
    )
    request = captured[0]
    assert request["index"] == "custom_user_alias" and request["allow_partial_search_results"] is False
    assert request["body"]["aggs"] == queries[0]["aggs"] == {"metric_0": {"cardinality": {"field": "user_id"}}}
    assert request["body"]["query"]["bool"]["filter"] == [
        queries[0]["query"],
        {"range": {"timestamp": {"lt": str(ts("2026-08-04 12:00")), "format": "epoch_second"}}},
        *([{"term": {"tenant_id": tenant_id}}] if tenant_id else []),
    ]


@pytest.mark.parametrize("failure", ["missing", "timeout", "shard", "terminated", "metric", "invalid"])
def test_dashboard_count_failure_is_not_zero(failure):
    config = user_metric()
    if failure == "metric":
        config["sum_type"] = "value_count"
    client = SimpleNamespace(
        indices=SimpleNamespace(exists=lambda **kwargs: failure != "missing"),
        search=lambda **kwargs: {
            "timed_out": failure == "timeout",
            "terminated_early": failure == "terminated",
            "_shards": {"failed": int(failure == "shard")},
            "aggregations": {"metric_0": {"value": -1 if failure == "invalid" else 0}},
        },
    )
    with pytest.raises(ValueError):
        dashboard_total_users(client, "test", config, ts("2026-08-04 12:00"), None, verbose=False)


def test_operation_span_uses_all_sources_even_without_login():
    activity = Activity(date(2026, 8, 1), date(2026, 8, 2), ts("2026-08-03 00:00"))
    # ES 已聚合的首末时间与数据库单条记录混合且乱序到达。
    activity.record(7, ts("2026-08-01 14:00"), ts("2026-08-01 14:20"), "es:portal_search", login=False, count=2)
    activity.record(7, ts("2026-08-01 09:10"), ts("2026-08-01 09:10"), "chat_message", login=False)
    activity.record(7, ts("2026-08-01 09:00"), ts("2026-08-01 09:00"), "audit:upload_file", login=False)
    activity.record(7, ts("2026-08-01 09:00"), ts("2026-08-01 09:00"), "es:new_knowledge_file", login=False)
    activity.record(7, ts("2026-08-02 00:00"), ts("2026-08-02 00:00"), "qa_answer", login=False)
    item = activity.days[date(2026, 8, 1), 7]
    assert item.first_operation == ts("2026-08-01 09:00")
    assert item.operation_seconds == 320 * 60
    assert activity.days[date(2026, 8, 2), 7].operation_seconds == 0
    assert activity.reports() == [
        ["2026-08-01", 1, 1, "100.00%", 320.0],
        ["2026-08-02", 1, 1, "100.00%", 0.0],
    ]


def test_monthly_distinct_users_and_partial_months():
    activity = Activity(
        date(2026, 7, 20),
        date(2026, 9, 21),
        ts("2026-09-21 12:00"),
        snapshot_cutoff=ts("2026-10-02 00:00"),
    )
    activity.historical_operation(99, ts("2026-10-01 10:00"))
    activity.historical_operation(98, ts("2026-06-01 10:00"))
    for user, stamp, source in [
        (1, "2026-08-01 10:00", "chat_message"),
        (1, "2026-08-02 10:00", "qa_question"),
        (1, "2026-08-02 10:00", "es:portal_qa"),
        (2, "2026-08-31 23:59", "es:portal_document_read"),
        (1, "2026-09-01 00:00", "es:portal_search"),
        (3, "2026-09-21 11:59", "qa_answer"),
    ]:
        activity.record(user, ts(stamp), ts(stamp), source)
    activity.record(8, ts("2026-07-21 10:00"), ts("2026-07-21 10:00"), "audit:user_login", login=True)
    assert activity.monthly_reports() == [
        ["2026-07", "2026-07-20 00:00:00+08:00", "2026-08-01 00:00:00+08:00", 0],
        ["2026-08", "2026-08-01 00:00:00+08:00", "2026-09-01 00:00:00+08:00", 2],
        ["2026-09", "2026-09-01 00:00:00+08:00", "2026-09-21 12:00:00+08:00", 2],
    ]


def test_daily_business_results_and_export(tmp_path):
    activity = Activity(date(2026, 8, 1), date(2026, 8, 3), ts("2026-08-03 12:00"))
    activity.historical_operation(1, ts("2026-07-01 08:00"))
    activity.historical_operation(2, ts("2026-07-02 08:00"))
    activity.historical_operation(5, ts("2026-08-04 08:00"))
    for user, stamp, source, login in [
        (1, "2026-08-01 09:00", "audit:user_login", True),
        (1, "2026-08-01 09:00", "es:user_login", True),
        (1, "2026-08-01 18:00", "audit:user_login", True),
        (1, "2026-08-01 10:00", "es:portal_document_read", False),
        (1, "2026-08-01 11:00", "chat_message", False),
        (3, "2026-08-01 08:00", "audit:user_login", True),
        (3, "2026-08-01 19:00", "es:user_login", True),
        (4, "2026-08-01 23:59", "qa_answer", False),
        (4, "2026-08-02 00:00", "audit:user_login", True),
        (4, "2026-08-02 00:01", "es:portal_search", False),
    ]:
        activity.record(user, ts(stamp), ts(stamp), source, login=login)
    summaries = activity.reports()
    assert summaries == [
        ["2026-08-01", 2, 3, "66.67%", 30.0],
        ["2026-08-02", 1, 3, "33.33%", 0.0],
        ["2026-08-03", 0, 3, "0.00%", 0.0],
    ]
    assert set(activity.history) == {1, 2, 4}
    # 日活与平均分母都是两位有操作的用户，只有登录的用户不计入任何指标。
    assert activity.daily_totals()[date(2026, 8, 1)]["operation_users"] == 2
    target = tmp_path / "report"
    write_report(target, activity, 20)
    assert {path.name for path in target.iterdir()} == {
        "每日用户活跃统计.csv",
        "平台用户汇总.csv",
        "每月用户活跃统计.csv",
    }
    with (target / "每日用户活跃统计.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["日期", "日活数量", "截至当日累计有效操作人数", "日活比例", "每日用户平均使用时间(分钟)"]
    assert rows[1] == ["2026-08-01", "2", "3", "66.67%", "30.0"]
    assert len(rows) == 4
    before = (target / "每日用户活跃统计.csv").read_bytes()
    with pytest.raises(FileExistsError):
        write_report(target, activity, 20)
    assert (target / "每日用户活跃统计.csv").read_bytes() == before


@pytest.mark.parametrize(
    "start,end,cutoff,expected",
    [
        (
            date(2025, 12, 31),
            date(2026, 1, 1),
            "2026-01-02 00:00",
            [
                ["2025-12", "2025-12-31 00:00:00+08:00", "2026-01-01 00:00:00+08:00", 0],
                ["2026-01", "2026-01-01 00:00:00+08:00", "2026-01-02 00:00:00+08:00", 0],
            ],
        ),
        (
            date(2024, 2, 29),
            date(2024, 3, 1),
            "2024-03-02 00:00",
            [
                ["2024-02", "2024-02-29 00:00:00+08:00", "2024-03-01 00:00:00+08:00", 0],
                ["2024-03", "2024-03-01 00:00:00+08:00", "2024-03-02 00:00:00+08:00", 0],
            ],
        ),
    ],
)
def test_monthly_calendar_boundaries(start, end, cutoff, expected):
    assert Activity(start, end, ts(cutoff)).monthly_reports() == expected


def test_database_sources_real_queries_and_scope():
    from bisheng.core.context.tenant import (
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
        strict_tenant_filter,
    )
    from bisheng.core.database import tenant_filter

    repository = ActivityRepository(None, ZoneInfo("UTC"))
    engine = create_engine("sqlite://")
    metadata = MetaData()
    # 使用精简表隔离生产 DDL 方言差异；实际查询和租户钩子均来自项目代码。
    audit = Table(
        repository.Audit.__tablename__,
        metadata,
        Column("operator_id", Integer),
        Column("tenant_id", Integer),
        Column("create_time", DateTime),
        Column("event_type", String),
        Column("action", String),
    )
    source_tables = []
    for model, time_column, name, zone, _ in repository.sources:
        columns = [Column("user_id", Integer), Column("tenant_id", Integer), Column(time_column.key, DateTime)]
        if name == "chat_message":
            columns.append(Column("is_bot", Boolean))
        source_tables.append((Table(model.__tablename__, metadata, *columns), time_column.key, name, zone))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            audit.insert(),
            [
                {
                    "operator_id": uid,
                    "tenant_id": tid,
                    "create_time": datetime.fromisoformat(stamp),
                    "event_type": kind,
                    "action": action,
                }
                for uid, tid, stamp, kind, action in [
                    (1, 1, "2026-07-01 00:00", "user_login", None),
                    (6, 1, "2026-07-03 00:00", None, "approval.task.approve"),
                    (7, 1, "2026-07-03 00:00", None, "approval.handler.success"),
                    (8, 1, "2026-07-03 00:00", "user_login", "approval.task.approve"),
                    (1, 1, "2026-08-01 01:00", "user_login", None),  # 北京09:00
                    (1, 1, "2026-08-01 01:30", "upload_file", None),
                    (1, 1, "2026-08-01 06:00", None, "approval.task.approve"),
                    (1, 1, "2026-08-01 15:00", None, "approval.handler.success"),  # 后台事件排除
                    (2, 2, "2026-08-01 01:00", "user_login", None),
                    (3, None, "2026-08-01 01:00", "upload_file", None),
                    (4, 1, "2026-08-03 01:00", "upload_file", None),  # 北京次日，排除
                    (0, 1, "2026-08-01 01:00", "upload_file", None),
                ]
            ],
        )
        for index, (table, time_key, name, zone) in enumerate(source_tables):
            hour = 13 if zone == CHINA else 5  # 统一北京时间13:00
            row = {"user_id": 1, "tenant_id": 1, time_key: datetime(2026, 8, 1, hour)}
            if name == "chat_message":
                row["is_bot"] = False
            connection.execute(table.insert(), [row, {**row, "user_id": 2, "tenant_id": 2}])
            connection.execute(table.insert(), {**row, "user_id": 10 + index, time_key: datetime(2026, 7, 2, hour)})
            if name == "chat_message":
                connection.execute(
                    table.insert(), {**row, "user_id": 30, "is_bot": True, time_key: datetime(2026, 7, 2, hour)}
                )
                connection.execute(table.insert(), {**row, "is_bot": True, time_key: datetime(2026, 8, 1, 15)})
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables = tenant_filter._discover_tenant_aware_tables()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt))
    token = set_current_tenant_id(1)
    try:
        for context, expected in [
            (strict_tenant_filter(), {1, 4, 6, 10, 11, 12, 13, 14}),
            (bypass_tenant_filter(), {1, 2, 3, 4, 6, 10, 11, 12, 13, 14}),
        ]:
            activity = Activity(
                date(2026, 8, 1), date(2026, 8, 1), ts("2026-08-02 00:00"), snapshot_cutoff=ts("2026-08-04 12:00")
            )
            with context, Session(engine) as session:
                repository.session = session
                repository.collect(activity, verbose=False)
            assert set(activity.history) == expected
            item = activity.days[date(2026, 8, 1), 1]
            assert item.first_operation == ts("2026-08-01 09:30")
            assert activity.history[1] == ts("2026-08-01 09:30")
            assert activity.history[6] == ts("2026-07-03 08:00")
            assert all(activity.history[user] == ts("2026-07-02 13:00") for user in range(10, 15))
            assert activity.reports()[0][1:4] == ([1, 7, "14.29%"] if len(expected) == 8 else [3, 9, "33.33%"])
            assert item.last_operation == ts("2026-08-01 14:00")
            assert item.last_sources == {"audit:approval.task.approve"}
            assert {name for _, name in activity.sources} >= {
                "chat_message",
                "qa_question",
                "qa_answer",
                "qa_comment",
                "article_read",
            }
    finally:
        current_tenant_id.reset(token)
        engine.dispose()
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


class FakeES:
    """按实际请求条件聚合原始事件，限制每页两组以覆盖精确分页。"""

    def __init__(self, events):
        self.events = events
        self.indices = SimpleNamespace(exists=lambda **kwargs: True)
        self.requests = []

    def search(self, *, index, body, allow_partial_search_results):
        assert allow_partial_search_results is False
        self.requests.append(body)
        events = self.events
        for condition in body["query"]["bool"]["filter"]:
            operator, content = next(iter(condition.items()))
            key, value = next(iter(content.items()))
            if operator == "term":
                events = [record for record in events if record.get(key) == value]
            elif operator == "terms":
                events = [record for record in events if record.get(key) in value]
            else:
                assert operator == "range"
                if key == "timestamp":
                    assert value["format"] == "epoch_second"
                for comparison, bound in value.items():
                    if comparison == "format":
                        continue
                    bound = float(bound)
                    if comparison == "lt":
                        events = [record for record in events if record[key] < bound]
                    elif comparison == "gte":
                        events = [record for record in events if record[key] >= bound]
                    else:
                        assert comparison == "gt"
                        events = [record for record in events if record[key] > bound]
        composite = body["aggs"]["records"]["composite"]
        names = [next(iter(source)) for source in composite["sources"]]
        groups = {}
        for record in events:
            values = {"user": record["user_context.user_id"], "event": record["event_type"]}
            if "day" in names:
                histogram = composite["sources"][0]["day"]["date_histogram"]
                assert histogram["calendar_interval"] == "1d" and histogram["time_zone"] == "+08:00"
                values["day"] = midnight(datetime.fromtimestamp(record["timestamp"], CHINA).date()).timestamp() * 1000
            key = tuple(values[name] for name in names)
            groups.setdefault(key, []).append(record["timestamp"])
        keys = sorted(groups)
        if "after" in composite:
            cursor = tuple(composite["after"][name] for name in names)
            keys = [key for key in keys if key > cursor]
        keys = keys[:2]
        buckets = [
            {
                "key": dict(zip(names, key, strict=True)),
                "doc_count": len(groups[key]),
                "first": {"value": min(groups[key]) * 1000},
                "last": {"value": max(groups[key]) * 1000},
            }
            for key in keys
        ]
        result = {"buckets": buckets}
        if buckets:
            result["after_key"] = buckets[-1]["key"]
        return {"timed_out": False, "_shards": {"failed": 0}, "aggregations": {"records": result}}


@pytest.mark.parametrize("tenant_id,expected_users", [(1, {1, 2, 3, 6}), (None, {1, 2, 3, 4, 5, 6})])
def test_es_source_filter_pagination_and_midnight(tenant_id, expected_users, capsys):
    client = FakeES(
        [
            {"user_context.user_id": user, "tenant_id": tenant, "event_type": event, "timestamp": ts(stamp)}
            for user, tenant, event, stamp in [
                (1, 1, "user_login", "2026-07-01 08:00"),
                (1, 1, "portal_search", "2026-07-02 08:00"),
                (2, 1, "portal_document_read", "2026-07-02 08:00"),
                (8, 1, "user_login", "2026-07-02 08:00"),
                (9, 1, "model_invoke", "2026-07-02 08:00"),
                (3, 1, "user_login", "2026-08-01 09:00"),
                (3, 1, "user_login", "2026-08-01 11:00"),
                (3, 1, "portal_search", "2026-08-01 12:00"),
                (3, 1, "portal_document_download", "2026-08-01 13:00"),
                (3, 1, "model_invoke", "2026-08-01 22:00"),
                (3, 1, "application_alive", "2026-08-01 23:00"),
                (3, 1, "portal_document_read", "2026-08-02 00:00"),
                (6, 1, "portal_search", "2026-08-02 00:00"),
                (7, 1, "portal_search", "2026-08-02 12:00"),
                (4, 2, "portal_search", "2026-08-01 09:00"),
                (5, None, "portal_search", "2026-08-01 09:00"),
                (0, 1, "portal_search", "2026-08-01 09:00"),
            ]
        ]
    )
    activity = Activity(date(2026, 8, 1), date(2026, 8, 2), ts("2026-08-02 12:00"))
    collect_es(client, "base_telemetry_events", activity, tenant_id, verbose=True)
    assert set(activity.history) == expected_users
    assert activity.days[date(2026, 8, 1), 3].last_operation == ts("2026-08-01 13:00")
    summary = activity.reports()
    assert activity.history[1] == ts("2026-07-02 08:00")
    assert summary == (
        [
            ["2026-08-01", 1, 3, "33.33%", 60.0],
            ["2026-08-02", 2, 4, "50.00%", 0.0],
        ]
        if tenant_id
        else [
            ["2026-08-01", 3, 5, "60.00%", 20.0],
            ["2026-08-02", 2, 6, "33.33%", 0.0],
        ]
    )
    assert len(client.requests) >= 5
    output = capsys.readouterr().err
    assert "ES 请求" in output and "ES 响应" in output


@pytest.mark.parametrize("failure", ["missing", "timeout", "shard", "terminated", "exception"])
def test_es_failure_never_becomes_zero_report(failure, capsys):
    client = FakeES([])
    if failure == "missing":
        client.indices.exists = lambda **kwargs: False
    else:

        def broken_search(**kwargs):
            if failure == "exception":
                raise ConnectionError("test")
            return {
                "timed_out": failure == "timeout",
                "terminated_early": failure == "terminated",
                "_shards": {"failed": 1 if failure == "shard" else 0},
            }

        client.search = broken_search
    activity = Activity(date(2026, 8, 1), date(2026, 8, 1), ts("2026-08-02 00:00"))
    with pytest.raises((ValueError, ConnectionError)):
        collect_es(client, "test", activity, None, verbose=True)
    assert "ES 响应" not in capsys.readouterr().err


def test_empty_days_and_fixed_end_date():
    activity = Activity(date(2026, 8, 1), date(2026, 9, 21), ts("2026-09-22 00:00"))
    summaries = activity.reports()
    assert len(summaries) == 52
    assert summaries[-1] == ["2026-09-21", 0, 0, "0.00%", 0.0]


@pytest.mark.parametrize("failed_file", [1, 2, 3])
def test_failed_write_never_publishes_partial_csv(tmp_path, monkeypatch, failed_file):
    activity = Activity(date(2026, 8, 1), date(2026, 8, 1), ts("2026-08-02 00:00"))
    calls = 0
    original_writer = csv.writer

    class BrokenWriter:
        def writerow(self, row):
            return None

        def writerows(self, rows):
            raise OSError("模拟磁盘写入失败")

    def writer(stream):
        nonlocal calls
        calls += 1
        return BrokenWriter() if calls == failed_file else original_writer(stream)

    monkeypatch.setattr(csv, "writer", writer)
    target = tmp_path / "report"
    with pytest.raises(OSError, match="写入失败"):
        write_report(target, activity, 20)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_operation_scope_and_partial_day_are_explained(tmp_path, capsys):
    activity = Activity(date(2026, 8, 1), date(2026, 8, 1), ts("2026-08-01 12:00"))
    activity.record(7, ts("2026-08-01 09:00"), ts("2026-08-01 10:00"), "es:portal_search", login=False)
    print_summary(activity, tmp_path / "report.csv", verbose=False)
    output = capsys.readouterr().out
    assert "数据不足" not in output
    assert "可追溯历史累计操作用户" in output and "部分数据" in output and "有操作人数平均" in output


def test_stuck_cursor_rejected():
    client = SimpleNamespace(
        search=lambda **kwargs: {
            "aggregations": {"records": {"buckets": [{"key": {"user": 1}}], "after_key": {"user": 1}}}
        }
    )
    with pytest.raises(ValueError, match="游标"):
        list(composite_pages(client, "test", [], [], verbose=False, label="test"))


@pytest.mark.parametrize("factory,port", [(create_telemetry_client, 19200), (create_dashboard_client, 19201)])
def test_uses_separate_es_configurations_without_initializing_index(factory, port):
    settings = SimpleNamespace(
        get_telemetry_conf=lambda: SimpleNamespace(elasticsearch_url="http://127.0.0.1:19200", ssl_verify={}),
        get_search_conf=lambda: SimpleNamespace(elasticsearch_url="http://127.0.0.1:19201", ssl_verify={}),
    )
    client = factory(settings)
    try:
        nodes = client.transport.node_pool.all()
        assert nodes[0].config.port == port
    finally:
        client.close()


@pytest.mark.parametrize("es_available,dashboard_available", [(True, True), (False, True), (True, False)])
def test_cli_collect_merge_export_and_failure_cleanup(tmp_path, monkeypatch, es_available, dashboard_available):
    from bisheng.core import database
    from bisheng.core.context.tenant import (
        current_tenant_id,
        get_current_tenant_id,
        is_tenant_filter_bypassed,
        set_current_tenant_id,
    )
    from bisheng.core.database import tenant_filter
    from scripts import export_user_daily_activity as script

    state = {"rollback": False, "closed": False, "dashboard_closed": False}

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 4, 12, tzinfo=CHINA)

    monkeypatch.setattr(script, "datetime", FixedDateTime)

    class Repository:
        def __init__(self, session, zone):
            self.session = session

        def dashboard_user_metric(self):
            return "configured_user_index", user_metric()

        def collect(self, activity, *, verbose):
            assert is_tenant_filter_bypassed()
            activity.historical_operation(1, ts("2026-07-01 08:00"))
            activity.historical_operation(3, ts("2026-07-01 08:00"))
            for user, stamp, source, login in [
                (1, "2026-08-01 09:00", "audit:user_login", True),
                (1, "2026-08-01 09:10", "chat_message", False),
                (2, "2026-08-01 10:00", "qa_question", False),
            ]:
                activity.record(user, ts(stamp), ts(stamp), source, login=login)

    @contextmanager
    def session():
        yield SimpleNamespace(rollback=lambda: state.update(rollback=True))

    client = FakeES(
        [
            {"user_context.user_id": user, "tenant_id": 1, "event_type": kind, "timestamp": ts(stamp)}
            for user, stamp, kind in [
                (1, "2026-07-02 09:00", "portal_search"),
                (3, "2026-07-02 09:00", "portal_search"),
                (1, "2026-08-01 09:00", "user_login"),
                (1, "2026-08-01 11:00", "portal_document_read"),
                (2, "2026-08-01 10:20", "portal_search"),
                (1, "2026-08-02 00:00", "portal_search"),
                (4, "2026-08-03 08:00", "portal_search"),
                (1, "2026-08-03 11:00", "portal_search"),
                (5, "2026-08-04 12:00", "portal_search"),
            ]
        ]
    )
    client.indices.exists = lambda **kwargs: es_available
    client.close = lambda: state.update(closed=True)
    dashboard_client = SimpleNamespace(
        indices=SimpleNamespace(exists=lambda **kwargs: dashboard_available),
        search=lambda **kwargs: {"aggregations": {"metric_0": {"value": 20}}},
        close=lambda: state.update(dashboard_closed=True),
    )
    monkeypatch.setattr(script, "create_dashboard_client", lambda settings: dashboard_client)
    monkeypatch.setattr(script, "ActivityRepository", Repository)
    monkeypatch.setattr(script, "create_telemetry_client", lambda settings: client)
    monkeypatch.setattr(database, "get_sync_db_session", session)
    monkeypatch.setattr(tenant_filter, "register_tenant_filter_events", lambda: None)
    directory = tmp_path / "report"
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "export_user_daily_activity.py",
            "--all-tenants",
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-08-02",
            "--output-dir",
            str(directory),
        ],
    )
    token = set_current_tenant_id(99)
    try:
        assert script.main() == (0 if es_available and dashboard_available else 1)
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(token)
    assert state == {"rollback": True, "closed": True, "dashboard_closed": es_available}
    if not es_available or not dashboard_available:
        assert not directory.exists()
        return
    assert {path.name for path in directory.iterdir()} == {
        "每日用户活跃统计.csv",
        "平台用户汇总.csv",
        "每月用户活跃统计.csv",
    }
    with (directory / "每日用户活跃统计.csv").open(encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        script.SUMMARY_HEADERS,
        ["2026-08-01", "2", "3", "66.67%", "65.0"],
        ["2026-08-02", "1", "3", "33.33%", "0.0"],
    ]

    with (directory / "平台用户汇总.csv").open(encoding="utf-8-sig") as stream:
        platform_rows = list(csv.reader(stream))
    assert platform_rows == [script.PLATFORM_HEADERS, ["2026-08-04 12:00:00+08:00", "全平台", "20", "4"]]
    with (directory / "每月用户活跃统计.csv").open(encoding="utf-8-sig") as stream:
        monthly_rows = list(csv.reader(stream))
    assert monthly_rows == [
        ["月份", "统计开始时间", "统计截止时间（不含）", "月活人数"],  # noqa: RUF001
        ["2026-08", "2026-08-01 00:00:00+08:00", "2026-08-03 00:00:00+08:00", "2"],
    ]
