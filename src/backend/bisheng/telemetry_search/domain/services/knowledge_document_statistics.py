# ruff: noqa: RUF001, RUF002
"""对完整候选集合进行精确文档统计，避免跨引用、分组和时间重复累加。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
DOCUMENT_METRICS = frozenset(
    {
        "total_file_count",
        "new_file_count",
        "knowledge_contribution_ratio",
        "called_document_count",
        "document_usage_ratio",
    }
)


def milliseconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value * 1000)
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (
        int(stamp.replace(tzinfo=CHINA).timestamp() * 1000) if stamp.tzinfo is None else int(stamp.timestamp() * 1000)
    )


def bucket_start(value: int, interval: str) -> int:
    stamp = datetime.fromtimestamp(value / 1000, CHINA)
    if interval == "hour":
        stamp = stamp.replace(minute=0, second=0, microsecond=0)
    else:
        stamp = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
        if interval == "week":
            stamp -= timedelta(days=stamp.weekday())
        elif interval == "month":
            stamp = stamp.replace(day=1)
        elif interval == "year":
            stamp = stamp.replace(month=1, day=1)
        elif interval != "day":
            raise ValueError("不支持的时间粒度")
    return int(stamp.timestamp() * 1000)


def next_bucket(value: int, interval: str) -> int:
    stamp = datetime.fromtimestamp(value / 1000, CHINA)
    if interval == "year":
        stamp = stamp.replace(year=stamp.year + 1)
    elif interval == "month":
        stamp = stamp.replace(year=stamp.year + (stamp.month == 12), month=stamp.month % 12 + 1)
    else:
        stamp += timedelta(hours=1) if interval == "hour" else timedelta(days=7 if interval == "week" else 1)
    return int(stamp.timestamp() * 1000)


def validated_end(metric: str, end: int | None) -> int:
    now = int(datetime.now(CHINA).timestamp() * 1000)
    if end is None:
        return now
    if metric in {"called_document_count", "document_usage_ratio"} and end < now - 1000:
        cutoff = datetime.fromtimestamp(end / 1000, CHINA)
        if (cutoff.hour, cutoff.minute, cutoff.second) != (23, 59, 59):
            raise ValueError("调用来源为日统计，历史截止时间须为当日 23:59:59，无法还原日内调用时刻")
    return end


class DocumentStatistics:
    def __init__(self, records: list[dict], called_at: dict[str, int]):
        if any(not row.get("knowledge_identity") for row in records):
            raise ValueError("文件统计缺少文档身份，请先完成知识空间统计索引重建")
        categories: dict[str, set[str]] = defaultdict(set)
        for row in records:
            categories[row["knowledge_identity"]].add(row.get("file_category_code") or "")
        if any(len(values) > 1 for values in categories.values()):
            raise ValueError("同一文档的知识分类冲突，请修正引用分类后重新同步")
        self.records = records
        self.called_at = called_at

    def aggregate(
        self,
        dimensions: list[tuple[str, str | None]],
        metric: str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> list[list]:
        if metric not in DOCUMENT_METRICS:
            raise ValueError("不支持的文档统计指标")
        end = validated_end(metric, end)
        if start is not None and start > end:
            return []
        time_dimensions = [(i, grain or "day") for i, (field, grain) in enumerate(dimensions) if field == "timestamp"]
        if metric in {"called_document_count", "document_usage_ratio"} and any(
            grain == "hour" for _, grain in time_dimensions
        ):
            raise ValueError("调用来源为日统计，请选择日或更粗的时间粒度")
        if len(time_dimensions) > 1:
            raise ValueError("文档统计只能配置一个时间维度")
        groups: dict[tuple, dict[str, int]] = defaultdict(dict)
        all_first: dict[str, int] = {}
        for row in self.records:
            created = milliseconds(row["timestamp"])
            if created > end:
                continue
            key = tuple(row.get(field) for field, _ in dimensions if field != "timestamp")
            identity = row["knowledge_identity"]
            groups[key][identity] = min(groups[key].get(identity, created), created)
            all_first[identity] = min(all_first.get(identity, created), created)
        if not dimensions or (time_dimensions and len(dimensions) == 1):
            groups.setdefault((), {})
        spans = [(None, start, end)]
        if time_dimensions:
            _, grain = time_dimensions[0]
            first = start if start is not None else min(all_first.values(), default=end)
            spans = []
            cursor = bucket_start(first, grain)
            while cursor <= end:
                following = next_bucket(cursor, grain)
                spans.append((cursor, max(first, cursor), min(end, following - 1)))
                cursor = following
        result = []
        for key, firsts in sorted(groups.items(), key=lambda item: tuple(str(value or "") for value in item[0])):
            for timestamp, lower, upper in spans:
                documents = {identity for identity, created in firsts.items() if created <= upper}
                used = {identity for identity in documents if self.called_at.get(identity, upper + 1) <= upper}
                if metric == "new_file_count":
                    value = sum(lower is None or firsts[identity] >= lower for identity in documents)
                elif metric == "called_document_count":
                    value = len(used)
                elif metric == "document_usage_ratio":
                    value = len(used) / len(documents) if documents else 0.0
                elif metric == "knowledge_contribution_ratio":
                    denominator = sum(created <= upper for created in all_first.values())
                    value = len(documents) / denominator if denominator else 0.0
                else:
                    value = len(documents)
                values = list(key)
                if time_dimensions:
                    values.insert(time_dimensions[0][0], timestamp)
                result.append([*values, value])
        return result

    def detail(self, metric: str, *, start: int | None, end: int | None) -> list[dict]:
        end = validated_end(metric, end)
        if start is not None and start > end:
            return []
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in self.records:
            if milliseconds(record["timestamp"]) <= end:
                grouped[record["knowledge_identity"]].append(record)
        result = []
        for identity, records in sorted(grouped.items()):
            first = min(milliseconds(record["timestamp"]) for record in records)
            if metric == "new_file_count" and start is not None and first < start:
                continue
            if (
                metric in {"called_document_count", "document_usage_ratio"}
                and self.called_at.get(identity, end + 1) > end
            ):
                continue
            merged = {}
            for field in set().union(*(record.keys() for record in records)):
                values = sorted({str(record[field]) for record in records if record.get(field) is not None})
                merged[field] = " / ".join(values)
            merged.update(knowledge_identity=identity, timestamp=first / 1000)
            result.append(merged)
        return result
