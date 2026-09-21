"""基于登录事实计算期间去重人数和截至期末的累计参与率。"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from contextlib import aclosing
from datetime import date, datetime, time, timedelta, timezone
from itertools import product
from typing import Any

from bisheng.common.errcode.telemetry import LoginParticipationDataError, LoginParticipationFilterError
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.telemetry_search.domain.schemas.query_builder import (
    AggregationExpression,
    FilterExpression,
    RangeOp,
    TermOp,
    TermsOp,
)

CHINA = timezone(timedelta(hours=8))
TIME_FIELDS = {"timestamp", "local_date"}
LOGIN_FIELDS = {"participation_rate", "logged_in_employee_count"}


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
        try:
            for expr in filters or []:
                remaining = self._split(expr)
                if remaining is not None:
                    self.business.append({"bool": remaining.to_dsl()})
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

    def query(self, *, history: bool) -> dict:
        bounds = {"lt": midnight(self.end + timedelta(days=1))}
        if not history and self.start:
            bounds["gte"] = midnight(self.start)
        conditions = [
            *self.business,
            {"term": {"metric_source": "participation"}},
            {"term": {"logged_in": True}},
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

    def rows(self, metric: str) -> list[list]:
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
                    value = (
                        numerator
                        if metric == "logged_in_employee_count"
                        else (numerator / denominator if denominator else 0.0)
                    )
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
    """PIT 分页完整读取, 禁止超时或部分分片结果冒充完整累计人数。"""
    client = await get_es_connection()
    opened = await client.open_point_in_time(index=index, keep_alive="2m")
    pit_id = opened["id"]
    cursor, total, count = None, None, 0
    try:
        if opened.get("_shards", {}).get("failed", 0):
            raise LoginParticipationDataError()
        while True:
            body = {
                "size": 1000,
                "pit": {"id": pit_id, "keep_alive": "2m"},
                "sort": [{"_shard_doc": "asc"}],
                "query": query,
                "_source": sorted(fields),
                "track_total_hits": total is None,
            }
            if cursor is not None:
                body["search_after"] = cursor
            response = await client.search(body=body, allow_partial_search_results=False)
            pit_id = response.get("pit_id", pit_id)
            if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                raise LoginParticipationDataError()
            if total is None:
                totals = response["hits"]["total"]
                if totals.get("relation") != "eq":
                    raise LoginParticipationDataError()
                total = totals["value"]
            hits = response["hits"]["hits"]
            if not hits:
                if count != total:
                    raise LoginParticipationDataError()
                break
            next_cursor = hits[-1].get("sort")
            if next_cursor is None or next_cursor == cursor:
                raise LoginParticipationDataError()
            cursor = next_cursor
            for hit in hits:
                count += 1
                if count > total:
                    raise LoginParticipationDataError()
                yield hit["_source"]
    finally:
        await client.close_point_in_time(body={"id": pit_id})


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
    return population.rows(metric)
