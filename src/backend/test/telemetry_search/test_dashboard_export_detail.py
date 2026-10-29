"""Detail-row resolution for chart exports (customer change request, 2026-09-07).

Each exported row must be one of the things the metric counts — a file for 文件数, a
person for 内容贡献人数 — instead of the chart's aggregated number. These cover the four
rules that decide what a row looks like: which filter narrows the records, which metrics
need de-duplicating, which metrics carry a number of their own, and which columns survive.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

if "langchain.docstore.document" not in sys.modules:
    _docstore_stub = MagicMock()
    _docstore_stub.Document = object
    sys.modules.setdefault("langchain.docstore", MagicMock())
    sys.modules["langchain.docstore.document"] = _docstore_stub

from bisheng.telemetry_search.domain.models.dashboard_dataset import MetricConfig
from bisheng.telemetry_search.domain.schemas.component import ComponentDataConfig
from bisheng.telemetry_search.domain.services import dashboard_export_detail as detail_module


def _data_config(metric: dict | None = None, dimensions: list[dict] | None = None) -> ComponentDataConfig:
    return ComponentDataConfig(
        dimensions=dimensions if dimensions is not None else [],
        metrics=[metric] if metric else [],
    )


def test_ratio_metric_details_its_numerator_population_only():
    """成功率 stores numerator + denominator in one filter list (numerator first, see
    component.py::query_formula_metric). Detailing it means "the successful calls", not
    rows that are simultaneously successes and everything-at-all."""
    metric = MetricConfig(
        field="tool_call_success_rate",
        name="工具调用成功率",
        is_virtual=True,
        formula="divide",
        filter={
            "bool_operator": "must",
            "filters": [
                {"operator": "term", "field": "status", "value": "success"},
                {"operator": "match_all", "field": "*"},
            ],
        },
    )

    narrowed = detail_module._metric_filter(metric)

    assert narrowed is not None
    assert [item.field for item in narrowed.filters] == ["status"]


def test_plain_metric_filter_is_used_as_is():
    metric = MetricConfig(
        field="total_file_count",
        name="总文件数",
        is_virtual=True,
        filter={
            "bool_operator": "must",
            "filters": [
                {"operator": "term", "field": "record_type", "value": "file"},
                {"operator": "term", "field": "file_type", "value": 1},
            ],
        },
    )

    narrowed = detail_module._metric_filter(metric)

    assert [item.field for item in narrowed.filters] == ["record_type", "file_type"]


def test_metric_without_filter_adds_nothing():
    assert detail_module._metric_filter(None) is None
    assert detail_module._metric_filter(MetricConfig(field="x", name="X")) is None


def test_headcount_metric_deduplicates_on_the_counted_person():
    """内容贡献人数 counts distinct uploaders over an index whose rows are files — without
    de-duplication the same person would appear once per file they uploaded."""
    metric = MetricConfig(
        field="contributor_count",
        name="内容贡献人数",
        is_virtual=True,
        aggregations=[{"name": "contributor_count", "field": "uploader_user_id", "type": "cardinality"}],
    )

    assert detail_module._deduplicate_field(_data_config(), metric) == "uploader_user_id"


def test_running_total_metric_deduplicates_on_its_sum_field():
    metric = MetricConfig(
        field="total_user_count",
        name="总用户数",
        is_virtual=True,
        index=1,
        sum_field="user_id",
        sum_type="cardinality",
        aggregations=[{"name": "total_user_count", "field": "user_id", "type": "cardinality"}],
    )

    assert detail_module._deduplicate_field(_data_config(), metric) == "user_id"


def test_count_metric_keeps_every_row():
    metric = MetricConfig(
        field="tool_call_count",
        name="工具调用次数",
        is_virtual=True,
        aggregations=[{"name": "tool_call_count", "field": "event_id", "type": "value_count"}],
    )

    assert detail_module._deduplicate_field(_data_config(), metric) is None


def test_author_chosen_distinct_count_also_deduplicates():
    """A non-virtual metric's aggregation is picked in the chart editor, not the dataset."""
    metric = MetricConfig(field="login_count", name="实际登录次数")
    data_config = _data_config({"fieldId": "login_count", "aggregation": "distinct_count"})

    assert detail_module._deduplicate_field(data_config, metric) == "login_count"


