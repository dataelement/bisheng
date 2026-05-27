import copy
from datetime import datetime, timedelta
from typing import List, Dict, Any, Union, Literal

from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.errcode.telemetry import QueryDatasetNotFoundError, QueryMetricNotFoundError, \
    QueryAggregationNotFoundError, QueryDimensionNotFoundError, QueryOperatorNotFoundError
from bisheng.core.database import get_async_db_session
from .search_engine_service import SearchParameters, SearchEngineService
from ..models.dashboard_dataset import SchemaConfig, MetricConfig, DimensionConfig, FormulaEnum
from ..repositories.implementations.dataset_repository_impl import DashboardDatasetRepositoryImpl
from ..schemas.component import ComponentDataConfig, TimeFilter, DataQueryResult, AggregationType, \
    DimensionField, LogicType, OperatorType
from ..schemas.query_builder import AggregationExpression, AggsTypeEnum, FilterExpression, AtomFilter, TermOp, RangeOp, \
    RangeValue, MatchPhraseOp, TermsOp

TIMESTAMP_FIELD = "timestamp"


class DataQueryService(BaseModel):
    dataset_code: str = Field(description="dataset code")
    data_config: ComponentDataConfig = Field(description="component data configuration")
    time_filters: List[TimeFilter] | None = Field(default=None, description="time filters")

    async def query_telemetry_data(self) -> DataQueryResult:
        res = DataQueryResult()
        if not self.data_config.metrics:
            return res

        # find dataset config
        async with get_async_db_session() as session:
            repository = DashboardDatasetRepositoryImpl(session)
            dataset_config = await repository.find_one(dataset_code=self.dataset_code)
        if not dataset_config:
            raise QueryDatasetNotFoundError()

        schema_config = SchemaConfig(**dataset_config.schema_config)
        metric_map = {one.field: one for one in schema_config.metrics}
        dimension_map = {one.field: one for one in schema_config.dimensions}

        query_dimensions = await self.convert_dimensions(self.data_config.dimensions, dimension_map)

        if self.data_config.stack_dimension:
            stack_dimensions = await self.convert_dimensions([self.data_config.stack_dimension], dimension_map)
            stack_dimension = stack_dimensions[0] if stack_dimensions else None
        else:
            stack_dimension = None

        query_filters, time_range = await self.convert_filters(dimension_map, metric_map)
        # empty time_range means no time filter applied
        if time_range is None:
            # time filter not find intersection, dont`t need query data
            return res

        timestamp_dimension_index = -1
        timestamp_dimension = None
        dimension_index = -1
        if query_dimensions:
            for dimension in query_dimensions:
                dimension_index += 1
                if dimension.field == TIMESTAMP_FIELD:
                    timestamp_dimension_index = dimension_index
                    timestamp_dimension = dimension
        if stack_dimension:
            dimension_index += 1
            if stack_dimension.field == TIMESTAMP_FIELD:
                timestamp_dimension_index = dimension_index
                timestamp_dimension = stack_dimension

        query_result = await self.query_all_metrics(metric_map, dimension_index,
                                                    index_name=dataset_config.es_index_name,
                                                    dimensions=query_dimensions,
                                                    stack_dimension=stack_dimension,
                                                    filters=query_filters if query_filters else None)

        res.dimensions, res.value = await self.sort_metrics(dimension_index, query_result, timestamp_dimension_index,
                                                            timestamp_dimension, time_range)
        return res

    async def query_all_metrics(self, metric_map: Dict[str, MetricConfig], dimension_index: int, index_name: str,
                                dimensions: List[AggregationExpression], stack_dimension: AggregationExpression,
                                filters: List[FilterExpression]) -> List[List]:
        all_dimensions = {}
        res = []
        for metric_index, metric in enumerate(self.data_config.metrics):
            metric_config = metric_map.get(metric.field_id)
            if not metric_config:
                raise QueryMetricNotFoundError()
            # metric filters、dimensions、stack_dimension、index_name copy from search_kwargs
            one_metric_result = await self.query_one_metric(metric_config, metric.aggregation, dimension_index,
                                                            index_name=index_name,
                                                            dimensions=copy.deepcopy(dimensions),
                                                            stack_dimension=copy.deepcopy(stack_dimension),
                                                            filters=copy.deepcopy(filters) if filters else None)
            # complete all dimensions
            if dimension_index >= 0:
                for one in one_metric_result:
                    one_dimension = one[:dimension_index + 1]
                    key = tuple(one_dimension)
                    if key not in all_dimensions:
                        all_dimensions[key] = [0] * len(self.data_config.metrics)
                    all_dimensions[key][metric_index] = one[dimension_index + 1]
            else:
                for one_index, one in enumerate(one_metric_result):
                    if len(res) <= one_index:
                        res.append([])
                    res[one_index].append(one[0])
        if dimension_index >= 0:
            for one, values in all_dimensions.items():
                one_dimension = list(one)
                one_dimension.extend(values)
                res.append(one_dimension)
        return res

    @staticmethod
    def merge_filters(filters: List[FilterExpression] | None, new_filter: FilterExpression) -> List[FilterExpression]:
        if not new_filter:
            return filters
        if filters is None:
            return [new_filter]
        filters = copy.deepcopy(filters)
        filters.append(new_filter)
        return filters

    async def query_one_metric(self, metric_config: MetricConfig, aggregation: AggregationType,
                               dimension_index: int, **search_kwargs) -> List[List]:
        if metric_config.is_virtual:
            # need query twice from telemetry mid table
            if metric_config.formula is not None:
                return await self.query_formula_metric(metric_config, dimension_index, **search_kwargs)
            elif metric_config.sum_field is not None:
                return await self.query_sum_metric(metric_config, dimension_index, **search_kwargs)
            # need find finally value from query_result by index
            elif metric_config.index is not None:
                return await self.query_index_metric(metric_config, dimension_index, **search_kwargs)
            else:
                filters = search_kwargs.pop('filters', None)
                filters = self.merge_filters(filters, metric_config.filter)
                search_params = SearchParameters(
                    metrics=metric_config.aggregations,
                    filters=filters,
                    **search_kwargs
                )
                return await SearchEngineService(search_params).search()

        agg_type = self.convert_metric_aggregation(aggregation)
        filters = search_kwargs.pop('filters', None)
        filters = self.merge_filters(filters, metric_config.filter)
        # search data from telemetry mid table
        search_params = SearchParameters(
            metrics=[AggregationExpression(name=metric_config.field, field=metric_config.field, type=agg_type)],
            filters=filters,
            **search_kwargs
        )
        # eg. [[dim1, dim2, metric1, metric2], [...]]
        return await SearchEngineService(search_params).search()

    async def query_formula_metric(self, metric_config: MetricConfig, dimension_index: int, **search_kwargs) \
            -> List[List]:
        filters = search_kwargs.pop('filters', None)

        # merge filters
        first_filters = copy.deepcopy(filters)
        second_filters = copy.deepcopy(filters)
        if metric_config.filter is not None:
            first_filters = self.merge_filters(first_filters,
                                               FilterExpression(bool_operator="must",
                                                                filters=metric_config.filter.filters[:1]))
            second_filters = self.merge_filters(second_filters,
                                                FilterExpression(bool_operator="must",
                                                                 filters=metric_config.filter.filters[1:]))

        # query first value
        search_params = SearchParameters(
            metrics=metric_config.aggregations[0:1],
            filters=first_filters,
            **search_kwargs
        )
        # query result eg. [[dim1, dim2, metric1, metric2], [...]]
        first_result = await SearchEngineService(search_params).search()

        # query second value
        search_params = SearchParameters(
            metrics=metric_config.aggregations[1:],
            filters=second_filters,
            **search_kwargs
        )
        # query result eg. [[dim1, dim2, metric1, metric2], [...]]
        second_result = await SearchEngineService(search_params).search()

        res = []
        # need merge dimensions
        if dimension_index >= 0:
            all_dimensions = {}
            for one in first_result:
                one_dimension = one[:dimension_index + 1]
                all_dimensions[tuple(one_dimension)] = one[dimension_index + 1]
            for one in second_result:
                one_dimension = one[:dimension_index + 1]
                first_value = all_dimensions.pop(tuple(one_dimension), 0)
                one_dimension.append(
                    self.calc_formula_value(metric_config.formula, first_value, one[dimension_index + 1]))
                res.append(one_dimension)
            for one, value in all_dimensions.items():
                one_dimension = list(one[0])
                one_dimension.append(self.calc_formula_value(metric_config.formula, value, 0))
                res.append(one_dimension)
        else:
            for index, one in enumerate(first_result):
                res.append([
                    self.calc_formula_value(metric_config.formula, one[0], second_result[index][0])
                ])
        return res

    @staticmethod
    def calc_formula_value(formula: FormulaEnum, first_value: int, second_value) -> float:
        if formula == FormulaEnum.ADD:
            return first_value + second_value
        elif formula == FormulaEnum.SUBTRACT:
            return first_value - second_value
        elif formula == FormulaEnum.MULTIPLY:
            return first_value * second_value
        elif formula == FormulaEnum.DIVIDE:
            if second_value == 0:
                return 0
            return first_value / second_value
        else:
            raise ValueError('Unknown formula')

    async def query_sum_metric(self, metric_config: MetricConfig, dimension_index: int, **search_kwargs) \
            -> List[List]:
        # judge timestamp dimensions exist
        timestamp_dimension_exists = False
        dimensions = search_kwargs.get("dimensions", [])
        for one in dimensions:
            if one.field == TIMESTAMP_FIELD:
                timestamp_dimension_exists = True
                break
        stack_dimension = search_kwargs.get("stack_dimension")
        if stack_dimension and stack_dimension.field == TIMESTAMP_FIELD:
            timestamp_dimension_exists = True

        # remove timestamp filters started
        filters = search_kwargs.get("filters")
        if filters:
            for one in filters:
                for one_op in one.filters:
                    if isinstance(one_op, FilterExpression):
                        continue
                    if one_op.field == TIMESTAMP_FIELD:
                        one_op.value.gte = None
                        break

        if timestamp_dimension_exists:
            return await self.query_index_metric(metric_config, dimension_index, **search_kwargs)

        filters = search_kwargs.pop("filters", None)
        filters = self.merge_filters(filters, metric_config.filter)
        search_params = SearchParameters(
            metrics=[AggregationExpression(field=metric_config.sum_field, type=AggsTypeEnum.CARDINALITY)],
            filters=filters,
            **search_kwargs
        )
        # query result eg. [[dim1, dim2, metric1, metric2], [...]]
        return await SearchEngineService(search_params).search()

    async def query_index_metric(self, metric_config: MetricConfig, dimension_index: int, **search_kwargs) \
            -> List[List]:
        # merge filters
        filters = search_kwargs.pop('filters', None)
        filters = self.merge_filters(filters, metric_config.filter)

        search_params = SearchParameters(
            metrics=metric_config.aggregations,
            filters=filters,
            **search_kwargs
        )
        # query result eg. [[dim1, dim2, metric1, metric2], [...]]
        query_result = await SearchEngineService(search_params).search()

        # find finally metric value by index
        res = []
        for one in query_result:
            one_result = []
            if dimension_index >= 0:
                one_result.extend(one[:dimension_index + 1])
                one_result.append(one[dimension_index + 1:][metric_config.index])
            else:
                one_result.append(one[metric_config.index])
            res.append(one_result)
        return res

    async def sort_metrics(self, dimension_index: int, query_result: List[List], time_dimension_index: int,
                           timestamp_dimension: AggregationExpression, time_range: List[int]) -> (List[List],
                                                                                                  List[List]):
        res = query_result

        # sort and limit
        field_order_map = {}
        for index, one in enumerate(self.data_config.field_order):
            field_order_map[one.field_id] = (index, one)

        sort_field = {}
        sort_index = 0
        for one in self.data_config.dimensions:
            if one.field_id == TIMESTAMP_FIELD and one.sort is None:
                one.sort = "asc"
            sort_field[one.field_id] = (sort_index, one.sort)
            sort_index += 1
        if self.data_config.stack_dimension:
            dimension = self.data_config.stack_dimension
            if dimension.field_id == TIMESTAMP_FIELD and dimension.sort is None:
                dimension.sort = "asc"
            sort_field[dimension.field_id] = (sort_index, dimension.sort)
            sort_index += 1
        for one in self.data_config.metrics:
            sort_field[one.field_id] = (sort_index, one.sort)
            sort_index += 1
        for index in range(len(self.data_config.field_order) - 1, -1, -1):
            one = self.data_config.field_order[index]
            sort_field_config = sort_field.get(one.field_id)
            if not sort_field_config or sort_field_config[1] is None:
                continue
            if sort_field_config[1].lower() == "asc":
                sort_reverse = False
            elif sort_field_config[1].lower() == "desc":
                sort_reverse = True
            else:
                raise ValueError("unknown sort order")
            res.sort(key=lambda x: x[sort_field_config[0]], reverse=sort_reverse)

        # split result dimensions and values
        final_dimensions = []
        final_values = []
        for one in res:
            if dimension_index >= 0:
                # need filter some data by time range
                if time_dimension_index >= 0 and not self.in_time_range(time_range, one[time_dimension_index],
                                                                        timestamp_dimension):
                    continue
                one_dimension = one[:dimension_index + 1]

                if time_dimension_index >= 0:
                    one_dimension[time_dimension_index] = self.format_timestamp(
                        one_dimension[time_dimension_index], timestamp_dimension)

                final_dimensions.append(one_dimension)
                final_values.append(one[dimension_index + 1:])
            else:
                final_values.append(one)

        # limit size
        if self.data_config.result_limit:
            if limit_num := self.data_config.result_limit.get_limit_number():
                final_dimensions = final_dimensions[:limit_num]
                final_values = final_values[:limit_num]

        return final_dimensions, final_values

    def in_time_range(self, time_range: List[int], timestamp: int, timestamp_dimension: AggregationExpression) -> bool:
        """ judge data timestamp whether in time range"""
        if not time_range:
            return True
        start_date = datetime.fromtimestamp(time_range[0] / 1000)
        end_date = datetime.fromtimestamp(time_range[1] / 1000)
        data_date = datetime.fromtimestamp(timestamp / 1000)
        if timestamp_dimension.time_interval == "year":
            return start_date.year <= data_date.year <= end_date.year
        elif timestamp_dimension.time_interval == "month":
            tmp_start = datetime(year=start_date.year, month=start_date.month, day=1)
            tmp_date = datetime(year=data_date.year, month=data_date.month, day=1)
            tmp_end = datetime(year=end_date.year, month=end_date.month, day=1)
            return tmp_start <= tmp_date <= tmp_end
        elif timestamp_dimension.time_interval == "week":
            # week need special process, judge week range intersection with time_range
            week_end = (data_date + timedelta(days=6)).timestamp() * 1000
            return True if self.find_intersection([[timestamp, week_end], time_range]) else False

        return start_date <= data_date <= end_date

    @staticmethod
    def format_timestamp(timestamp: int, timestamp_dimension: AggregationExpression) -> str:
        dt_object = datetime.fromtimestamp(timestamp / 1000)
        if timestamp_dimension.time_interval == "year":
            return dt_object.strftime('%Y')
        elif timestamp_dimension.time_interval == "month":
            return dt_object.strftime('%Y-%m')
        elif timestamp_dimension.time_interval == "week":
            week_end = dt_object + timedelta(days=6)
            return dt_object.strftime('%Y-%m-%d') + ' ~ ' + week_end.strftime('%Y-%m-%d')
        elif timestamp_dimension.time_interval == "day":
            return dt_object.strftime('%Y-%m-%d')
        elif timestamp_dimension.time_interval == "hour":
            return dt_object.strftime('%Y-%m-%d %H')
        return dt_object.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def convert_metric_aggregation(agg_type: AggregationType) -> AggsTypeEnum:
        if agg_type == AggregationType.SUM:
            return AggsTypeEnum.SUM
        elif agg_type == AggregationType.AVERAGE:
            return AggsTypeEnum.AVG
        elif agg_type == AggregationType.COUNT:
            return AggsTypeEnum.VALUE_COUNT
        elif agg_type == AggregationType.MAX:
            return AggsTypeEnum.MAX
        elif agg_type == AggregationType.MIN:
            return AggsTypeEnum.MIN
        elif agg_type == AggregationType.DISTINCT_COUNT:
            return AggsTypeEnum.CARDINALITY
        raise QueryAggregationNotFoundError()

    @staticmethod
    async def convert_dimensions(dimensions: List[DimensionField], dimension_map: Dict[str, DimensionConfig]) \
            -> List[AggregationExpression]:
        res = []
        for dimension in dimensions:
            dimension_config = dimension_map.get(dimension.field_id)
            if not dimension_config:
                raise QueryDimensionNotFoundError()
            if dimension.time_granularity:
                agg = AggregationExpression(name=dimension_config.field,
                                            field=dimension_config.field,
                                            type=AggsTypeEnum.DATE_HISTOGRAM,
                                            time_interval=dimension.time_granularity)

            else:
                agg = AggregationExpression(name=dimension_config.field,
                                            field=dimension_config.field,
                                            type=AggsTypeEnum.TERMS)
            res.append(agg)
        return res

    async def convert_filters(self, dimension_map: Dict[str, DimensionConfig], metric_map: Dict[str, MetricConfig]) \
            -> (List[FilterExpression], List[int]):
        """
        return:
            filter expression: some filed filter,
            time_range: [start, end]: have time intersection or not time filters; None: no time intersection, don`t need query data
        """
        all_time_filters: List[TimeFilter] = []
        if self.data_config.time_filter:
            all_time_filters.append(self.data_config.time_filter)
        if self.time_filters:
            all_time_filters.extend(self.time_filters)

        filters = []
        filter_expressions = []
        filter_ope: Literal['must', 'should', 'must_not', 'filter']
        if self.data_config.filters_logic == LogicType.AND:
            filter_ope = "must"
        else:
            filter_ope = "should"
        for one in self.data_config.filters:
            field_config = dimension_map.get(one.field_id)
            if not field_config:
                metric_config = metric_map.get(one.field_id)
                if not metric_config or metric_config.is_virtual:
                    raise QueryDimensionNotFoundError()
                field_type = metric_config.field_type
            else:
                field_type = field_config.field_type

            filters.append(self.convert_filter_operator(one.field_id, one.operator, one.value, field_type))
        if filters:
            filter_expressions.append(FilterExpression(bool_operator=filter_ope, filters=filters))

        time_range = []
        for one in all_time_filters:
            start_date, end_date = one.get_start_end_date()
            if start_date and end_date:
                time_range.append([start_date, end_date])
        finally_time_range = self.find_intersection(time_range)
        if finally_time_range:
            filter_expressions.append(
                FilterExpression(bool_operator="must",
                                 filters=[RangeOp(field="timestamp",
                                                  value=RangeValue(
                                                      gte=finally_time_range[0],
                                                      lte=finally_time_range[1]))]))

        return filter_expressions, finally_time_range if time_range else []

    @staticmethod
    def find_intersection(intervals):
        """ find multi timestamp intervals intersection
        params:
            intervals: [[start, end], [start2, end2]]。
        return:
            if exist: [max_start, min_end]；else None。
        """
        if not intervals:
            return None

        max_start = intervals[0][0]
        min_end = intervals[0][1]

        for start, end in intervals[1:]:
            if start > max_start:
                max_start = start
            if end < min_end:
                min_end = end

        if max_start <= min_end:
            return [max_start, min_end]
        else:
            return None

    @staticmethod
    def convert_filter_operator(field: str, operator: OperatorType, value: Any, field_type) -> Union[
        AtomFilter, FilterExpression]:
        if field_type == "number":
            try:
                value = float(value)
            except ValueError:
                logger.warning("Failed to convert number to float")
        if operator == OperatorType.EQUAL:
            return TermOp(field=field, value=value)
        elif operator == OperatorType.NOT_EQUAL:
            return FilterExpression(bool_operator="must_not", filters=[
                TermOp(field=field, value=value),
            ])
        elif operator == OperatorType.GREATER_THAN:
            return RangeOp(field=field, value=RangeValue(gt=value))
        elif operator == OperatorType.LESS_THAN:
            return RangeOp(field=field, value=RangeValue(lt=value))
        elif operator == OperatorType.GREATER_THAN_OR_EQUAL:
            return RangeOp(field=field, value=RangeValue(gte=value))
        elif operator == OperatorType.LESS_THAN_OR_EQUAL:
            return RangeOp(field=field, value=RangeValue(lte=value))
        elif operator == OperatorType.CONTAINS:
            return MatchPhraseOp(field=field, value=value)
        elif operator == OperatorType.NOT_CONTAINS:
            return FilterExpression(bool_operator="must_not", filters=[
                MatchPhraseOp(field=field, value=value),
            ])
        elif operator == OperatorType.IS_EMPTY:
            return TermOp(field=field, value="null")
        elif operator == OperatorType.IS_NOT_EMPTY:
            return FilterExpression(bool_operator="must_not", filters=[
                TermOp(field=field, value="null"),
            ])
        elif operator == OperatorType.IN:
            return TermsOp(field=field, value=value)
        raise QueryOperatorNotFoundError()
