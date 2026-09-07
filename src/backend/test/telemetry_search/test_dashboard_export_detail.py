"""Detail-row resolution for chart exports (customer change request, 2026-09-07).

Each exported row must be one of the things the metric counts — a file for 文件数, a
person for 内容贡献人数 — instead of the chart's aggregated number. These cover the four
rules that decide what a row looks like: which filter narrows the records, which metrics
need de-duplicating, which metrics carry a number of their own, and which columns survive.
"""

import sys
from unittest.mock import MagicMock

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
        FilterExpression(bool_operator="must", filters=[{"operator": "term", "field": "parse_type", "value": "etl4lm"}]),
    ]

    query = detail_module._build_bool_query(filters)

    assert len(query["bool"]["must"]) == 2
    assert detail_module._build_bool_query([]) == {"match_all": {}}
