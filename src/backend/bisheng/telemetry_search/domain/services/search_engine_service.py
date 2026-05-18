import json
from datetime import datetime
from typing import List, Optional, Any, Dict, Set

from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator

from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    FilterExpression,
    AggsTypeEnum,
    TermOp, PipelineTypeEnum
)


class Constants:
    """Constants for Elasticsearch query building"""
    DEFAULT_SIZE = 10000
    MAX_SIZE = 65535
    DEFAULT_TERMS_SIZE = 65535
    MIN_SIZE = 0

    AGGREGATION_KEY = "aggregations"
    BUCKETS_KEY = "buckets"
    VALUE_KEY = "value"
    KEY_FIELD = "key"
    PATH_SEPARATOR = ">"

    DIMENSION_PREFIX = "dimension_"
    METRIC_PREFIX = "metric_"
    SUB_DIM_PREFIX = "sub_dim_"
    STACK_DIM_KEY = "stack_dimension"
    NESTED_WRAPPER_PREFIX = "__nested_wrapper_"
    REVERSE_NESTED_PREFIX = "__reverse_nested_wrapper_"


class AggregationLevel:
    """Represents a single aggregation level in the hierarchy"""

    def __init__(
            self,
            key: str,
            config: AggregationExpression,
            agg_type: str = "normal",
            original_index: int = 0
    ):
        self.key = key
        self.config = config
        self.type = agg_type
        self.original_index = original_index
        self.nested_path = self._extract_nested_path(config.field)

    @staticmethod
    def _extract_nested_path(field: Optional[str]) -> Optional[str]:
        """Extract nested path from field (e.g., 'users.name' -> 'users')"""
        if field and "." in field:
            return field.split(".")[0]
        return None

    def is_date_histogram(self) -> bool:
        return self.config.type == AggsTypeEnum.DATE_HISTOGRAM

    def is_stack_dimension(self) -> bool:
        return self.type == "stack"

    def is_nested(self) -> bool:
        return self.nested_path is not None


class SearchParameters(BaseModel):
    """Search parameters for Elasticsearch aggregation queries"""

    index_name: Optional[str] = Field(description="Elasticsearch index name")
    metrics: List[AggregationExpression] = Field(description="Metric aggregations")
    dimensions: List[AggregationExpression] = Field(description="Dimension aggregations")
    stack_dimension: Optional[AggregationExpression] = Field(
        default=None,
        description="Stack dimension for chart stacking"
    )
    filters: Optional[List[FilterExpression]] = Field(
        default=None,
        description="Query filters"
    )
    size: Optional[int] = Field(
        default=Constants.DEFAULT_SIZE,
        ge=Constants.MIN_SIZE,
        le=Constants.MAX_SIZE,
        description="Result size limit"
    )

    @field_validator('metrics')
    @classmethod
    def validate_metrics(cls, v):
        if not v:
            raise ValueError("At least one metric is required")
        return v

    @staticmethod
    def _collect_metric_names(metrics: List[AggregationExpression]) -> Set[str]:
        """Recursively collect all metric names including nested ones"""
        names = set()
        for metric in metrics:
            if metric.name:
                names.add(metric.name)
            if metric.aggs:
                names.update(SearchParameters._collect_metric_names(metric.aggs))
        return names

    @model_validator(mode='after')
    def validate_pipeline_references(self):
        """Ensure pipeline aggregations reference valid metrics"""
        metric_names = self._collect_metric_names(self.metrics)

        for metric in self.metrics:
            if not metric.is_pipeline_aggregation():
                continue

            if not metric.field:
                raise ValueError(
                    f"Pipeline aggregation '{metric.name}' missing field reference"
                )

            self._validate_metric_path(metric.field, metric_names, metric.name)

        return self

    @staticmethod
    def _validate_metric_path(path: str, available_names: Set[str], metric_name: str):
        """Validate that all parts of a metric path exist"""
        parts = path.split(Constants.PATH_SEPARATOR)
        for part in parts:
            if part not in available_names:
                raise ValueError(
                    f"Pipeline aggregation '{metric_name}' references "
                    f"non-existent metric '{part}' in path '{path}'"
                )


