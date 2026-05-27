from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List, Literal

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
    field_id: str = Field(alias='fieldId')
    field_name: Optional[str] = Field(default="", alias='fieldName')
    display_name: Optional[str] = Field(default="", alias='displayName')
    sort: Optional[str] = Field(default=None, description="asc or desc")
    time_granularity: Optional[Literal['year', 'month', 'week', 'day', 'hour']] = Field(default=None,
                                                                                        alias='timeGranularity',
                                                                                        description="timeGranularity")


class MetricField(BaseModel):
    field_id: str = Field(alias='fieldId')
    field_name: Optional[str] = Field(default="", alias='fieldName')
    display_name: Optional[str] = Field(default="", alias='displayName')
    aggregation: Optional[AggregationType] = Field(default="", alias='aggregation', description="aggregation type")
    is_virtual: Optional[bool] = Field(default=False, alias='isVirtual')
    sort: Optional[str] = Field(default=None, description="asc or desc")
    numberFormat: Optional[Dict] = Field(default_factory=dict, alias='numberFormat')


class FilterCondition(BaseModel):
    id: Optional[str] = Field(default="", alias='id')
    field_id: str = Field(alias='fieldId')
    field_name: Optional[str] = Field(default="", alias='fieldName')
    filter_type: str = Field(alias='filterType')
    operator: OperatorType = Field(alias='operator')
    value: Any = Field(default=None, alias='value')


class FieldOrder(BaseModel):
    field_id: str = Field(alias='fieldId')
    field_type: str = Field(alias='fieldType',
                            description="dimension、stack_dimension、metric")  # 'dimension' or 'metric'


class TimeFilter(BaseModel):
    type: Optional[TimeRangeType] = Field(default=None, description="time range type")
    mode: TimeRangeMode = Field(default=None, description="time range mode")
    recent_days: Optional[int] = Field(default=None, alias='recentDays')
    start_date: Optional[int] = Field(default=None, alias='startDate', description="start timestamp(s)")
    end_date: Optional[int] = Field(default=None, alias='endDate', description="end timestamp(s)")

    def get_start_end_date(self) -> (Optional[int], Optional[int]):
        if self.mode == TimeRangeMode.DYNAMIC:
            end_date = datetime.now() - timedelta(days=1)
            end_date = int(datetime(year=end_date.year, month=end_date.month, day=end_date.day, hour=23, minute=59,
                                    second=59).timestamp() * 1000)
            start_date = int((datetime.now() - timedelta(days=self.recent_days)).timestamp() * 1000)
        else:
            if not self.start_date or not self.end_date:
                return None, None
            start_date = self.start_date * 1000
            end_date = self.end_date * 1000
        return start_date, end_date


class ResultLimit(BaseModel):
    limit_type: str = Field(alias='limitType', description="all or limited")
    limit: int = Field(default=0, alias='limit', description="number of results to limit")

    def get_limit_number(self) -> Optional[int]:
        if self.limit_type == 'limited':
            return self.limit
        return 0


class ComponentDataConfig(BaseModel):
    dimensions: List[DimensionField] = Field(default_factory=list, description="list of dimension fields")
    stack_dimension: Optional[DimensionField] = Field(default=None, alias="stackDimension",
                                                      description="list of stack dimension fields")
    metrics: List[MetricField] = Field(default_factory=list, description="list of metric fields")
    field_order: List[FieldOrder] = Field(default_factory=list, alias="fieldOrder", description="list of field order")
    filters: List[FilterCondition] = Field(default_factory=list, description="list of filter conditions")
    filters_logic: Optional[str] = Field(default=LogicType.AND, alias='filtersLogic', description="logic for filters")
    time_filter: Optional[TimeFilter] = Field(default=None, alias='timeFilter')
    result_limit: Optional[ResultLimit] = Field(default=None, alias='resultLimit')


class DataQueryResult(BaseModel):
    value: List[List] = Field(default_factory=list, description="metrics value list", examples=[[1], [2], [3]])
    dimensions: List[List] = Field(default_factory=list, description="metrics dimensions list",
                                   examples=[["flow_1"], ["flow_2"], ["flow_3"]])
