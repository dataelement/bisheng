from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _FakeDbSession:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


async def _get_field_options(
    monkeypatch,
    *,
    dataset_code,
    field,
    values,
    label_field=None,
    raw_labels=None,
    keyword=None,
):
    from bisheng.telemetry_search.domain.services import dashboard as module

    dimensions = [{"field": field, "field_type": "string"}]
    if label_field:
        dimensions.append({"field": label_field, "field_type": "string"})
    dataset = SimpleNamespace(
        es_index_name=dataset_code,
        schema_config={"dimensions": dimensions},
    )
    repository = SimpleNamespace(find_one=AsyncMock(return_value=dataset))
    buckets = []
    for index, value in enumerate(values):
        bucket = {"key": value}
        if label_field:
            bucket["label_value"] = {
                "buckets": [{"key": raw_labels[index]}],
            }
        buckets.append(bucket)
    es_client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    **(
                        {
                            "filter_wrapper": {
                                "total_count": {"value": len(values)},
                                "enum_values": {"buckets": buckets},
                            }
                        }
                        if keyword
                        else {
                            "total_count": {"value": len(values)},
                            "enum_values": {"buckets": buckets},
                        }
                    )
                }
            }
        )
    )

    monkeypatch.setattr(module, "get_async_db_session", _FakeDbSession)
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
        dataset_code=dataset_code,
        field=field,
        label_field=label_field,
        keyword=keyword,
    )
    return result, es_client.search.await_args.kwargs["body"]


@pytest.mark.parametrize(
    (
        "dataset_code",
        "field",
        "label_field",
        "values",
        "raw_labels",
        "expected_labels",
    ),
    [
        (
            "mid_app_increment",
            "app_type",
            None,
            ["assistant", "workflow", "daily_chat", "unknown"],
            None,
            ["助手", "工作流", "日常对话", "未知"],
        ),
        (
            "mid_sessions_increment",
            "source",
            None,
            ["platform", "api"],
            None,
            ["平台端", "API调用"],
        ),
        (
            "mid_sessions_increment",
            "app_id",
            "app_name",
            ["daily_chat", "linsight", "42"],
            ["daily_chat", "linsight", "自定义应用"],
            ["日常对话", "Linsight", "自定义应用"],
        ),
        (
            "mid_session_run_dtl",
            "app_id",
            "app_name",
            ["linsight"],
            ["linsight"],
            ["Linsight"],
        ),
        (
            "mid_tool_call_dtl",
            "tool_type",
            None,
            [0, 1, 2],
            None,
            ["API工具", "内置工具", "MCP工具"],
        ),
        (
            "mid_tool_call_dtl",
            "app_type",
            None,
            ["assistant"],
            None,
            ["助手"],
        ),
        (
            "mid_doc_parse_dtl",
            "parse_type",
            None,
            ["local", "etl4lm", "un_etl4lm", "mineru", "paddle_ocr"],
            None,
            [
                "本地解析",
                "ETL4LM解析",
                "非ETL4LM解析",
                "MinerU解析",
                "PaddleOCR解析",
            ],
        ),
        (
            "mid_doc_parse_dtl",
            "status",
            None,
            ["success", "failed", "parse_failed"],
            None,
            ["成功", "失败", "解析失败"],
        ),
        (
            "mid_doc_parse_dtl",
            "app_type",
            None,
            ["knowledge_base"],
            None,
            ["知识库"],
        ),
        (
            "mid_model_call_dtl",
            "model_type",
            None,
            ["llm", "embedding", "rerank", "asr", "tts"],
            None,
            ["大语言模型", "嵌入模型", "重排模型", "语音识别", "语音合成"],
        ),
        (
            "mid_model_call_dtl",
            "app_id",
            "app_name",
            ["evaluation"],
            ["evaluation"],
            ["模型评测"],
        ),
        (
            "mid_user_daily_participation",
            "department_source",
            None,
            [
                "event_time",
                "current_roster",
                "current_roster_backfill",
                "current_primary_backfill",
            ],
            None,
            [
                "登录时所属主部门",
                "当前在职名册",
                "当前名册（历史回填）",
                "当前主部门（历史登录回填）",
            ],
        ),
        (
            "mid_knowledge_space_content_stat",
            "space_level",
            None,
            ["team", "team_ks"],
            None,
            ["团队库", "科室库"],
        ),
    ],
    ids=[
        "application-type",
        "session-source",
        "session-system-app",
        "runtime-system-app",
        "tool-type",
        "tool-app-type",
        "parse-type",
        "parse-status",
        "parse-app-type",
        "model-type",
        "model-system-app",
        "participation-department-source",
        "knowledge-space-level",
    ],
)
@pytest.mark.asyncio
async def test_dashboard_enum_options_keep_values_and_use_readable_labels(
    monkeypatch,
    dataset_code,
    field,
    label_field,
    values,
    raw_labels,
    expected_labels,
):
    result, _ = await _get_field_options(
        monkeypatch,
        dataset_code=dataset_code,
        field=field,
        values=values,
        label_field=label_field,
        raw_labels=raw_labels,
    )

    assert result["enums"] == values
    assert result["options"] == [
        {"value": value, "label": label} for value, label in zip(values, expected_labels, strict=True)
    ]


@pytest.mark.asyncio
async def test_realtime_dataset_enum_query_has_no_implicit_scope_filter(monkeypatch):
    result, body = await _get_field_options(
        monkeypatch,
        dataset_code="mid_realtime_qa_question_fact",
        field="primary_department_id",
        values=[9, 10, 11],
    )

    assert result["enums"] == [9, 10, 11]
    assert "query" not in body


