from enum import Enum
from typing import Optional, Any, Literal, Union, List

from pydantic import BaseModel, field_validator, Field, model_validator

TIME_INTERVALS_MAP = {
    'year': '1y',
    'month': '1M',
    'week': '1w',
    'day': '1d',
    'hour': '1h'
}


# ==================== enum definition ====================
class AggsTypeEnum(str, Enum):
    """Standard Aggregation Type"""
    TERMS = "terms"
    DATE_HISTOGRAM = "date_histogram"
    AVG = "avg"
    SUM = "sum"
    MAX = "max"
    MIN = "min"
    CARDINALITY = "cardinality"
    VALUE_COUNT = "value_count"


class PipelineTypeEnum(str, Enum):
    """Pipeline aggregation type (dependent on other aggregation results)"""
    DERIVATIVE = "derivative"
    MOVING_AVG = "moving_avg"
    CUMULATIVE_SUM = "cumulative_sum"
    MAX_BUCKET = "max_bucket"
    MIN_BUCKET = "min_bucket"
    AVG_BUCKET = "avg_bucket"


# ==================== Value Object ====================
class RangeValue(BaseModel):
    """Range Query Value Object"""
    gte: Optional[Any] = None
    lte: Optional[Any] = None
    gt: Optional[Any] = None
    lt: Optional[Any] = None

    @model_validator(mode='after')
    def validate_at_least_one_bound(self):
        """At least one boundary value is required"""
        if not any([self.gte, self.lte, self.gt, self.lt]):
            raise ValueError("Range query must have at least one bound (gte, lte, gt, or lt)")
        return self


# ==================== Filter Operators ====================
class BaseOp(BaseModel):
    """Filter operation base class"""
    operator: str
    field: str
    value: Optional[Any] = None

    def to_dsl(self) -> dict:
        raise NotImplementedError("Subclasses must implement to_dsl()")


class TermOp(BaseOp):
    """Exact Match Operator"""
    operator: Literal['term'] = 'term'
    value: Any

    def to_dsl(self) -> dict:
        # nested field handling
        if "." in self.field:
            # Nested Field Handling
            path = self.field.rsplit('.', 1)[0]

            return {
                "nested": {
                    "path": path,
                    "query": {"term": {self.field: self.value}}
                }
            }

        # Regular field handling
        return {"term": {self.field: self.value}}


class TermsOp(BaseOp):
    """Multi-value match operator (IN Inquiry"""
    operator: Literal['terms'] = 'terms'
    value: List[Any]

    @field_validator('value')
    @classmethod
    def validate_non_empty_list(cls, v):
        if not v:
            raise ValueError("Terms operator requires at least one value")
        return v

    def to_dsl(self) -> dict:
        # nested field handling
        if "." in self.field:
            # Nested Field Handling
            path = self.field.rsplit('.', 1)[0]

            return {
                "nested": {
                    "path": path,
                    "query": {"terms": {self.field: self.value}}
                }
            }

        return {"terms": {self.field: self.value}}


class RangeOp(BaseOp):
    """Range Query Operator"""
    operator: Literal['range'] = 'range'
    value: RangeValue

    def to_dsl(self) -> dict:
        # nested field handling
        if "." in self.field:
            # Nested Field Handling
            path = self.field.rsplit('.', 1)[0]

            return {
                "nested": {
                    "path": path,
                    "query": {"range": {self.field: self.value.model_dump(exclude_none=True)}}
                }
            }

        return {"range": {self.field: self.value.model_dump(exclude_none=True)}}


class MatchAllOp(BaseOp):
    """Match all documents"""
    operator: Literal['match_all'] = 'match_all'
    field: str = ""  # match_all Not Required field, but in order to inherit the uniformity reservation

    def to_dsl(self) -> dict:
        return {"match_all": {}}


class MatchPhraseOp(BaseOp):
    """Phrase Match Operator"""
    operator: Literal['match_phrase'] = 'match_phrase'
    value: str

    def to_dsl(self) -> dict:
        # nested field handling
        if "." in self.field:
            # Nested Field Handling
            path = self.field.rsplit('.', 1)[0]

            return {
                "nested": {
                    "path": path,
                    "query": {"match_phrase": {f"{self.field}.text": self.value}}
                }
            }
        return {"match_phrase": {f"{self.field}.text": self.value}}


