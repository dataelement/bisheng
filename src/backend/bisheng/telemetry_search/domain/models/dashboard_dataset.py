from enum import Enum
from typing import Dict, Literal, List, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, VARCHAR, BOOLEAN, JSON, INTEGER, CLOB, Integer
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, AggregationExpression

from bisheng.telemetry_search.domain.models.dashboard import DMJSON

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

    index: Optional[int] = None
    sum_field: Optional[str] = None

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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __tablename__ = 'dashboard_dataset'

    id: int = Field(default=None,sa_column=Column(Integer, primary_key=True, autoincrement=True), description='Primary Key')

    dataset_name: str = Field(sa_column=Column(VARCHAR(255), nullable=False), description='dataset Name')

    dataset_code: str = Field(sa_column=Column(VARCHAR(255), nullable=False, unique=True),
                              description='dataset Code')

    es_index_name: str = Field(sa_column=Column(VARCHAR(255), nullable=False), description='Elasticsearch Index Name')

    description: str = Field(default='', sa_column=Column(VARCHAR(1024), nullable=True), description='Description')

    is_commercial_only: bool = Field(default=False, sa_column=Column(INTEGER, nullable=False),
                                     description='Is Commercial Only Dataset')

    schema_config: Dict = Field(..., sa_column=Column(DMJSON, nullable=False),
                                description='Schema Configuration in JSON format')