class NestedPathManager:
    """Manages nested/reverse_nested wrapper generation"""

    def __init__(self):
        self._counter = 0

    def create_nested_wrapper(self, path: str) -> tuple[str, dict]:
        """Create a nested aggregation wrapper"""
        self._counter += 1
        key = f"{Constants.NESTED_WRAPPER_PREFIX}{self._counter}_{path}"
        config = {
            "nested": {"path": path},
            "aggs": {}
        }
        return key, config

    def create_reverse_nested_wrapper(self) -> tuple[str, dict]:
        """Create a reverse_nested aggregation wrapper"""
        self._counter += 1
        key = f"{Constants.REVERSE_NESTED_PREFIX}{self._counter}"
        config = {
            "reverse_nested": {},
            "aggs": {}
        }
        return key, config


class ResultParser:
    """Parses Elasticsearch aggregation results into 2D arrays"""

    def __init__(self, parameters: SearchParameters):
        self.parameters = parameters
        self.has_stack = parameters.stack_dimension is not None
        self.num_dims = len(parameters.dimensions) + (1 if self.has_stack else 0)
        self.num_metrics = len(parameters.metrics)

    @property
    def stack_dim_index(self) -> Optional[int]:
        if not self.has_stack:
            return None
        return len(self.parameters.dimensions)

    def parse_to_2d_array(self, es_response: dict) -> List[List[Any]]:
        """Parse ES response to 2D array format"""
        aggregations = self._extract_aggregations(es_response)
        if not aggregations:
            return []

        rows = []
        metric_keys = [f"{Constants.METRIC_PREFIX}{i}" for i in range(self.num_metrics)]
        self._traverse_buckets(aggregations, {}, rows, metric_keys)
        return rows

    def _extract_aggregations(self, es_response: dict) -> dict:
        """Extract aggregations from ES response"""
        if Constants.AGGREGATION_KEY in es_response:
            return es_response[Constants.AGGREGATION_KEY]

        if any(k.startswith(Constants.DIMENSION_PREFIX) for k in es_response.keys()):
            return es_response

        return {}

    def _traverse_buckets(
            self,
            current_aggs: dict,
            current_row_dict: Dict[int, Any],
            rows: List[List[Any]],
            metric_keys: List[str]
    ) -> None:
        """Recursively traverse aggregation buckets"""

        # Check for nested/reverse_nested wrapper
        wrapper_key = self._find_wrapper_key(current_aggs)
        if wrapper_key:
            self._traverse_buckets(
                current_aggs[wrapper_key],
                current_row_dict,
                rows,
                metric_keys
            )
            return

        # Process dimension level
        dimension_key = self._find_dimension_key(current_aggs)
        if dimension_key:
            self._process_dimension_level(
                dimension_key,
                current_aggs,
                current_row_dict,
                rows,
                metric_keys
            )
            return

        # Process stack dimension
        if Constants.STACK_DIM_KEY in current_aggs:
            self._process_stack_dimension(
                current_aggs,
                current_row_dict,
                rows,
                metric_keys
            )
            return

        # Reached metric level, build result row
        self._build_result_row(current_aggs, current_row_dict, rows, metric_keys)

    def _find_wrapper_key(self, aggs: dict) -> Optional[str]:
        """Find nested/reverse_nested wrapper key if present"""
        for key in aggs:
            if (key.startswith(Constants.NESTED_WRAPPER_PREFIX) or
                    key.startswith(Constants.REVERSE_NESTED_PREFIX)):
                return key
        return None

    def _find_dimension_key(self, aggs: dict) -> Optional[str]:
        """Find dimension key in current aggregation level"""
        for key in aggs:
            if key.startswith(Constants.DIMENSION_PREFIX):
                return key
        return None

    def _process_dimension_level(
            self,
            dimension_key: str,
            current_aggs: dict,
            current_row_dict: Dict[int, Any],
            rows: List[List[Any]],
            metric_keys: List[str]
    ) -> None:
        """Process a dimension level and recurse into buckets"""
        try:
            dim_index = int(dimension_key.split("_")[1])
        except (IndexError, ValueError):
            return

        buckets = current_aggs[dimension_key].get(Constants.BUCKETS_KEY, [])
        if not isinstance(buckets, list):
            return

        for bucket in buckets:
            new_row_dict = current_row_dict.copy()
            new_row_dict[dim_index] = bucket.get(Constants.KEY_FIELD)
            self._traverse_buckets(bucket, new_row_dict, rows, metric_keys)

    def _process_stack_dimension(
            self,
            current_aggs: dict,
            current_row_dict: Dict[int, Any],
            rows: List[List[Any]],
            metric_keys: List[str]
    ) -> None:
        """Process stack dimension level"""
        buckets = current_aggs[Constants.STACK_DIM_KEY].get(Constants.BUCKETS_KEY, [])
        for bucket in buckets:
            new_row_dict = current_row_dict.copy()
            new_row_dict[self.stack_dim_index] = bucket.get(Constants.KEY_FIELD)
            self._traverse_buckets(bucket, new_row_dict, rows, metric_keys)

    def _build_result_row(
            self,
            current_aggs: dict,
            current_row_dict: Dict[int, Any],
            rows: List[List[Any]],
            metric_keys: List[str]
    ) -> None:
        """Build a result row from dimension values and metrics"""
        row = [None] * self.num_dims

        for dim_idx, val in current_row_dict.items():
            if dim_idx < self.num_dims:
                row[dim_idx] = val

        for metric_key in metric_keys:
            metric_value = self._extract_metric_value(current_aggs.get(metric_key))
            row.append(metric_value)

        rows.append(row)

    @staticmethod
    def _extract_metric_value(metric_data: Any) -> float:
        """Extract numeric value from metric aggregation result"""
        if isinstance(metric_data, dict):
            return metric_data.get(Constants.VALUE_KEY, 0)
        elif isinstance(metric_data, (int, float)):
            return metric_data
        return 0


