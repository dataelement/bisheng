"""Detail-row resolution for dashboard chart exports (customer change request, 2026-09-07).

Before: exporting a chart wrote out the same aggregated numbers the chart already shows.
Now: it writes the underlying records that add up to that number — one row per file /
per tool call / per question — with the chart's dimension columns alongside.

One rule makes this work across every dataset: re-run the chart's own filters (time
range + chart filters + the clicked category) *plus* the metric's own filter (总文件数,
for instance, only counts ``record_type=file`` AND ``file_type=1``), then fetch the raw
documents instead of an aggregation. Whatever grain the index stores is what the sheet
gets — which is also the agreed fallback for the metrics whose index only ever stored
pre-aggregated rows (预览/下载/收藏 are stored per file per day, so that is the row) or
which never recorded a human-readable identity at all (文件解析 has no file name).

Two adjustments on top of the raw fetch:
- Distinct-count metrics (内容贡献人数, 提问人数, 活跃用户数 …) count people over an index
  whose rows are files/questions/days, so the same person appears many times. Those
  exports are de-duplicated on the counted field, one row per person.
- A metric that sums a stored number (下载次数, 文件大小, Token消耗量 …) carries that
  column into the sheet; a pure count metric does not, since every row would just say 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from elasticsearch.helpers import async_scan

from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection

from ..models.dashboard_dataset import MetricConfig, SchemaConfig
from ..repositories.implementations.dataset_repository_impl import DashboardDatasetRepositoryImpl
from ..schemas.component import AggregationType, ComponentDataConfig, DimensionQueryFilter, TimeFilter
from ..schemas.query_builder import AggsTypeEnum, FilterExpression
from .component import DataQueryService

# Per-dataset "which one is this" columns, in display order. These are read straight off
# the stored document, so they cover fields that were never declared as chart dimensions
# (file_name, session_id, event_id …). Any column that comes back empty for every row is
# dropped before writing the sheet, so it is safe to list fields that only exist on some
# record types of a mixed-grain index (local_date only exists on the daily rows of
# mid_knowledge_space_content_stat, metric_source only on mid_user_engagement_stat …).
DETAIL_IDENTITY_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "mid_knowledge_space_content_stat": [
        ("file_name", "文件名"),
        ("space_name", "知识空间"),
        ("space_level_name", "知识库大类"),
        ("file_category_name", "知识分类"),
        ("uploader_user_name", "上传人"),
        ("local_date", "日期"),
    ],
    "mid_knowledge_file_increment": [
        # This index stores only the knowledge base's id and type, never its name.
        ("file_name", "文件名"),
        ("knowledge_base_type", "知识库类型"),
        ("user_name", "上传人"),
    ],
    "mid_knowledge_increment": [
        ("knowledge_name", "知识库名称"),
        ("user_name", "创建人"),
    ],
    "mid_app_increment": [
        ("app_name", "应用名称"),
        ("app_type", "应用类型"),
        ("user_name", "创建人"),
    ],
    "mid_sessions_increment": [
        ("session_id", "会话ID"),
        ("app_name", "应用名称"),
        ("user_name", "使用人"),
    ],
    "mid_session_run_dtl": [
        ("session_id", "会话ID"),
        ("app_name", "应用名称"),
        ("user_name", "使用人"),
    ],
    "mid_tool_call_dtl": [
        ("tool_name", "工具名称"),
        ("app_name", "应用名称"),
        ("user_name", "调用人"),
        ("status", "状态"),
    ],
    "mid_doc_parse_dtl": [
        ("user_name", "操作人"),
        ("parse_type", "解析方式"),
        ("status", "状态"),
    ],
    "mid_model_call_dtl": [
        ("model_name", "模型名称"),
        ("model_server_name", "模型服务"),
        ("app_name", "应用名称"),
        ("user_name", "调用人"),
    ],
    "mid_realtime_qa_question_fact": [
        ("user_name", "提问人"),
        ("qa_type_name", "问答类型"),
        ("scene", "场景"),
        ("primary_department_name", "所属部门"),
    ],
    "mid_user_increment": [
        ("user_name", "用户名"),
        ("local_date", "日期"),
    ],
}

_TIMESTAMP_FIELD = "timestamp"
_SUMMABLE_AGGREGATIONS = {
    AggsTypeEnum.SUM,
    AggsTypeEnum.AVG,
    AggsTypeEnum.MAX,
    AggsTypeEnum.MIN,
}


@dataclass
class DetailColumn:
    field: str
    label: str


@dataclass
class DetailRows:
    columns: list[DetailColumn]
    rows: list[dict[str, Any]]


def _metric_config_for(data_config: ComponentDataConfig, metric_map: dict[str, MetricConfig]) -> MetricConfig | None:
    if not data_config.metrics:
        return None
    return metric_map.get(data_config.metrics[0].field_id)


def _metric_filter(metric_config: MetricConfig | None) -> FilterExpression | None:
    """The metric's own filter, narrowed to its numerator for a ratio metric.

    A ratio metric (成功率, 参与占比 …) stores numerator and denominator conditions in one
    filter list — first entry is the numerator, the rest the denominator (see
    component.py::query_formula_metric). Detailing "the rows behind 成功率" means the
    numerator population; ANDing both halves would ask for rows that are simultaneously
    successes and everything-at-all.
    """
    if metric_config is None or metric_config.filter is None:
        return None
    if metric_config.formula is not None:
        numerator = metric_config.filter.filters[:1]
        if not numerator:
            return None
        return FilterExpression(bool_operator="must", filters=numerator)
    return metric_config.filter


def _deduplicate_field(data_config: ComponentDataConfig, metric_config: MetricConfig | None) -> str | None:
    """Field to de-duplicate on, for metrics that count distinct things.

    人数-style metrics count distinct users over an index whose rows are files, questions
    or per-day records, so the raw rows repeat the same person. Everything else keeps its
    rows as-is.
    """
    if metric_config is not None and metric_config.is_virtual:
        if metric_config.sum_field and metric_config.sum_type == AggsTypeEnum.CARDINALITY:
            return metric_config.sum_field
        for aggregation in metric_config.aggregations or []:
            if aggregation.type == AggsTypeEnum.CARDINALITY and aggregation.field:
                return aggregation.field
        return None
    if data_config.metrics and data_config.metrics[0].aggregation == AggregationType.DISTINCT_COUNT:
        return metric_config.field if metric_config else data_config.metrics[0].field_id
    return None


def _value_column(data_config: ComponentDataConfig, metric_config: MetricConfig | None) -> DetailColumn | None:
    """The metric's own number, when a single row actually carries one.

    下载次数/文件大小/Token消耗量 sum a column that lives on each row, so that column is the
    point of the row. A count or distinct-count metric has no per-row number — every row
    would just read 1 — so the sheet simply lists the rows.
    """
    if metric_config is None or not data_config.metrics:
        return None
    label = data_config.metrics[0].display_name or metric_config.name
    if metric_config.is_virtual:
        for aggregation in metric_config.aggregations or []:
            if aggregation.type in _SUMMABLE_AGGREGATIONS and aggregation.field:
                return DetailColumn(field=aggregation.field, label=label)
        return None
    if data_config.metrics[0].aggregation in (AggregationType.COUNT, AggregationType.DISTINCT_COUNT):
        return None
    return DetailColumn(field=metric_config.field, label=label)


def _dimension_columns(data_config: ComponentDataConfig) -> list[DetailColumn]:
    columns: list[DetailColumn] = []
    for dimension in [*data_config.dimensions, *data_config.get_stack_dimensions()]:
        label = dimension.display_name or dimension.field_name or dimension.field_id
        columns.append(DetailColumn(field=dimension.field_id, label=label))
    return columns


def _ordered_unique(columns: list[DetailColumn]) -> list[DetailColumn]:
    seen: set[str] = set()
    result: list[DetailColumn] = []
    for column in columns:
        if column.field in seen:
            continue
        seen.add(column.field)
        result.append(column)
    return result


def _build_bool_query(filters: list[FilterExpression] | None) -> dict[str, Any]:
    if not filters:
        return {"match_all": {}}
    bool_query: dict[str, list] = {}
    for filter_expr in filters:
        for operator, conditions in filter_expr.to_dsl().items():
            bool_query.setdefault(operator, []).extend(conditions)
    return {"bool": bool_query} if bool_query else {"match_all": {}}


def _source_value(source: dict[str, Any], field: str) -> Any:
    """Read a possibly dotted field path off the stored document."""
    if field in source:
        return source[field]
    current: Any = source
    for part in field.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


async def query_detail_rows(
    *,
    dataset_code: str,
    data_config: ComponentDataConfig,
    time_filters: list[TimeFilter] | None = None,
    dimension_filters: list[DimensionQueryFilter] | None = None,
    row_limit: int,
) -> DetailRows:
    """Fetch the raw records behind a chart's first metric, with its display columns."""
    async with get_async_db_session() as session:
        repository = DashboardDatasetRepositoryImpl(session)
        dataset = await repository.find_one(dataset_code=dataset_code)
    if not dataset:
        return DetailRows(columns=[], rows=[])

    schema_config = SchemaConfig(**dataset.schema_config)
    metric_map = {item.field: item for item in schema_config.metrics}
    dimension_map = {item.field: item for item in schema_config.dimensions}

    query_service = DataQueryService(
        dataset_code=dataset_code,
        data_config=data_config,
        time_filters=time_filters,
        dimension_filters=dimension_filters or [],
    )
    filters, time_range = await query_service.convert_filters(dimension_map, metric_map)
    if time_range is None:
        # The chart's own time filter and the dashboard's don't overlap — the chart shows
        # nothing, so neither should the export.
        return DetailRows(columns=[], rows=[])

    metric_config = _metric_config_for(data_config, metric_map)
    filters = DataQueryService.merge_filters(filters, _metric_filter(metric_config))

    identity_columns = [
        DetailColumn(field=field, label=label)
        for field, label in DETAIL_IDENTITY_COLUMNS.get(dataset_code, [])
    ]
    value_column = _value_column(data_config, metric_config)
    columns = _ordered_unique(
        [*identity_columns, *_dimension_columns(data_config), *([value_column] if value_column else [])]
    )
    deduplicate_field = _deduplicate_field(data_config, metric_config)

    source_fields = {column.field for column in columns}
    source_fields.add(_TIMESTAMP_FIELD)
    if deduplicate_field:
        source_fields.add(deduplicate_field)

    es_client = await get_es_connection()
    rows: list[dict[str, Any]] = []
    seen_keys: set[Any] = set()
    async for hit in async_scan(
        es_client,
        index=dataset.es_index_name,
        query={"query": _build_bool_query(filters), "_source": {"includes": sorted(source_fields)}},
        preserve_order=False,
    ):
        source = hit.get("_source") or {}
        if deduplicate_field:
            key = _source_value(source, deduplicate_field)
            if key in seen_keys:
                continue
            seen_keys.add(key)
        rows.append(
            {
                _TIMESTAMP_FIELD: source.get(_TIMESTAMP_FIELD),
                **{column.field: _source_value(source, column.field) for column in columns},
            }
        )
        if len(rows) > row_limit:
            break

    rows.sort(key=lambda row: row.get(_TIMESTAMP_FIELD) or 0, reverse=True)
    for row in rows:
        row.pop(_TIMESTAMP_FIELD, None)

    # Columns that are empty for every row carry no information — a mixed-grain index
    # (file rows vs. per-day rows) always produces a few of these.
    populated = [
        column
        for column in columns
        if any(row.get(column.field) not in (None, "") for row in rows)
    ]
    return DetailRows(columns=populated or columns, rows=rows)
