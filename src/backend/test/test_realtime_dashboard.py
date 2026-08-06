from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeAsyncEs:
    def __init__(self):
        self.update_calls = []
        self.index_calls = []
        self.delete_by_query_calls = []
        self.indices = SimpleNamespace(
            exists=AsyncMock(return_value=True),
            put_mapping=AsyncMock(return_value={"acknowledged": True}),
        )

    async def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"result": "updated"}

    async def index(self, **kwargs):
        self.index_calls.append(kwargs)
        return {"result": "created"}

    async def delete_by_query(self, **kwargs):
        self.delete_by_query_calls.append(kwargs)
        return {"deleted": 1}


def test_realtime_dashboard_seed_contains_three_target_datasets():
    from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET

    datasets = {dataset.dataset_code: dataset for dataset in DASHBOARD_DATASET}
    assert {
        "mid_knowledge_space_content_stat",
        "mid_realtime_qa_question_fact",
        "mid_user_daily_participation",
    }.issubset(datasets)

    participation = datasets["mid_user_daily_participation"]
    metrics = {
        metric["field"]: metric
        for metric in participation.schema_config["metrics"]
    }
    assert metrics["participation_rate"]["formula"] == "divide"
    assert {
        aggregation["type"]
        for aggregation in metrics["participation_rate"]["aggregations"]
    } == {"value_count"}
    assert participation.es_index_name == "mid_user_daily_participation_fact"
    assert "department_source" in {
        dimension["field"]
        for dimension in participation.schema_config["dimensions"]
    }

    qa_dataset = datasets["mid_realtime_qa_question_fact"]
    qa_metrics = {
        metric["field"]: metric
        for metric in qa_dataset.schema_config["metrics"]
    }
    assert qa_metrics["total_qa_count"]["aggregations"][0]["type"] == "value_count"
    assert "department_source" in {
        dimension["field"]
        for dimension in qa_dataset.schema_config["dimensions"]
    }

    knowledge_dataset = datasets["mid_knowledge_space_content_stat"]
    knowledge_metrics = {
        metric["field"]: metric
        for metric in knowledge_dataset.schema_config["metrics"]
    }
    assert knowledge_metrics["total_file_count"]["sum_type"] == "value_count"
    assert knowledge_metrics["new_file_count"]["aggregations"][0]["type"] == "value_count"
    assert knowledge_metrics["preview_count"]["filter"]["filters"] == [
        {"operator": "term", "field": "record_type", "value": "preview_daily"},
        {
            "operator": "terms",
            "field": "space_level",
            "value": ["public", "department", "team", "team_ks", "personal"],
        },
    ]
    for metric_name in ("total_file_count", "new_file_count", "contributor_count"):
        level_filter = next(
            item
            for item in knowledge_metrics[metric_name]["filter"]["filters"]
            if item["field"] == "space_level"
        )
        assert level_filter["value"] == [
            "public",
            "department",
            "team",
            "team_ks",
            "personal",
        ]
    assert knowledge_metrics["preview_count"]["aggregations"][0]["type"] == "sum"
    knowledge_dimensions = {
        dimension["field"]: dimension["name"]
        for dimension in knowledge_dataset.schema_config["dimensions"]
    }
    assert knowledge_dimensions["space_department_name"] == "所属部门"
    assert knowledge_dimensions["primary_department_name"] == "上传人所在部门"


def test_component_data_config_preserves_pivot_column_aliases():
    from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig

    config = ComponentDataConfig.model_validate(
        {
            "pivotColumnAliases": {
                "fieldId": "space_department_name",
                "aliases": {
                    "首钢股份钢铁板块生产部": "生产部",
                },
            },
        }
    )

    assert config.model_dump(by_alias=True)["pivotColumnAliases"] == {
        "fieldId": "space_department_name",
        "aliases": {
            "首钢股份钢铁板块生产部": "生产部",
        },
    }