class QueryBuilder:
    """Builds Elasticsearch query DSL from search parameters"""

    def __init__(self, parameters: SearchParameters):
        self.parameters = parameters
        self._metric_name_to_key: Dict[str, str] = {}
        self._nested_manager = NestedPathManager()

    def build_query_dsl(self) -> dict:
        """Build complete query DSL"""
        try:
            return {
                "size": 0,
                "query": self._build_bool_query(),
                "aggs": self._build_aggregations()
            }
        except Exception as e:
            raise ValueError(f"Failed to build search query: {str(e)}") from e

    def _build_bool_query(self) -> dict:
        """Build bool query from filters"""
        if not self.parameters.filters:
            return {"match_all": {}}

        bool_query: Dict[str, List] = {}

        for filter_expr in self.parameters.filters:
            try:
                expr_dsl = filter_expr.to_dsl()
                for operator, conditions in expr_dsl.items():
                    if operator not in bool_query:
                        bool_query[operator] = []
                    bool_query[operator].extend(conditions)
            except Exception:
                continue

        return {"bool": bool_query} if bool_query else {"match_all": {}}

    def _build_aggregations(self) -> dict:
        """Build aggregations section"""
        self._build_metric_name_mapping()

        agg_levels = self._prepare_aggregation_levels()
        agg_levels = self._reorder_for_pipeline(agg_levels)
        agg_levels = self._reorder_for_nested(agg_levels)

        aggs = {}
        innermost_level = self._build_nested_dimensions(aggs, agg_levels, None)
        self._add_metric_aggregations(innermost_level, self.parameters.metrics)

        return aggs

    def _prepare_aggregation_levels(self) -> List[AggregationLevel]:
        """Prepare aggregation levels with original indices"""
        levels = []

        for idx, dim in enumerate(self.parameters.dimensions):
            key = f"{Constants.DIMENSION_PREFIX}{idx}"
            levels.append(AggregationLevel(key, dim, "normal", idx))

        if self.parameters.stack_dimension:
            levels.append(
                AggregationLevel(
                    Constants.STACK_DIM_KEY,
                    self.parameters.stack_dimension,
                    "stack",
                    len(self.parameters.dimensions)
                )
            )

        return levels

    def _reorder_for_nested(
            self,
            levels: List[AggregationLevel]
    ) -> List[AggregationLevel]:
        """Group dimensions by nested path to minimize context switches"""
        if not levels:
            return []

        reordered = []
        processed = set()

        for i, current in enumerate(levels):
            if i in processed:
                continue

            reordered.append(current)
            processed.add(i)

            if current.is_nested():
                target_path = current.nested_path
                for j in range(i + 1, len(levels)):
                    if j not in processed:
                        candidate = levels[j]
                        if (candidate.is_nested() and
                                candidate.nested_path == target_path):
                            reordered.append(candidate)
                            processed.add(j)

        return reordered

    def _reorder_for_pipeline(
            self,
            levels: List[AggregationLevel]
    ) -> List[AggregationLevel]:
        """Move date histogram to innermost level for pipeline aggregations"""
        if not self._has_histogram_dependent_pipeline():
            return levels

        for idx, level in enumerate(levels):
            if level.is_date_histogram():
                date_dim = levels.pop(idx)
                levels.append(date_dim)
                break

        return levels

    def _has_histogram_dependent_pipeline(self) -> bool:
        """Check if any metric requires histogram parent"""

        def check_metrics(metrics: List[AggregationExpression]) -> bool:
            for metric in metrics:
                if metric.requires_histogram_parent():
                    return True
                if metric.aggs and check_metrics(metric.aggs):
                    return True
            return False

        return check_metrics(self.parameters.metrics)

    def _build_nested_dimensions(
            self,
            current_root: dict,
            levels: List[AggregationLevel],
            current_path: Optional[str]
    ) -> dict:
        """Recursively build dimension chain with automatic nested wrapping"""

        if not levels:
            # Base case: no more levels to process
            if current_path is not None:
                wrapper_key, wrapper_config = self._nested_manager.create_reverse_nested_wrapper()
                current_root[wrapper_key] = wrapper_config
                return current_root[wrapper_key]["aggs"]

            return current_root

        head = levels[0]
        target_path = head.nested_path

        # Current level matches target nested path
        if target_path == current_path:
            agg_config = self._build_dimension_config(head.config)
            current_root[head.key] = {
                head.config.type.value: agg_config,
                "aggs": {}
            }

            return self._build_nested_dimensions(
                current_root[head.key]["aggs"],
                levels[1:],
                current_path
            )

        # Need to switch nested context
        if target_path is not None and current_path is None:
            wrapper_key, wrapper_config = self._nested_manager.create_nested_wrapper(
                target_path
            )
            current_root[wrapper_key] = wrapper_config

            return self._build_nested_dimensions(
                current_root[wrapper_key]["aggs"],
                levels,
                target_path
            )

        # Switching from one nested path to another
        if target_path is None and current_path is not None:
            wrapper_key, wrapper_config = self._nested_manager.create_reverse_nested_wrapper()
            current_root[wrapper_key] = wrapper_config

            return self._build_nested_dimensions(
                current_root[wrapper_key]["aggs"],
                levels,
                None
            )

        # Switching between different nested paths
        if (target_path is not None and
                current_path is not None and
                target_path != current_path):
            wrapper_key, wrapper_config = self._nested_manager.create_reverse_nested_wrapper()
            current_root[wrapper_key] = wrapper_config

            return self._build_nested_dimensions(
                current_root[wrapper_key]["aggs"],
                levels,
                None
            )

        return current_root

    def _build_dimension_config(self, dimension: AggregationExpression) -> dict:
        """Build dimension aggregation configuration"""
        config = {"field": dimension.field}

        if dimension.custom_params:
            config.update(dimension.custom_params)

        if dimension.type == AggsTypeEnum.TERMS and "size" not in config:
            config["size"] = Constants.DEFAULT_TERMS_SIZE

        return config

    def _build_metric_name_mapping(
            self,
            metrics: Optional[List[AggregationExpression]] = None,
            parent_key: str = ""
    ) -> None:
        """Recursively build metric name to key mapping for pipeline refs"""
        if metrics is None:
            self._metric_name_to_key.clear()
            metrics = self.parameters.metrics

        for idx, metric in enumerate(metrics):
            key = f"{parent_key}_{idx}" if parent_key else f"{Constants.METRIC_PREFIX}{idx}"

            if metric.name:
                self._metric_name_to_key[metric.name] = key

            if metric.aggs:
                self._build_metric_name_mapping(metric.aggs, key)

    def _add_metric_aggregations(
            self,
            current_level: dict,
            metrics: List[AggregationExpression],
            parent_key: str = ""
    ) -> None:
        """Recursively add metric aggregations"""
        for idx, metric in enumerate(metrics):
            agg_key = (f"{parent_key}_{idx}" if parent_key
                       else f"{Constants.METRIC_PREFIX}{idx}")

            agg_config = self._build_metric_config(metric)
            current_level[agg_key] = {
                metric.type.value: agg_config
            }

            if metric.aggs:
                current_level[agg_key]["aggs"] = {}
                self._add_metric_aggregations(
                    current_level[agg_key]["aggs"],
                    metric.aggs,
                    agg_key
                )

    def _build_metric_config(self, metric: AggregationExpression) -> dict:
        """Build metric aggregation configuration"""
        config = {}

        if metric.is_pipeline_aggregation():
            buckets_path = self._convert_name_path_to_key_path(metric.field)
            config["buckets_path"] = buckets_path
        else:
            config["field"] = metric.field

        if metric.custom_params:
            config.update(metric.custom_params)

        return config

    def _convert_name_path_to_key_path(self, name_path: str) -> str:
        """Convert metric name path to key path for buckets_path"""
        if not name_path:
            return ""

        if Constants.PATH_SEPARATOR not in name_path:
            return self._metric_name_to_key.get(name_path, name_path)

        parts = name_path.split(Constants.PATH_SEPARATOR)
        key_parts = [self._metric_name_to_key.get(part, part) for part in parts]

        return Constants.PATH_SEPARATOR.join(key_parts)


