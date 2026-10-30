# ruff: noqa: RUF001, RUF002
"""普通索引分页读取文件候选及非个人入口调用，查询失败时中止统计。"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from loguru import logger

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
    KnowledgeStatisticsRepositoryImpl as KnowledgeStatisticsRepository,
)
from bisheng.telemetry_search.domain.schemas.query_builder import FilterExpression, RangeOp, TermOp, TermsOp

from .knowledge_document_statistics import CHINA, DocumentStatistics, next_bucket

FILE_PAGE_SIZE = 2000
USAGE_BATCH_SIZE = 400
USAGE_CONCURRENCY = 4
CHART_SOURCE_FIELDS = (
    "file_id",
    "knowledge_identity",
    "timestamp",
    "space_id",
    "file_category_code",
    "file_category_name",
)


def chart_source_fields(dimension_fields: list[str]) -> list[str]:
    """图表统计固定带上分类和空间字段，避免分类冲突告警被字段裁剪丢掉。"""
    fields = set(CHART_SOURCE_FIELDS)
    for field in dimension_fields:
        if field and field != "timestamp":
            fields.add(field)
    return sorted(fields)


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
    def __init__(self, client: Any, index: str):
        self.client, self.index = client, index

    async def buckets(self, query: dict, field: str, aggregations: dict):
        after = None
        while True:
            composite = {"size": 500, "sources": [{"key": {"terms": {"field": field}}}]}
            if after is not None:
                composite["after"] = after
            response = await self.client.search(
                index=self.index,
                size=0,
                allow_partial_search_results=False,
                query=query,
                aggs={"items": {"composite": composite, "aggs": aggregations}},
            )
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

    def _reject_partial(self, response: dict) -> None:
        if (
            response.get("timed_out")
            or response.get("terminated_early")
            or response.get("_shards", {}).get("failed", 0)
        ):
            raise RuntimeError("知识文档统计 ES 返回不完整，已停止统计")

    async def _iter_files(self, query: dict, source_fields: list[str] | None):
        """按 file_id 分页读取。缺 file_id 的文档不进入统计，重复 file_id 跨页也报错。"""
        search_after = None
        previous_file_id = None
        while True:
            payload = {
                "index": self.index,
                "size": FILE_PAGE_SIZE,
                "allow_partial_search_results": False,
                "query": query,
                "sort": [{"file_id": "asc"}, {"timestamp": "asc"}],
                "track_total_hits": False,
            }
            if source_fields is not None:
                payload["source"] = source_fields
            if search_after is not None:
                payload["search_after"] = search_after
            response = await self.client.search(**payload)
            self._reject_partial(response)
            hits = response["hits"]["hits"]
            if not hits:
                return
            cursor = hits[-1].get("sort")
            if not isinstance(cursor, list) or len(cursor) != 2:
                raise RuntimeError("知识文档统计分页游标无效")
            if search_after is not None and cursor <= search_after:
                raise RuntimeError("知识文档统计分页游标未前进")
            search_after = cursor
            for hit in hits:
                source = dict(hit["_source"])
                file_id = str(source.get("file_id"))
                if previous_file_id is not None and file_id == previous_file_id:
                    raise ValueError("同一文件存在重复统计投影，请检查索引别名或重新导入")
                previous_file_id = file_id
                yield source
            if len(hits) < FILE_PAGE_SIZE:
                return

    async def load(
        self,
        filters: list[dict],
        *,
        include_usage: bool,
        source_fields: list[str] | None = None,
    ) -> DocumentStatistics:
        from .query_singleflight import shared_call, stable_key

        key = stable_key(
            {
                "kind": "documents",
                "index": self.index,
                "tenant": get_current_tenant_id() or 1,
                "filters": filters,
                "include_usage": include_usage,
                "fields": source_fields,
            }
        )
        return await shared_call(
            key,
            lambda filters=filters, include_usage=include_usage, source_fields=source_fields: self._load_unshared(
                filters,
                include_usage=include_usage,
                source_fields=source_fields,
            ),
        )

    async def _load_unshared(
        self,
        filters: list[dict],
        *,
        include_usage: bool,
        source_fields: list[str] | None = None,
    ) -> DocumentStatistics:
        started = time.perf_counter()
        query = {
            "bool": {
                "filter": [
                    *filters,
                    {"exists": {"field": "file_id"}},
                    {"term": {"record_type": "file"}},
                    {"term": {"file_type": 1}},
                ]
            }
        }
        records = [row async for row in self._iter_files(query, source_fields)]
        logger.info(
            "document_statistics_load index={} records={} fields={} elapsed_ms={}",
            self.index,
            len(records),
            len(source_fields) if source_fields is not None else "all",
            round((time.perf_counter() - started) * 1000, 1),
        )
        # 旧索引记录在查询内补齐身份, 不要求迁移或改写 ES 数据。
        missing = [row for row in records if not row.get("knowledge_identity")]
        if missing:
            identity_started = time.perf_counter()
            identities = await asyncio.to_thread(
                KnowledgeStatisticsRepository.identities, [int(row["file_id"]) for row in missing]
            )
            logger.info(
                "document_statistics_identities missing={} resolved={} elapsed_ms={}",
                len(missing),
                len(identities),
                round((time.perf_counter() - identity_started) * 1000, 1),
            )
            for row in missing:
                identity = identities.get(int(row["file_id"]))
                if not identity:
                    raise ValueError(f"文件统计无法关联文档身份，请检查库存同步：file_id={row['file_id']}")
                row["knowledge_identity"] = identity
        stats = DocumentStatistics(records, {})
        if stats.category_conflicts:
            logger.warning(
                "document_category_conflicts tenant={} index={} documents={} samples={}",
                get_current_tenant_id() or 1,
                self.index,
                len(stats.category_conflicts),
                stats.conflict_samples(),
            )
        if not include_usage:
            return stats
        alias_started = time.perf_counter()
        identities = {row["knowledge_identity"] for row in records}
        aliases = await asyncio.to_thread(KnowledgeStatisticsRepository.aliases, identities)
        logger.info(
            "document_statistics_aliases identities={} files={} elapsed_ms={}",
            len(identities),
            len(aliases),
            round((time.perf_counter() - alias_started) * 1000, 1),
        )
        ids = sorted(aliases)
        usage_started = time.perf_counter()
        batches = [ids[offset : offset + USAGE_BATCH_SIZE] for offset in range(0, len(ids), USAGE_BATCH_SIZE)]
        semaphore = asyncio.Semaphore(USAGE_CONCURRENCY)

        async def scan_batch(batch: list[int]) -> dict[str, int]:
            async with semaphore:
                found: dict[str, int] = {}
                usage_query = {
                    "bool": {
                        "filter": [
                            {"terms": {"file_id": [str(value) for value in batch]}},
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
                                        {
                                            "bool": {
                                                "filter": [
                                                    {"term": {"record_type": "qa_citation_daily"}},
                                                    {"range": {"qa_citation_count": {"gt": 0}}},
                                                ]
                                            }
                                        },
                                    ],
                                }
                            },
                        ]
                    }
                }
                async for page in self.buckets(usage_query, "file_id", {"first": {"min": {"field": "timestamp"}}}):
                    for bucket in page:
                        identity = aliases[int(bucket["key"]["key"])]
                        timestamp = bucket["first"]["value"]
                        if timestamp is None:
                            raise ValueError("调用日统计缺少有效日期")
                        current = found.get(identity)
                        found[identity] = int(timestamp) if current is None else min(current, int(timestamp))
                return found

        scanned = await asyncio.gather(*(scan_batch(batch) for batch in batches))
        for found in scanned:
            for identity, timestamp in found.items():
                current = stats.called_at.get(identity)
                stats.called_at[identity] = timestamp if current is None else min(current, timestamp)
        logger.info(
            "document_statistics_usage batches={} files={} identities={} elapsed_ms={}",
            len(batches),
            len(ids),
            len(stats.called_at),
            round((time.perf_counter() - usage_started) * 1000, 1),
        )
        return stats


@asynccontextmanager
async def document_reader(index: str):
    client = await get_es_connection()
    yield DocumentReader(client, index)