@pytest.mark.parametrize(
    ("dataset_code", "field", "label_field", "keyword", "expected_values"),
    [
        ("mid_app_increment", "app_type", None, "助手", ["assistant"]),
        (
            "mid_sessions_increment",
            "app_id",
            "app_name",
            "日常对话",
            ["daily_chat"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_dashboard_enum_search_matches_readable_labels(
    monkeypatch,
    dataset_code,
    field,
    label_field,
    keyword,
    expected_values,
):
    result, body = await _get_field_options(
        monkeypatch,
        dataset_code=dataset_code,
        field=field,
        values=expected_values,
        label_field=label_field,
        raw_labels=expected_values if label_field else None,
        keyword=keyword,
    )

    search_filter = body["aggs"]["filter_wrapper"]["filter"]
    assert {"terms": {field: expected_values}} in search_filter["bool"]["should"]
    assert result["enums"] == expected_values


@pytest.mark.asyncio
async def test_space_level_name_options_use_fixed_customer_order_not_es_key_order(monkeypatch):
    """知识库大类 dropdown: 公共库/部门库/科室库/团队库/个人库 fixed order agreed with the
    customer — not the ES terms-agg's default `_key` (alphabetical Unicode) order."""
    es_arbitrary_order = ["个人库", "科室库", "公共库", "团队库", "部门库"]

    result, _ = await _get_field_options(
        monkeypatch,
        dataset_code="mid_knowledge_space_content_stat",
        field="space_level_name",
        values=es_arbitrary_order,
    )

    assert [option["value"] for option in result["options"]] == [
        "公共库", "部门库", "科室库", "团队库", "个人库",
    ]


@pytest.mark.asyncio
async def test_space_level_code_field_with_name_label_field_also_uses_fixed_order(monkeypatch):
    """The dashboard config UI (DimensionFilterConfigurator) auto-pairs the raw
    space_level (code) field with space_level_name as its label_field and hides
    space_level_name from the picker — so in practice the configured widget has
    field="space_level" (value=code) with label_field="space_level_name" (label=Chinese
    text), not field="space_level_name" directly. The fixed order must still apply here,
    sorted on the resolved label."""
    codes_in_arbitrary_order = ["personal", "team_ks", "public", "team", "department"]
    labels_in_same_order = ["个人库", "科室库", "公共库", "团队库", "部门库"]

    result, _ = await _get_field_options(
        monkeypatch,
        dataset_code="mid_knowledge_space_content_stat",
        field="space_level",
        label_field="space_level_name",
        values=codes_in_arbitrary_order,
        raw_labels=labels_in_same_order,
    )

    assert [option["label"] for option in result["options"]] == [
        "公共库", "部门库", "科室库", "团队库", "个人库",
    ]
    assert [option["value"] for option in result["options"]] == [
        "public", "department", "team_ks", "team", "personal",
    ]


def test_dashboard_dataset_seed_exposes_readable_tool_and_parse_dimensions():
    from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET

    datasets = {dataset.dataset_code: dataset for dataset in DASHBOARD_DATASET}
    tool_dimensions = {
        dimension["field"]: dimension for dimension in datasets["mid_tool_call_dtl"].schema_config["dimensions"]
    }
    parse_dimensions = {
        dimension["field"]: dimension for dimension in datasets["mid_doc_parse_dtl"].schema_config["dimensions"]
    }

    assert tool_dimensions["app_type"]["name"] == "应用类型"
    assert tool_dimensions["app_name"]["name"] == "应用名称"
    assert parse_dimensions["app_type"]["name"] == "应用类型"


@pytest.mark.asyncio
async def test_dashboard_dataset_upgrade_refreshes_changed_dimension_schemas():
    from bisheng.telemetry_search.domain.init_dataset import (
        DASHBOARD_DATASET,
        DASHBOARD_DATASET_REFRESH_CODES,
        _upgrade_dashboard_datasets,
    )

    seeds = {dataset.dataset_code: dataset for dataset in DASHBOARD_DATASET}
    existing = {
        dataset_code: SimpleNamespace(
            dataset_code=dataset_code,
            dataset_name="旧名称",
            es_index_name="旧索引",
            description="旧描述",
            is_commercial_only=False,
            schema_config={},
        )
        for dataset_code in DASHBOARD_DATASET_REFRESH_CODES
    }
    repository = SimpleNamespace(
        find_one=AsyncMock(side_effect=lambda dataset_code: existing.get(dataset_code)),
        save=AsyncMock(),
        update=AsyncMock(),
    )

    await _upgrade_dashboard_datasets(repository)

    assert repository.update.await_count == len(DASHBOARD_DATASET_REFRESH_CODES)
    assert repository.save.await_count == 0
    for dataset_code, dataset in existing.items():
        assert dataset.schema_config == seeds[dataset_code].schema_config

    tool_dimensions = {
        dimension["field"]: dimension for dimension in existing["mid_tool_call_dtl"].schema_config["dimensions"]
    }
    parse_dimensions = {
        dimension["field"]: dimension for dimension in existing["mid_doc_parse_dtl"].schema_config["dimensions"]
    }
    assert tool_dimensions["app_name"]["name"] == "应用名称"
    assert parse_dimensions["app_type"]["name"] == "应用类型"
