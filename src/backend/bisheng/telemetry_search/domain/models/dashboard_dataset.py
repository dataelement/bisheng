from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel
from sqlalchemy import BOOLEAN, VARCHAR, Column
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    AggsTypeEnum,
    FilterExpression,
)


class FormulaEnum(str, Enum):
    """
    Formula Enumeration
    """

    # Addition
    ADD = 'add'
    # subtraction
    SUBTRACT = 'subtract'
    # Multiplication
    MULTIPLY = 'multiply'
    # Division
    DIVIDE = 'divide'


class VirtualMetricCalculationEnum(str, Enum):
    """Virtual metric calculation strategies."""

    SHARE_OF_TOTAL = "share_of_total"


class MetricConfig(BaseModel):
    """
    Metric Configuration Model
    """
    field: str
    field_type: Literal['string', 'number', 'date'] = 'number'
    # Indicator Name
    name: str
    # Filter
    filter: Optional[FilterExpression] = None
    # Aggregation method
    aggregations: Optional[List[AggregationExpression]] = None

    formula: Optional[FormulaEnum] = None
    calculation: Optional[VirtualMetricCalculationEnum] = None
    default_number_format: Optional[Dict[str, Any]] = None

    index: Optional[int] = None
    sum_field: Optional[str] = None
    sum_type: AggsTypeEnum = AggsTypeEnum.CARDINALITY

    is_virtual: Optional[bool] = False


class DimensionConfig(BaseModel):
    """
    Dimension Configuration Model
    """

    # Dimension Name
    name: str
    # Data field
    field: str
    field_type: Literal['string', 'number', 'date'] = 'string'
    # Time Granularity (only iftypearedateexist at the time)
    time_granularitys: Optional[List[Literal['year', 'month', 'week', 'day', 'hour']]] = None


class SchemaConfig(BaseModel):
    """
    Schema Configuration Model
    """

    # List Metrics
    metrics: List[MetricConfig]
    # Dimension List
    dimensions: List[DimensionConfig]


class DashboardDataset(SQLModelSerializable, table=True):
    """
    Dashboard Dataset Model
    """

    __tablename__ = 'dashboard_dataset'

    id: int = Field(default=None, primary_key=True, description='Primary Key')

    dataset_name: str = Field(sa_column=Column(VARCHAR(255), nullable=False), description='dataset Name')

    dataset_code: str = Field(sa_column=Column(VARCHAR(255), nullable=False, unique=True),
                              description='dataset Code')

    es_index_name: str = Field(sa_column=Column(VARCHAR(255), nullable=False), description='Elasticsearch Index Name')

    description: str = Field(default='', sa_column=Column(VARCHAR(1024), nullable=True), description='Description')

    is_commercial_only: bool = Field(default=False, sa_column=Column(BOOLEAN, nullable=False),
                                     description='Is Commercial Only Dataset')

    schema_config: Dict = Field(..., sa_column=Column(JsonType, nullable=False),
                                description='Schema Configuration in JSON format')

    # F058: whether this dataset appears in the dashboard's dataset/component picker.
    # Historical rows written before this column existed default to True (visible).
    is_visible: bool = Field(default=True, sa_column=Column(BOOLEAN, nullable=False),
                             description='Whether this dataset is selectable in the dashboard UI')

    # F058: datasets sharing a non-null group_key are presented as one grouped entry
    # (multiple sub-panels) in the dataset picker instead of separate top-level entries.
    dataset_group: Optional[str] = Field(default=None, sa_column=Column(VARCHAR(64), nullable=True),
                                         description='Optional grouping key for the dataset picker UI')