class SearchEngineService:
    """Elasticsearch query service for aggregation searches"""

    def __init__(self, parameters: SearchParameters):
        self.parameters = parameters
        self.query_builder = QueryBuilder(parameters)
        self.result_parser = ResultParser(parameters)

    async def search(self) -> List[List[Any]]:
        """Execute search and return parsed results"""
        try:
            query_dsl = self.query_builder.build_query_dsl()
            logger.debug(f"query_dsl: {json.dumps(query_dsl, indent=2)}")

            es_client = await get_es_connection()
            response = await es_client.search(
                index=self.parameters.index_name,
                body=query_dsl,
                filter_path=Constants.AGGREGATION_KEY
            )

            return self.result_parser.parse_to_2d_array(response)

        except Exception as e:
            raise RuntimeError(f"Search execution failed: {str(e)}") from e

    def build_search_query(self) -> dict:
        """Build query DSL for debugging"""
        return self.query_builder.build_query_dsl()

    def get_query_summary(self) -> str:
        """Get human-readable query summary"""
        parts = [
            f"Index: {self.parameters.index_name or 'N/A'}",
            f"Metrics: {len(self.parameters.metrics)}",
            f"Dimensions: {len(self.parameters.dimensions)}",
        ]

        if self.parameters.stack_dimension:
            parts.append("Stack Dimension: Yes")

        if self.parameters.filters:
            parts.append(f"Filters: {len(self.parameters.filters)}")

        return " | ".join(parts)


async def run_example():
    """Example usage"""
    parameters = SearchParameters(
        index_name="mid_app_increment",
        metrics=[
            AggregationExpression(
                name="app_count",
                type=AggsTypeEnum.CARDINALITY,
                field="app_id"
            ),
            AggregationExpression(
                name="total_app_count",
                type=PipelineTypeEnum.CUMULATIVE_SUM,
                field="app_count"
            )
        ],
        dimensions=[
            AggregationExpression(
                name="月",
                type=AggsTypeEnum.DATE_HISTOGRAM,
                field="timestamp",
                time_interval="month"
            )
        ],
        stack_dimension=AggregationExpression(
            name="应用类型",
            type=AggsTypeEnum.TERMS,
            field="app_type"
        )
    )

    service = SearchEngineService(parameters)
    rows = await service.search()
    for row in rows:
        row[0] = datetime.fromtimestamp(row[0] / 1000).strftime('%Y-%m')

    print(rows)


if __name__ == '__main__':
    import asyncio

    asyncio.run(run_example())