AtomFilter = Union[TermOp, TermsOp, RangeOp, MatchAllOp, MatchPhraseOp]


# ==================== Filter expression ====================
class FilterExpression(BaseModel):
    """
    Boolean query expression, support nesting
    Map Elasticsearch right of privacy Bool Query
    """
    bool_operator: Literal['must', 'should', 'must_not', 'filter'] = Field(
        description="Boolean logical operator"
    )
    filters: List[Union[AtomFilter, 'FilterExpression']] = Field(
        description="Filter the list of criteria, support nesting"
    )

    @field_validator('filters', mode="before")
    @classmethod
    def validate_non_empty_filters(cls, v):
        if not v:
            raise ValueError("FilterExpression must have at least one filter")
        return v

    def to_dsl(self) -> dict:
        """Convert To Elasticsearch DSL"""
        dsl_list = []
        for item in self.filters:
            if isinstance(item, FilterExpression):
                # Nidificato FilterExpression
                dsl_list.append({"bool": item.to_dsl()})
            else:
                # Atomic Operator
                dsl_list.append(item.to_dsl())

        return {self.bool_operator: dsl_list}


# ==================== Aggregate Expression ====================
class AggregationExpression(BaseModel):
    """
    Aggregate expressions, support nesting
    """
    name: str = Field(default=None,
                      description="Aggregate Name for Result Recognition and Pipeline Aggregate Reference")
    type: Union[AggsTypeEnum, PipelineTypeEnum] = Field(description="Aggregation Type")
    field: str = Field(
        description="Field Name (Normal Aggregation) or Referenced Aggregation Name (Pipeline Aggregation)")
    custom_params: Optional[dict] = Field(default=None, description="Custom Parameters")
    time_interval: Optional[Literal['year', 'month', 'week', 'day', 'hour']] = Field(
        default=None, description="Time interval, only if type are date_histogram Used at"
    )
    aggs: Optional[List["AggregationExpression"]] = Field(default=None, description="Nested Sub-Aggregation")

    @model_validator(mode='after')
    def validate_date_histogram_params(self):
        if self.type == AggsTypeEnum.DATE_HISTOGRAM:
            if self.custom_params is None:
                self.custom_params = {}
            if self.time_interval:
                if 'calendar_interval' in self.custom_params:
                    self.custom_params['calendar_interval'] = TIME_INTERVALS_MAP[self.time_interval]
                elif 'fixed_interval' in self.custom_params:
                    self.custom_params['fixed_interval'] = TIME_INTERVALS_MAP[self.time_interval]
                else:
                    self.custom_params['calendar_interval'] = TIME_INTERVALS_MAP[self.time_interval]

        return self

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Aggregation name cannot be empty")
        return v.strip()

    def is_pipeline_aggregation(self) -> bool:
        """Determine if it is pipeline aggregation"""
        return isinstance(self.type, PipelineTypeEnum) or \
            self.type.value in [e.value for e in PipelineTypeEnum]

    def requires_histogram_parent(self) -> bool:
        """Check if needed histogram Parent of type"""
        histogram_required = [
            PipelineTypeEnum.CUMULATIVE_SUM,
            PipelineTypeEnum.DERIVATIVE
        ]
        return self.type in histogram_required


if __name__ == '__main__':
    query = [
        FilterExpression(
            bool_operator='must',
            filters=[
                TermOp(field='status', value='active'),
                RangeOp(field='age', value=RangeValue(gte=18, lt=30)),
                FilterExpression(
                    bool_operator='should',
                    filters=[
                        TermsOp(field='tags', value=['python', 'developer']),
                        TermOp(field='role', value='admin')
                    ]
                )
            ]
        ),
        FilterExpression(
            bool_operator='should',
            filters=[
                TermOp(field='country', value='US'),
                TermOp(field='country', value='UK')
            ]
        ),
        FilterExpression(
            bool_operator='must_not',
            filters=[
                TermOp(field='banned', value=True)
            ]
        )
    ]

    import json

    for q in query:
        print(json.dumps(q.to_dsl(), indent=2))