def test_participation_day_uses_china_local_midnight():
    from bisheng.telemetry.domain.mid_table.daily_participation import (
        participation_day,
    )

    local_date, timestamp = participation_day(
        datetime(2026, 7, 26, 16, 30, tzinfo=timezone.utc)
    )
    assert local_date == "2026-07-27"
    assert datetime.fromtimestamp(timestamp, timezone.utc).isoformat() == (
        "2026-07-26T16:00:00+00:00"
    )


def test_historical_login_backfill_aggregates_by_china_local_day():
    from bisheng.telemetry.domain.mid_table.daily_participation import (
        aggregate_historical_login_hits,
    )

    first = int(
        datetime(2026, 7, 26, 16, 30, tzinfo=timezone.utc).timestamp()
    )
    second = int(
        datetime(2026, 7, 27, 3, 15, tzinfo=timezone.utc).timestamp()
    )
    aggregates = aggregate_historical_login_hits(
        [
            {
                "_source": {
                    "tenant_id": 2,
                    "timestamp": second,
                    "user_context": {"user_id": 17, "user_name": "张三"},
                }
            },
            {
                "_source": {
                    "tenant_id": 2,
                    "timestamp": first,
                    "user_context": {"user_id": 17, "user_name": "张三"},
                }
            },
            {"_source": {"timestamp": "invalid", "user_context": {}}},
        ]
    )

    aggregate = aggregates[(2, "2026-07-27", 17)]
    assert aggregate["login_count"] == 2
    assert aggregate["first_login_at"] == first
    assert aggregate["last_login_at"] == second


@pytest.mark.asyncio
async def test_daily_participation_login_is_atomic_and_department_scoped(
    monkeypatch,
):
    from bisheng.telemetry.domain.mid_table import daily_participation as module

    fake_es = _FakeAsyncEs()

    async def fake_get_es_connection():
        return fake_es

    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection",
        fake_get_es_connection,
    )
    monkeypatch.setattr(
        module.UserDepartmentDao,
        "aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=9)),
    )
    monkeypatch.setattr(
        module.DepartmentDao,
        "aget_by_id",
        AsyncMock(return_value=SimpleNamespace(id=9, name="炼钢部")),
    )

    record = await module.DailyParticipationFact.record_login(
        tenant_id=2,
        user_id=17,
        user_name="张三",
        occurred_at=datetime(2026, 7, 27, 9, 5),
    )

    assert record.es_id == "participation_2_2026-07-27_17"
    assert record.primary_department_id == 9
    assert record.first_login_at == record.last_login_at
    assert record.first_login_at == int(
        datetime(
            2026,
            7,
            27,
            9,
            5,
            tzinfo=timezone(timedelta(hours=8)),
        ).timestamp()
    )
    assert record.department_source == "event_time"
    assert fake_es.update_calls
    call = fake_es.update_calls[0]
    assert call["retry_on_conflict"] == 3
    assert call["upsert"]["logged_in"] is True
    assert call["upsert"]["login_count"] == 1
    assert call["upsert"]["department_source"] == "event_time"
    assert "first_login_at" in call["script"]["source"]
    assert "login_count" in call["script"]["source"]


@pytest.mark.asyncio
async def test_realtime_qa_question_uses_event_time_primary_department(
    monkeypatch,
):
    from bisheng.telemetry.domain.mid_table import realtime_qa_question as module

    fake_es = _FakeAsyncEs()

    async def fake_get_es_connection():
        return fake_es

    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection",
        fake_get_es_connection,
    )
    monkeypatch.setattr(
        module.UserDepartmentDao,
        "aget_user_primary_department",
        AsyncMock(return_value=SimpleNamespace(department_id=6)),
    )
    monkeypatch.setattr(
        module.DepartmentDao,
        "aget_by_id",
        AsyncMock(return_value=SimpleNamespace(id=6, name="制造部")),
    )

    record = await module.RealtimeQaQuestionFact.record_success(
        tenant_id=3,
        user_id=22,
        user_name="李四",
        question_id="q-001",
        qa_type="document",
        scene="document_qa",
        source_app="portal",
        space_id=12,
        file_id=1580,
    )

    assert record.es_id == "qa_3_document_q-001"
    assert record.qa_type_name == "文档内AI对话"
    assert record.primary_department_id == 6
    assert record.department_source == "event_time"
    assert fake_es.index_calls[0]["document"]["question_id"] == "q-001"