def test_summed_metric_brings_its_number_into_the_sheet():
    """下载次数 sums a column that lives on each row, so the row without it is meaningless."""
    metric = MetricConfig(
        field="download_count",
        name="下载次数",
        is_virtual=True,
        aggregations=[{"name": "download_count", "field": "download_count", "type": "sum"}],
    )
    data_config = _data_config({"fieldId": "download_count", "displayName": "下载次数"})

    column = detail_module._value_column(data_config, metric)

    assert column is not None
    assert (column.field, column.label) == ("download_count", "下载次数")


def test_count_metric_has_no_per_row_number():
    metric = MetricConfig(
        field="new_file_count",
        name="新增文件数",
        is_virtual=True,
        aggregations=[{"name": "new_file_count", "field": "file_id", "type": "value_count"}],
    )

    assert detail_module._value_column(_data_config({"fieldId": "new_file_count"}), metric) is None


def test_author_chosen_sum_of_a_stored_column_is_carried():
    metric = MetricConfig(field="file_size", name="文件大小")
    data_config = _data_config({"fieldId": "file_size", "displayName": "文件大小", "aggregation": "sum"})

    column = detail_module._value_column(data_config, metric)

    assert column is not None and column.field == "file_size"


def test_knowledge_detail_lists_readable_fields_without_counted_time():
    fields = [field for field, _label in detail_module.DETAIL_IDENTITY_COLUMNS["mid_knowledge_space_content_stat"]]

    assert fields[:4] == ["file_name", "space_name", "space_level_name", "file_category_name"]
    for field in (
        "file_subcategory_name",
        "business_domain_name",
        "uploader_user_id",
        "uploader_company_name",
        "uploader_department_name",
        "uploader_office_name",
        "uploader_squad_name",
        "belonging_company_name",
        "belonging_department_name",
        "belonging_office_name",
        "belonging_squad_name",
        "original_space_name",
    ):
        assert field in fields
    assert "counted_at_text" not in fields
    assert "timestamp" not in fields


def test_qa_detail_lists_source_and_ids_without_asker_id():
    fields = [field for field, _label in detail_module.DETAIL_IDENTITY_COLUMNS["mid_realtime_qa_question_fact"]]

    assert fields[fields.index("scene") + 1] == "source_app"
    for field in ("space_id", "file_id", "business_domain_code"):
        assert field in fields
    assert "user_id" not in fields


def test_login_event_columns_follow_the_row_grain():
    day_metrics = (
        MetricConfig(field="logged_in_employee_count", name="累计登录人次", is_virtual=True),
        MetricConfig(field="login_count", name="实际登录次数"),
    )
    person_metrics = (
        MetricConfig(field="active_user_count", name="活跃用户数", is_virtual=True),
        MetricConfig(field="participation_rate", name="全员参与度占比", is_virtual=True),
        MetricConfig(field="active_employee_count", name="全员有效用户数", is_virtual=True),
    )
    expected = ["primary_department_name", "login_count", "first_login_at_text", "last_login_at_text"]

    for dataset_code in ("mid_user_increment", "mid_user_daily_participation"):
        for metric in day_metrics:
            assert [column.field for column in detail_module._login_event_columns(dataset_code, metric)] == expected
        for metric in person_metrics:
            assert detail_module._login_event_columns(dataset_code, metric) == []
    assert (
        detail_module._login_event_columns("mid_active_user", MetricConfig(field="login_count", name="实际登录次数"))
        == []
    )


