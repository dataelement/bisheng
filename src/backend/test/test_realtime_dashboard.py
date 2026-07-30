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
        scope_filters=[
            DimensionQueryFilter(fieldId="tenant_id", values=[2]),
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
    scope = filters[1].model_dump()
    assert scope["bool_operator"] == "must"
    assert scope["filters"][0]["field"] == "tenant_id"
    assert scope["filters"][0]["value"] == [2]


def test_file_space_level_options_group_section_libraries_under_team():
    from bisheng.telemetry_search.domain.services.dashboard import (
        DashboardService,
    )

    assert DashboardService.FILE_SPACE_LEVEL_LABELS == {
        "public": "公共库",
        "department": "部门库",
        "team": "团队库（含科室库）",
    }


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
async def test_realtime_admin_scope_always_contains_current_tenant(monkeypatch):
    from bisheng.telemetry_search.domain.services import dashboard as module

    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(is_admin=lambda: True)
    )

    filters = await service._get_realtime_scope_filters(
        "mid_knowledge_space_content_stat"
    )

    assert [item.model_dump(by_alias=True) for item in filters] == [
        {"fieldId": "tenant_id", "values": [7]}
    ]


@pytest.mark.asyncio
async def test_department_admin_file_scope_uses_manageable_spaces(monkeypatch):
    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao
    from bisheng.database.models.department import DepartmentDao
    from bisheng.permission.domain.services.permission_service import (
        PermissionService,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(
        DepartmentDao,
        "aget_user_admin_departments",
        AsyncMock(return_value=[SimpleNamespace(id=9, path="1/9")]),
    )
    monkeypatch.setattr(
        PermissionService,
        "list_accessible_ids",
        AsyncMock(return_value=["12", "invalid"]),
    )
    monkeypatch.setattr(
        SpaceChannelMemberDao,
        "async_get_user_managed_members",
        AsyncMock(return_value=[SimpleNamespace(business_id="13")]),
    )
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(
            user_id=22,
            is_admin=lambda: False,
        )
    )

    filters = await service._get_realtime_scope_filters(
        "mid_knowledge_space_content_stat"
    )

    assert [item.model_dump(by_alias=True) for item in filters] == [
        {"fieldId": "tenant_id", "values": [7]},
        {"fieldId": "space_id", "values": [12, 13]},
    ]


@pytest.mark.asyncio
async def test_department_admin_qa_scope_includes_department_subtree(monkeypatch):
    from bisheng.database.models.department import DepartmentDao
    from bisheng.telemetry_search.domain.services import dashboard as module

    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(
        DepartmentDao,
        "aget_user_admin_departments",
        AsyncMock(return_value=[SimpleNamespace(id=9, path="1/9")]),
    )
    monkeypatch.setattr(
        DepartmentDao,
        "aget_subtree_ids",
        AsyncMock(return_value=[9, 10, 11]),
    )
    service = module.DashboardService.model_construct(
        login_user=SimpleNamespace(
            user_id=22,
            is_admin=lambda: False,
        )
    )

    filters = await service._get_realtime_scope_filters(
        "mid_realtime_qa_question_fact"
    )

    assert [item.model_dump(by_alias=True) for item in filters] == [
        {"fieldId": "tenant_id", "values": [7]},
        {"fieldId": "primary_department_id", "values": [9, 10, 11]},
    ]


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