@pytest.mark.asyncio
async def test_realtime_qa_question_delete_is_tenant_scoped(monkeypatch):
    from bisheng.telemetry.domain.mid_table import realtime_qa_question as module

    fake_es = _FakeAsyncEs()

    async def fake_get_es_connection():
        return fake_es

    monkeypatch.setattr(
        "bisheng.telemetry.domain.mid_table.base.get_es_connection",
        fake_get_es_connection,
    )

    deleted = await module.RealtimeQaQuestionFact.delete_question(
        tenant_id=3,
        question_id="q-001",
        qa_type="expert",
    )

    assert deleted == 1
    filters = fake_es.delete_by_query_calls[0]["body"]["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": 3}} in filters
    assert {"term": {"question_id": "q-001"}} in filters


@pytest.mark.asyncio
async def test_runtime_dimension_filters_are_combined_with_and():
    from bisheng.telemetry_search.domain.models.dashboard_dataset import (
        DimensionConfig,
    )
    from bisheng.telemetry_search.domain.schemas.component import (
        ComponentDataConfig,
        DimensionQueryFilter,
    )
    from bisheng.telemetry_search.domain.services.component import DataQueryService

    service = DataQueryService(
        dataset_code="mid_knowledge_space_content_stat",
        data_config=ComponentDataConfig(),
        dimension_filters=[
            DimensionQueryFilter(fieldId="space_level", values=["public", "team"]),
            DimensionQueryFilter(fieldId="business_domain_code", values=["steel"]),
        ],
    )
    filters, time_range = await service.convert_filters(
        {
            "space_level": DimensionConfig(
                name="知识库大类",
                field="space_level",
            ),
            "business_domain_code": DimensionConfig(
                name="业务域",
                field="business_domain_code",
            ),
        },
        {},
    )

    assert time_range == []
    dumped = filters[0].model_dump()
    assert dumped["bool_operator"] == "must"
    assert [item["field"] for item in dumped["filters"]] == [
        "space_level",
        "business_domain_code",
    ]
    assert dumped["filters"][0]["value"] == ["public", "team", "team_ks"]


@pytest.mark.asyncio
async def test_realtime_component_query_does_not_pass_server_scope(monkeypatch):
    from bisheng.telemetry_search.domain.models.dashboard import (
        Dashboard,
        DashboardComponent,
        DashboardStatus,
        DashboardType,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    dashboard = Dashboard(
        id=12,
        title="实时统计",
        status=DashboardStatus.PUBLISHED.value,
        dashboard_type=DashboardType.PRESET_OSS.value,
        user_id=7,
    )
    component = DashboardComponent(
        id="metric-1",
        dashboard_id=12,
        type="metric",
        dataset_code="mid_realtime_qa_question_fact",
    )
    captured_kwargs = {}

    class FakeDataQueryService:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def query_telemetry_data(self):
            return "query-result"

    monkeypatch.setattr(
        module.DashboardDao,
        "get_one",
        AsyncMock(return_value=dashboard),
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_one_component",
        AsyncMock(return_value=component),
    )
    monkeypatch.setattr(module, "DataQueryService", FakeDataQueryService)
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(
            is_admin=lambda: True,
            async_access_check=AsyncMock(return_value=True),
        )
    )

    result = await service.query_component_data(
        dashboard_id=12,
        component_id="metric-1",
    )

    assert result == "query-result"
    assert "scope_filters" not in captured_kwargs
    assert captured_kwargs["dimension_filters"] == []


def test_file_space_level_options_group_section_libraries_under_team():
    from bisheng.telemetry_search.domain.services.dashboard import (
        DashboardService,
    )

    assert DashboardService.FILE_SPACE_LEVEL_LABELS == {
        "public": "公共库",
        "department": "部门库",
        "team": "团队库（含科室库）",
        "personal": "个人库",
    }