def test_qa_enum_label_uses_dashboard_text_and_keeps_unknown_codes():
    assert detail_module._enum_label("mid_realtime_qa_question_fact", "scene", "expert_question") == "专家问答"
    assert detail_module._enum_label("mid_realtime_qa_question_fact", "source_app", "shougang_portal") == "首钢知识门户"
    assert detail_module._enum_label("mid_realtime_qa_question_fact", "scene", "custom_scene") == "custom_scene"
    assert detail_module._enum_label("mid_realtime_qa_question_fact", "scene", None) is None


async def test_qa_export_translates_known_labels_and_drops_asker_id(monkeypatch):
    from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET

    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == "mid_realtime_qa_question_fact")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    captured: dict = {}

    async def scan(*_args, **kwargs):
        captured["includes"] = kwargs["query"]["_source"]["includes"]
        yield {
            "_source": {
                "user_id": 3,
                "user_name": "张三",
                "qa_type": "expert",
                "qa_type_name": "专家问答",
                "scene": "document_qa",
                "source_app": "other_app",
                "question_id": "7",
                "conversation_id": "chat-1",
                "space_id": 12,
                "file_id": 34,
                "business_domain_code": "ROLL",
                "timestamp": 1780000000,
            }
        }

    monkeypatch.setattr(detail_module, "get_async_db_session", Session)
    monkeypatch.setattr(
        detail_module,
        "DashboardDatasetRepositoryImpl",
        lambda _: SimpleNamespace(find_one=AsyncMock(return_value=dataset)),
    )
    monkeypatch.setattr(detail_module, "get_es_connection", AsyncMock())
    monkeypatch.setattr(detail_module, "async_scan", scan)
    monkeypatch.setattr(detail_module, "enrich_qa_detail_rows", AsyncMock())

    result = await detail_module.query_detail_rows(
        dataset_code="mid_realtime_qa_question_fact",
        data_config=ComponentDataConfig(metrics=[{"fieldId": "total_qa_count"}]),
        row_limit=10,
    )

    row = result.rows[0]
    assert row["scene"] == "知识门户·文档问答"
    assert row["source_app"] == "other_app"
    assert row["space_id"] == 12
    assert row["file_id"] == 34
    assert row["business_domain_code"] == "ROLL"
    assert "user_id" not in row
    assert "question_id" not in row
    assert "user_id" in captured["includes"]


def test_columns_start_with_identity_then_chart_dimensions_without_repeats():
    data_config = _data_config(
        metric={"fieldId": "new_file_count"},
        dimensions=[
            {"fieldId": "file_name", "displayName": "文件名"},
            {"fieldId": "belonging_department_name", "displayName": "所属部门"},
        ],
    )

    identity = [
        detail_module.DetailColumn(field=field, label=label)
        for field, label in detail_module.DETAIL_IDENTITY_COLUMNS["mid_knowledge_space_content_stat"]
    ]
    columns = detail_module._ordered_unique([*identity, *detail_module._dimension_columns(data_config)])
    fields = [column.field for column in columns]

    assert fields[0] == "file_name"
    assert fields.count("file_name") == 1
    assert "belonging_department_name" in fields


def test_nested_field_values_are_read_off_the_document():
    source = {"user_group_infos": {"user_group_name": "运维组"}, "file_name": "a.pdf"}

    assert detail_module._source_value(source, "file_name") == "a.pdf"
    assert detail_module._source_value(source, "user_group_infos.user_group_name") == "运维组"
    assert detail_module._source_value(source, "missing.path") is None


def test_filters_become_one_bool_query():
    from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression

    filters = [
        FilterExpression(bool_operator="must", filters=[{"operator": "term", "field": "status", "value": "success"}]),
        FilterExpression(
            bool_operator="must", filters=[{"operator": "term", "field": "parse_type", "value": "etl4lm"}]
        ),
    ]

    query = detail_module._build_bool_query(filters)

    assert len(query["bool"]["must"]) == 2
    assert detail_module._build_bool_query([]) == {"match_all": {}}
