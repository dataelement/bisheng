"""基于登录事实计算期间去重人数和截至期末的累计参与率。"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from contextlib import aclosing
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from itertools import product
from typing import Any

from bisheng.common.errcode.telemetry import LoginParticipationDataError, LoginParticipationFilterError
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    FilterExpression,
    RangeOp,
    RangeValue,
    TermOp,
    TermsOp,
)

from .search_engine_service import SearchEngineService, SearchParameters
from .user_metric_definitions import active_user_metric

CHINA = timezone(timedelta(hours=8))
TIME_FIELDS = {"timestamp", "local_date"}
LOGIN_FIELDS = {"participation_rate", "logged_in_employee_count", "active_employee_count"}


def day_of(value: Any) -> date:
    if isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value / 1000 if value > 100_000_000_000 else value, CHINA).date()
    return date.fromisoformat(str(value)[:10])


def midnight(day: date) -> int:
    return int(datetime.combine(day, time.min, CHINA).timestamp() * 1000)


def period(day: date, granularity: str) -> tuple[date, date]:
    if granularity == "day":
        return day, day
    if granularity == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    if granularity == "month":
        start = day.replace(day=1)
        end = date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1)
        return start, end
    if granularity == "year":
        return date(day.year, 1, 1), date(day.year, 12, 31)
    raise LoginParticipationFilterError()


def selected_period(value: Any) -> tuple[date, date]:
    if isinstance(value, str):
        if " ~ " in value:
            start, end = value.split(" ~ ")
            return day_of(start), day_of(end)
        if len(value) == 4:
            return period(date(int(value), 1, 1), "year")
        if len(value) == 7:
            return period(date.fromisoformat(value + "-01"), "month")
    day = day_of(value)
    return day, day


class LoginSelection:
    """分离业务条件与展示日期, 累计分母只保留日期上界。"""

    def __init__(self, filters: list[FilterExpression] | None, today: date | None = None):
        self.start: date | None = None
        self.end = today or datetime.now(CHINA).date()
        self.selections: list[list[tuple[date, date]]] = []
        self.business = []
        self.business_filters = []
        try:
            for expr in filters or []:
                remaining = self._split(expr)
                if remaining is not None:
                    self.business.append({"bool": remaining.to_dsl()})
                    self.business_filters.append(remaining)
        except (ValueError, TypeError, OverflowError) as exc:
            raise LoginParticipationFilterError() from exc

    @staticmethod
    def _has_time(expr: Any) -> bool:
        if isinstance(expr, FilterExpression):
            return any(LoginSelection._has_time(item) for item in expr.filters)
        return expr.field in TIME_FIELDS

    def _split(self, expr: Any) -> Any:
        if not self._has_time(expr):
            return expr
        if isinstance(expr, FilterExpression):
            if expr.bool_operator not in ("must", "filter"):
                raise LoginParticipationFilterError()
            remaining = [item for child in expr.filters if (item := self._split(child)) is not None]
            return FilterExpression(bool_operator=expr.bool_operator, filters=remaining) if remaining else None
        if isinstance(expr, RangeOp):
            values = expr.value
            starts = [day_of(v) for v in (values.gte, values.gt) if v is not None]
            ends = [day_of(v) for v in (values.lte, values.lt) if v is not None]
            if values.gt is not None:
                starts[-1] += timedelta(days=1)
            if values.lt is not None:
                ends[-1] -= timedelta(days=1)
            if starts:
                self.start = max([*starts, *([self.start] if self.start else [])])
            if ends:
                self.end = min(self.end, *ends)
        elif isinstance(expr, (TermOp, TermsOp)):
            values = expr.value if isinstance(expr, TermsOp) else [expr.value]
            spans = [selected_period(value) for value in values]
            self.selections.append(spans)
            lower = min(start for start, _ in spans)
            self.start = max(self.start, lower) if self.start else lower
            self.end = min(self.end, max(end for _, end in spans))
        else:
            raise LoginParticipationFilterError()
        return None

    def contains(self, day: date) -> bool:
        return (
            (self.start is None or day >= self.start)
            and day <= self.end
            and all(any(start <= day <= end for start, end in spans) for spans in self.selections)
        )

    def query(self, *, history: bool, successful_only: bool = True) -> dict:
        bounds = {"lt": midnight(self.end + timedelta(days=1))}
        if not history and self.start:
            bounds["gte"] = midnight(self.start)
        conditions = [
            *self.business,
            *([
                {"term": {"metric_source": "participation"}},
                {"term": {"logged_in": True}},
            ] if successful_only else []),
            {"range": {"timestamp": bounds}},
        ]
        if not history:
            for spans in self.selections:
                conditions.append(
                    {
                        "bool": {
                            "minimum_should_match": 1,
                            "should": [
                                {
                                    "range": {
                                        "timestamp": {"gte": midnight(start), "lt": midnight(end + timedelta(days=1))}
                                    }
                                }
                                for start, end in spans
                            ],
                        }
                    }
                )
        return {"bool": {"filter": conditions}}

    def activity_filters(self) -> list[FilterExpression]:
        """活跃查询保留业务范围, 将年月等日期选择转换为实际期间."""
        filters = [
            *self.business_filters,
            FilterExpression(bool_operator="must", filters=[RangeOp(
                field="timestamp", value=RangeValue(
                    gte=midnight(self.start) if self.start else None,
                    lt=midnight(self.end + timedelta(days=1)),
                ),
            )]),
        ]
        for spans in self.selections:
            filters.append(FilterExpression(bool_operator="must", filters=[FilterExpression(
                bool_operator="should", filters=[RangeOp(
                    field="timestamp", value=RangeValue(gte=midnight(start), lt=midnight(end + timedelta(days=1))),
                ) for start, end in spans],
            )]))
        return filters


def dimension_keys(source: dict, fields: list[str]) -> set[tuple]:
    """同一嵌套对象的字段保持配对, 不产生部门 ID 与名称的错配。"""
    roots: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for index, field in enumerate(fields):
        root, _, leaf = field.partition(".")
        roots[root].append((index, leaf))
    alternatives = []
    for root, entries in roots.items():
        values = source.get(root)
        values = values if isinstance(values, list) else [values]
        choices = []
        for value in values:
            pairs = [(index, value.get(leaf) if leaf and isinstance(value, dict) else value) for index, leaf in entries]
            if all(value is not None for _, value in pairs):
                choices.append(pairs)
        alternatives.append(choices)
    keys = set()
    for combination in product(*alternatives):
        key = [None] * len(fields)
        for pairs in combination:
            for index, value in pairs:
                key[index] = value
        keys.add(tuple(key))
    return keys


class LoginPopulation:
    def __init__(self, dimensions: list[AggregationExpression], selection: LoginSelection):
        self.dimensions, self.selection = dimensions, selection
        self.time_indices = [i for i, dim in enumerate(dimensions) if dim.field in TIME_FIELDS]
        if len(self.time_indices) > 1:
            raise LoginParticipationFilterError()
        self.time_index = self.time_indices[0] if self.time_indices else None
        time_dim = dimensions[self.time_index] if self.time_index is not None else None
        self.granularity = (time_dim.time_interval or "day") if time_dim else None
        if self.granularity:
            period(selection.end, self.granularity)
        self.fields = [dim.field for dim in dimensions if dim.field not in TIME_FIELDS]
        self.firsts: dict[tuple, dict[int, date]] = defaultdict(dict)
        self.active: dict[tuple, set[int]] = defaultdict(set)

    def add(self, source: dict) -> None:
        if source.get("metric_source") != "participation" or source.get("logged_in") is not True:
            return
        try:
            day, user = day_of(source["timestamp"]), int(source["user_id"])
            if user <= 0:
                raise ValueError("user_id")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LoginParticipationDataError() from exc
        if day > self.selection.end:
            return
        for key in dimension_keys(source, self.fields):
            self.firsts[key][user] = min(day, self.firsts[key].get(user, day))
            if self.selection.contains(day):
                bucket = period(day, self.granularity)[0] if self.granularity else None
                self.active[key, bucket].add(user)

    def rows(self, metric: str, *, active_rows: list[list] | None = None) -> list[list]:
        if metric == "participation_rate":
            if active_rows is None:
                raise ValueError("Active user counts are required for participation rate")
            counts = {tuple(row[:-1]): row[-1] for row in active_rows}
            totals = {tuple(row[:-1]): row[-1] for row in self.rows("active_employee_count")}
            return [
                [*key, counts.get(key, 0) / totals[key] if totals.get(key) else 0.0]
                for key in dict.fromkeys([*totals, *counts])
            ]
        if self.selection.start and self.selection.start > self.selection.end:
            return []
        groups = self.firsts or ({(): {}} if not self.fields else {})
        result = []
        for key, users in groups.items():
            first_days = sorted(users.values())
            start = self.selection.start or (first_days[0] if first_days else self.selection.end)
            bucket = period(start, self.granularity)[0] if self.granularity else None
            while True:
                end = min(period(bucket, self.granularity)[1], self.selection.end) if bucket else self.selection.end
                # 非连续选中日期只展示与选择范围有交集的期间。
                selected_days = [
                    max(start, bucket or start) + timedelta(days=offset)
                    for offset in range((end - max(start, bucket or start)).days + 1)
                    if self.selection.contains(max(start, bucket or start) + timedelta(days=offset))
                ]
                if selected_days:
                    numerator = len(self.active.get((key, bucket), ()))
                    denominator = bisect_right(first_days, selected_days[-1])
                    if metric == "active_employee_count":
                        value = denominator
                    elif metric == "logged_in_employee_count":
                        value = numerator
                    else:
                        value = numerator / denominator if denominator else 0.0
                    row = list(key)
                    if self.time_index is not None:
                        field = self.dimensions[self.time_index].field
                        row.insert(self.time_index, bucket.isoformat() if field == "local_date" else midnight(bucket))
                    result.append([*row, value])
                if bucket is None or end >= self.selection.end:
                    break
                bucket = end + timedelta(days=1)
        return result


async def read_login_records(index: str, query: dict, fields: set[str]):
    """普通索引分页读取登录事实, 允许刷新偏差但拒绝失败或无效游标。"""
    client = await get_es_connection()
    cursor = None
    while True:
        body = {
            "size": 1000,
            "sort": [{"timestamp": "asc"}, {"tenant_id": "asc"}, {"user_id": "asc"}],
            "query": query,
            "_source": sorted(fields),
            "track_total_hits": False,
        }
        if cursor is not None:
            body["search_after"] = cursor
        response = await client.search(index=index, body=body, allow_partial_search_results=False)
        if (
            response.get("timed_out")
            or response.get("terminated_early")
            or response.get("_shards", {}).get("failed", 0)
        ):
            raise LoginParticipationDataError()
        hits = response["hits"]["hits"]
        if not hits:
            return
        next_cursor = hits[-1].get("sort")
        if not isinstance(next_cursor, list) or len(next_cursor) != 3:
            raise LoginParticipationDataError()
        try:
            if cursor is not None and next_cursor <= cursor:
                raise LoginParticipationDataError()
        except TypeError as exc:
            raise LoginParticipationDataError() from exc
        cursor = next_cursor
        for hit in hits:
            yield hit["_source"]


async def load_login_population(
    *,
    index_name: str,
    dimensions: list,
    stack_dimension: AggregationExpression | None,
    filters: list[FilterExpression] | None,
) -> LoginPopulation:
    selection = LoginSelection(filters)
    population = LoginPopulation([*dimensions, *([stack_dimension] if stack_dimension else [])], selection)
    fields = {"timestamp", "user_id", "metric_source", "logged_in"}
    fields.update(field.split(".")[0] for field in population.fields)
    if selection.start is None or selection.start <= selection.end:
        async with aclosing(read_login_records(index_name, selection.query(history=True), fields)) as records:
            async for source in records:
                population.add(source)
    return population


async def query_login_participation(metric: str, **search_kwargs) -> list[list]:
    population = await load_login_population(**search_kwargs)
    active_rows = await query_active_users(**search_kwargs) if metric == "participation_rate" else None
    return population.rows(metric, active_rows=active_rows)


async def query_active_users(**search_kwargs) -> list[list]:
    parameters = deepcopy(search_kwargs)
    metric = active_user_metric()
    parameters["filters"] = LoginSelection(parameters.get("filters")).activity_filters()
    if metric.filter is not None:
        parameters["filters"].append(metric.filter)
    for dimension in [*parameters.get("dimensions", []), *([parameters["stack_dimension"]] if parameters.get("stack_dimension") else [])]:
        if dimension.type == "date_histogram":
            dimension.custom_params["time_zone"] = "+08:00"
    return await SearchEngineService(SearchParameters(
        metrics=metric.aggregations,
        **parameters,
    )).search()