@pytest.mark.asyncio
async def test_date_field_enums_keep_raw_value_and_format_display_label(
    monkeypatch,
):
    from bisheng.telemetry_search.domain.services import dashboard as module

    timestamp_ms = 1785134769000
    dataset = SimpleNamespace(
        es_index_name="mid_knowledge_space_content_stat",
        schema_config={
            "dimensions": [
                {
                    "field": "timestamp",
                    "field_type": "date",
                }
            ]
        },
    )
    repository = SimpleNamespace(find_one=AsyncMock(return_value=dataset))
    es_client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    "total_count": {"value": 1},
                    "enum_values": {
                        "buckets": [{"key": timestamp_ms}],
                    },
                }
            }
        )
    )

    class FakeDbSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

    monkeypatch.setattr(module, "get_async_db_session", FakeDbSession)
    monkeypatch.setattr(
        module,
        "DashboardDatasetRepositoryImpl",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        module,
        "get_es_connection",
        AsyncMock(return_value=es_client),
    )
    service = module.DashboardService.model_construct()

    result = await service.get_dataset_field_enums(
        dataset_code="mid_knowledge_space_content_stat",
        field="timestamp",
    )

    assert result["options"] == [
        {
            "value": timestamp_ms,
            "label": datetime.fromtimestamp(timestamp_ms / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
    ]


@pytest.mark.parametrize(
    ("field", "values", "expected_labels"),
    [
        (
            "department_source",
            ["event_time", "current_primary_backfill"],
            ["提问时所属主部门", "当前主部门（历史回填）"],
        ),
        (
            "scene",
            [
                "expert_question",
                "smart_qa",
                "document_qa",
                "my_knowledge_document_qa",
            ],
            [
                "专家问答",
                "智能问答",
                "知识门户·文档问答",
                "我的知识·文档问答",
            ],
        ),
        (
            "source_app",
            [
                "bisheng_my_knowledge",
                "expert_qa",
                "shougang_portal",
                "unknown_app",
            ],
            ["毕昇·我的知识", "专家问答", "首钢知识门户", "unknown_app"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_realtime_qa_field_enums_keep_codes_and_use_readable_labels(
    monkeypatch,
    field,
    values,
    expected_labels,
):
    from bisheng.telemetry_search.domain.services import dashboard as module

    dataset = SimpleNamespace(
        es_index_name="mid_realtime_qa_question_fact",
        schema_config={
            "dimensions": [
                {"field": field, "field_type": "string"},
            ]
        },
    )
    repository = SimpleNamespace(find_one=AsyncMock(return_value=dataset))
    es_client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    "total_count": {"value": len(values)},
                    "enum_values": {
                        "buckets": [{"key": value} for value in values],
                    },
                }
            }
        )
    )

    class FakeDbSession:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

    monkeypatch.setattr(module, "get_async_db_session", FakeDbSession)
    monkeypatch.setattr(
        module,
        "DashboardDatasetRepositoryImpl",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        module,
        "get_es_connection",
        AsyncMock(return_value=es_client),
    )
    service = module.DashboardService.model_construct()

    result = await service.get_dataset_field_enums(
        dataset_code="mid_realtime_qa_question_fact",
        field=field,
    )

    assert result["enums"] == values
    assert result["options"] == [
        {"value": value, "label": label}
        for value, label in zip(values, expected_labels, strict=True)
    ]


@pytest.mark.asyncio
async def test_realtime_temporal_datasets_default_to_today_and_include_today():
    from bisheng.telemetry_search.domain.schemas.component import (
        ComponentDataConfig,
        TimeFilter,
    )
    from bisheng.telemetry_search.domain.services.component import DataQueryService

    today = datetime.now().date()
    service = DataQueryService(
        dataset_code="mid_realtime_qa_question_fact",
        data_config=ComponentDataConfig(),
    )
    filters, time_range = await service.convert_filters({}, {})

    assert len(filters) == 1
    assert datetime.fromtimestamp(time_range[0] / 1000).date() == today
    assert datetime.fromtimestamp(time_range[1] / 1000).date() == today

    service.time_filters = [
        TimeFilter(type="recent_days", mode="dynamic", recentDays=7)
    ]
    _, seven_day_range = await service.convert_filters({}, {})
    assert datetime.fromtimestamp(seven_day_range[0] / 1000).date() == (
        today - timedelta(days=6)
    )
    assert datetime.fromtimestamp(seven_day_range[1] / 1000).date() == today


@pytest.mark.asyncio
async def test_department_admin_cannot_edit_realtime_dashboard(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard as module

    class TestUnauthorizedError(Exception):
        pass

    monkeypatch.setattr(module, "UnAuthorizedError", TestUnauthorizedError)
    monkeypatch.setattr(
        module.DashboardDao,
        "get_components",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    dataset_code="mid_knowledge_space_content_stat"
                )
            ]
        ),
    )
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(is_admin=lambda: False)
    )

    with pytest.raises(TestUnauthorizedError):
        await service._ensure_realtime_dashboard_write(12)


