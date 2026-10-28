from datetime import datetime, timedelta, tzinfo
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class OperatorType(str, Enum):
    EQUAL = "equals"
    NOT_EQUAL = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"
    IN = "in"  # value in a list


class LogicType(str, Enum):
    AND = "and"
    OR = "or"


class AggregationType(str, Enum):
    SUM = "sum"
    AVERAGE = "average"
    COUNT = "count"
    MAX = "max"
    MIN = "min"
    DISTINCT_COUNT = "distinct_count"


class TimeRangeType(str, Enum):
    ALL = "all"
    RECENT_DAYS = "recent_days"
    CUSTOM = "custom"


class TimeRangeMode(str, Enum):
    FIXED = "fixed"  # fixed time range
    DYNAMIC = "dynamic"  # dynamic time range


class DimensionField(BaseModel):
    field_id: str = Field(alias="fieldId")
    field_name: str | None = Field(default="", alias="fieldName")
    display_name: str | None = Field(default="", alias="displayName")
    sort: str | None = Field(default=None, description="asc or desc")
    time_granularity: Literal["year", "month", "week", "day", "hour"] | None = Field(
        default=None, alias="timeGranularity", description="timeGranularity"
    )


class MetricField(BaseModel):
    field_id: str = Field(alias="fieldId")
    field_name: str | None = Field(default="", alias="fieldName")
    display_name: str | None = Field(default="", alias="displayName")
    aggregation: AggregationType | None = Field(default="", alias="aggregation", description="aggregation type")
    is_virtual: bool | None = Field(default=False, alias="isVirtual")
    sort: str | None = Field(default=None, description="asc or desc")
    numberFormat: dict | None = Field(default_factory=dict, alias="numberFormat")


class FilterCondition(BaseModel):
    id: str | None = Field(default="", alias="id")
    field_id: str = Field(alias="fieldId")
    field_name: str | None = Field(default="", alias="fieldName")
    filter_type: str = Field(alias="filterType")
    operator: OperatorType = Field(alias="operator")
    value: Any = Field(default=None, alias="value")


class DimensionQueryFilter(BaseModel):
    """Runtime multi-select filter supplied by a dashboard filter component."""

    field_id: str = Field(alias="fieldId")
    values: list[Any] = Field(default_factory=list)


class FieldOrder(BaseModel):
    field_id: str = Field(alias="fieldId")
    field_type: str = Field(
        alias="fieldType", description="dimension、stack_dimension、metric"
    )  # 'dimension' or 'metric'


class TimeFilter(BaseModel):
    type: TimeRangeType | None = Field(default=None, description="time range type")
    mode: TimeRangeMode = Field(default=None, description="time range mode")
    recent_days: int | None = Field(default=None, alias="recentDays")
    start_date: int | None = Field(default=None, alias="startDate", description="start timestamp(s)")
    end_date: int | None = Field(default=None, alias="endDate", description="end timestamp(s)")

    def get_start_end_date(
        self,
        *,
        include_today: bool = False,
        timezone: tzinfo | None = None,
    ) -> (int | None, int | None):
        if self.mode == TimeRangeMode.DYNAMIC:
            recent_days = max(int(self.recent_days or 1), 1)
            now = datetime.now(timezone) if timezone else datetime.now()
            if include_today:
                start = datetime(
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    tzinfo=timezone,
                ) - timedelta(days=recent_days - 1)
                end = datetime(
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    tzinfo=timezone,
                    hour=23,
                    minute=59,
                    second=59,
                )
                start_date = int(start.timestamp() * 1000)
                end_date = int(end.timestamp() * 1000)
            else:
                end = now - timedelta(days=1)
                end_date = int(
                    datetime(
                        year=end.year,
                        month=end.month,
                        day=end.day,
                        hour=23,
                        minute=59,
                        second=59,
                        tzinfo=timezone,
                    ).timestamp()
                    * 1000
                )
                start_date = int((now - timedelta(days=recent_days)).timestamp() * 1000)
        else:
            if not self.start_date or not self.end_date:
                return None, None
            start_date = self.start_date * 1000
            end_date = self.end_date * 1000
        return start_date, end_date


class ComponentDetailExportRequest(BaseModel):
    """维度值必须提供, 但允许 null 表示缺失值分组。"""

    dashboard_id: int
    dimension_field: str
    dimension_value: Any
    time_filters: list[TimeFilter] | None = None
    dimension_filters: list[DimensionQueryFilter] | None = None


class PivotSheetMerge(BaseModel):
    """交叉表画面里的一个合并区域, 行列从 0 开始, 跨度含起始格."""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)


class PivotSheet(BaseModel):
    """交叉表导出第一页. 内容由当前画面生成, 服务端只负责写入."""

    has_table: bool = False
    rows: list[list[str | int | float | None]] = Field(default_factory=list)
    merges: list[PivotSheetMerge] = Field(default_factory=list)


class ResultLimit(BaseModel):
    limit_type: str = Field(alias="limitType", description="all or limited")
    limit: int = Field(default=0, alias="limit", description="number of results to limit")

    def get_limit_number(self) -> int | None:
        if self.limit_type == "limited":
            return self.limit
        return 0


class PivotColumnAliases(BaseModel):
    field_id: str = Field(alias="fieldId")
    aliases: dict[str, str] = Field(default_factory=dict)


class ComponentDataConfig(BaseModel):
    dimensions: list[DimensionField] = Field(default_factory=list, description="list of dimension fields")
    stack_dimension: DimensionField | None = Field(
        default=None, alias="stackDimension", description="list of stack dimension fields"
    )
    stack_dimensions: list[DimensionField] = Field(
        default_factory=list,
        alias="stackDimensions",
        max_length=2,
        description="ordered pivot table column dimensions",
    )
    metrics: list[MetricField] = Field(default_factory=list, description="list of metric fields")
    field_order: list[FieldOrder] = Field(default_factory=list, alias="fieldOrder", description="list of field order")
    filters: list[FilterCondition] = Field(default_factory=list, description="list of filter conditions")
    filters_logic: str | None = Field(default=LogicType.AND, alias="filtersLogic", description="logic for filters")
    time_filter: TimeFilter | None = Field(default=None, alias="timeFilter")
    result_limit: ResultLimit | None = Field(default=None, alias="resultLimit")
    pivot_column_aliases: PivotColumnAliases | None = Field(
        default=None,
        alias="pivotColumnAliases",
    )

    def get_stack_dimensions(self) -> list[DimensionField]:
        """Return the new ordered column dimensions or the legacy single dimension."""
        if self.stack_dimensions:
            return self.stack_dimensions
        return [self.stack_dimension] if self.stack_dimension else []


class DataQueryResult(BaseModel):
    dimension_labels: dict[str, dict[str, str]] = Field(default_factory=dict, description="组织维度原值对应的展示名称")
    rollups: list[dict] = Field(default_factory=list, description="按文档重新去重的服务端合计, 非单元格相加")
    value: list[list] = Field(default_factory=list, description="metrics value list", examples=[[1], [2], [3]])
    dimensions: list[list] = Field(
        default_factory=list, description="metrics dimensions list", examples=[["flow_1"], ["flow_2"], ["flow_3"]]
    )
