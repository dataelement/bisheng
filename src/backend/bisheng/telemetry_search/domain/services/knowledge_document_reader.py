# ruff: noqa: RUF001, RUF002
"""一致 ES 视图内完整读取文件候选及非个人入口调用，任何部分失败均中止。"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from bisheng.common.errcode.telemetry import DocumentStatisticsNotReadyError
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
    KnowledgeStatisticsRepositoryImpl as KnowledgeStatisticsRepository,
)
from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, RangeOp, TermOp, TermsOp

from .knowledge_document_statistics import CHINA, DocumentStatistics, next_bucket


def split_time_filters(filters: list[FilterExpression]) -> tuple[list[dict], int | None, int | None]:
    starts, ends = [], []

    def convert(expr, conjunctive=True):
        if isinstance(expr, FilterExpression):
            safe = conjunctive and expr.bool_operator in {"must", "filter"}
            children = [value for child in expr.filters if (value := convert(child, safe)) is not None]
            return {"bool": {expr.bool_operator: children}} if children else None
        if isinstance(expr, RangeOp) and expr.field == "timestamp":
            if not conjunctive:
                raise ValueError("文档统计的时间范围需使用 AND 条件或时间筛选器")
            value = expr.value
            if value.gte is not None:
                starts.append(int(value.gte))
            if value.gt is not None:
                starts.append(int(value.gt) + 1)
            if value.lte is not None:
                ends.append(int(value.lte))
            if value.lt is not None:
                ends.append(int(value.lt) - 1)
            return None
        if expr.field == "timestamp":
            values = expr.value if isinstance(expr, TermsOp) else [expr.value]
            if not conjunctive or not isinstance(expr, (TermOp, TermsOp)) or len(values) != 1:
                raise ValueError("文档统计的时间条件需使用单个时间桶或 AND 时间范围")
            label = str(values[0])
            formats = (
                (r"\d{4}", "%Y", "year"),
                (r"\d{4}-\d{2}", "%Y-%m", "month"),
                (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d", "day"),
                (r"\d{4}-\d{2}-\d{2} \d{2}", "%Y-%m-%d %H", "hour"),
            )
            if " ~ " in label:
                first, last = label.split(" ~ ")
                lower = int(datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=CHINA).timestamp() * 1000)
                upper = int(datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=CHINA).timestamp() * 1000)
                starts.append(lower)
                ends.append(next_bucket(upper, "day") - 1)
                return None
            for pattern, date_format, grain in formats:
                if re.fullmatch(pattern, label):
                    lower = int(datetime.strptime(label, date_format).replace(tzinfo=CHINA).timestamp() * 1000)
                    starts.append(lower)
                    ends.append(next_bucket(lower, grain) - 1)
                    return None
            raise ValueError("无法识别文档统计的时间桶")
        return expr.to_dsl()

    result = [value for expr in filters if (value := convert(expr)) is not None]
    return result, max(starts, default=None), min(ends, default=None)


class DocumentReader:
    def __init__(self, client: Any, pit_id: str):
        self.client, self.pit_id = client, pit_id

    async def buckets(self, query: dict, field: str, aggregations: dict):
        after = None
        while True:
            composite = {"size": 500, "sources": [{"key": {"terms": {"field": field}}}]}
            if after is not None:
                composite["after"] = after
            response = await self.client.search(
                pit={"id": self.pit_id, "keep_alive": "2m"},
                size=0,
                allow_partial_search_results=False,
                query=query,
                aggs={"items": {"composite": composite, "aggs": aggregations}},
            )
            self.pit_id = response.get("pit_id", self.pit_id)
            if (
                response.get("timed_out")
                or response.get("terminated_early")
                or response.get("_shards", {}).get("failed", 0)
            ):
                raise RuntimeError("知识文档统计 ES 返回不完整，已停止统计")
            page = response["aggregations"]["items"]
            yield page["buckets"]
            cursor = page.get("after_key")
            if not page["buckets"] or cursor is None:
                return
            if cursor == after:
                raise RuntimeError("知识文档统计分页游标未前进")
            after = cursor

    async def load(self, filters: list[dict], *, include_usage: bool) -> DocumentStatistics:
        query = {
            "bool": {
                "filter": [
                    *filters,
                    {"term": {"record_type": "file"}},
                    {"term": {"file_type": 1}},
                ]
            }
        }
        records = []
        async for page in self.buckets(query, "file_id", {"record": {"top_hits": {"size": 1}}}):
            for bucket in page:
                if bucket["doc_count"] != 1:
                    raise ValueError("同一文件存在重复统计投影，请检查索引别名或重新导入")
                records.append(bucket["record"]["hits"]["hits"][0]["_source"])
        stats = DocumentStatistics(records, {})
        if not include_usage:
            return stats
        identities = {row["knowledge_identity"] for row in records}
        aliases = await asyncio.to_thread(KnowledgeStatisticsRepository.aliases, identities)
        ids = sorted(aliases)
        for offset in range(0, len(ids), 400):
            query = {
                "bool": {
                    "filter": [
                        {"terms": {"file_id": [str(value) for value in ids[offset : offset + 400]]}},
                        {"terms": {"space_level": ["public", "department", "team", "team_ks"]}},
                        {
                            "bool": {
                                "minimum_should_match": 1,
                                "should": [
                                    {
                                        "bool": {
                                            "filter": [
                                                {"term": {"record_type": "preview_daily"}},
                                                {"range": {"preview_count": {"gt": 0}}},
                                            ]
                                        }
                                    },
                                    {
                                        "bool": {
                                            "filter": [
                                                {"term": {"record_type": "download_daily"}},
                                                {"range": {"download_count": {"gt": 0}}},
                                            ]
                                        }
                                    },
                                ],
                            }
                        },
                    ]
                }
            }
            async for page in self.buckets(query, "file_id", {"first": {"min": {"field": "timestamp"}}}):
                for bucket in page:
                    identity = aliases[int(bucket["key"]["key"])]
                    timestamp = bucket["first"]["value"]
                    if timestamp is None:
                        raise ValueError("调用日统计缺少有效日期")
                    stats.called_at[identity] = min(stats.called_at.get(identity, int(timestamp)), int(timestamp))
        return stats


@asynccontextmanager
async def document_reader(index: str):
    client = await get_es_connection()
    mapping = await client.indices.get_mapping(index=index)
    if not mapping or any(
        value.get("mappings", {}).get("_meta", {}).get("document_statistics_version") != 1 for value in mapping.values()
    ):
        raise DocumentStatisticsNotReadyError()
    response = await client.open_point_in_time(index=index, keep_alive="2m", allow_partial_search_results=False)
    reader = DocumentReader(client, response["id"])
    try:
        yield reader
    finally:
        await client.close_point_in_time(id=reader.pit_id)