@pytest.mark.asyncio
async def test_department_admin_can_view_published_realtime_dashboard_without_group_grant(
    monkeypatch,
):
    from bisheng.telemetry_search.domain.models.dashboard import (
        Dashboard,
        DashboardComponent,
        DashboardStatus,
        DashboardType,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    dashboard = Dashboard(
        id=12,
        title="知识运营大屏",
        status=DashboardStatus.PUBLISHED.value,
        dashboard_type=DashboardType.PRESET_OSS.value,
        user_id=7,
    )
    component = DashboardComponent(
        id="pivot-1",
        dashboard_id=12,
        type="pivot-table",
        dataset_code="mid_knowledge_space_content_stat",
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_one",
        AsyncMock(return_value=dashboard),
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_components",
        AsyncMock(return_value=[component]),
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_default_dashboard",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        module.DashboardService,
        "_is_department_admin",
        AsyncMock(return_value=True),
    )
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(
            user_id=7,
            user_name="部门管理员",
            is_admin=lambda: False,
            async_access_check=AsyncMock(return_value=False),
        )
    )

    result = await service.get_dashboard_detail(12, from_share=False)

    assert result.id == 12
    assert result.write is False
    assert result.components[0].id == "pivot-1"


@pytest.mark.asyncio
async def test_department_admin_realtime_view_cannot_query_component_from_other_dashboard(
    monkeypatch,
):
    from bisheng.telemetry_search.domain.models.dashboard import (
        Dashboard,
        DashboardComponent,
        DashboardStatus,
        DashboardType,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    class TestNotFoundError(Exception):
        pass

    monkeypatch.setattr(module, "NotFoundError", TestNotFoundError)
    dashboard = Dashboard(
        id=12,
        title="知识运营大屏",
        status=DashboardStatus.PUBLISHED.value,
        dashboard_type=DashboardType.PRESET_OSS.value,
        user_id=99,
    )
    realtime_component = DashboardComponent(
        id="pivot-1",
        dashboard_id=12,
        type="pivot-table",
        dataset_code="mid_knowledge_space_content_stat",
    )
    other_component = DashboardComponent(
        id="other-1",
        dashboard_id=99,
        type="metric",
        dataset_code="mid_realtime_qa_question_fact",
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_one",
        AsyncMock(return_value=dashboard),
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_components",
        AsyncMock(return_value=[realtime_component]),
    )
    monkeypatch.setattr(
        module.DashboardDao,
        "get_one_component",
        AsyncMock(return_value=other_component),
    )
    monkeypatch.setattr(
        module.DashboardService,
        "_is_department_admin",
        AsyncMock(return_value=True),
    )
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(
            is_admin=lambda: False,
            async_access_check=AsyncMock(return_value=False),
        )
    )

    with pytest.raises(TestNotFoundError):
        await service.query_component_data(
            dashboard_id=12,
            component_id="other-1",
        )
