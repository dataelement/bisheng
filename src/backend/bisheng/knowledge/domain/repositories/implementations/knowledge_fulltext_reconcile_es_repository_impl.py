"""有界批量读取及条件 Bulk 写入; 所有返回值保留单项失败。"""

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

from elasticsearch import NotFoundError
from loguru import logger

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.contracts.fulltext_reconcile import (
    Mutation,
    Observation,
    ReconcileChunkDataError,
    ReconcileReadError,
    ReconcileWriteError,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextChunk,
    KnowledgeFulltextChunkSource,
)


class KnowledgeFulltextReconcileESRepository:
    def __init__(
        self,
        client: Any,
        *,
        index: str = constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
        max_bytes: int = 5 * 1024 * 1024,
        chunk_page_size: int = 500,
    ):
        self.client = client
        self.index = index
        self.max_bytes = max_bytes
        self.chunk_page_size = chunk_page_size
        self.unavailable_indexes = set()
        self.identity_errors = {}
        self.unkeyed_count = 0

    async def totals(self, ids: list[int]) -> dict[int, dict]:
        result = {i: {"preview_count": 0, "download_count": 0} for i in ids}
        if not ids:
            return result
        try:
            response = await self.client.search(
                index=constants.KNOWLEDGE_FULLTEXT_ENGAGEMENT_DAILY_INDEX,
                size=0,
                query={
                    "bool": {
                        "filter": [
                            {"term": {"record_type": "portal_engagement_daily"}},
                            {"terms": {"file_id": [str(i) for i in ids]}},
                        ]
                    }
                },
                aggs={
                    "files": {
                        "terms": {"field": "file_id", "size": len(ids)},
                        "aggs": {
                            "preview": {"sum": {"field": "preview_count"}},
                            "download": {"sum": {"field": "download_count"}},
                        },
                    }
                },
            )
        except NotFoundError:
            return result
        self.check_search(response)
        for bucket in response["aggregations"]["files"]["buckets"]:
            file_id = int(bucket["key"])
            if file_id in result:
                result[file_id] = {
                    "preview_count": int(bucket["preview"]["value"] or 0),
                    "download_count": int(bucket["download"]["value"] or 0),
                }
        return result

    @staticmethod
    def check_search(response: dict) -> None:
        if (
            response.get("timed_out")
            or response.get("terminated_early")
            or response.get("_shards", {}).get("failed", 0)
        ):
            raise ReconcileReadError("incomplete Elasticsearch search")

    async def read(self, ids: list[int]) -> dict[int, Observation | Exception]:
        if not ids:
            return {}
        response = await self.client.mget(index=self.index, ids=[str(i) for i in ids], realtime=True)
        result = {i: ReconcileReadError("missing mget response item") for i in ids}
        for item in response.get("docs", []):
            try:
                file_id = int(item["_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if file_id not in result:
                continue
            if item.get("error"):
                result[file_id] = ReconcileReadError("mget item failed")
            elif item.get("found") is False:
                result[file_id] = Observation(None)
            elif item.get("found") is True and isinstance(item.get("_source"), dict):
                if item.get("_seq_no") is None or item.get("_primary_term") is None:
                    result[file_id] = ReconcileReadError("missing concurrency metadata")
                else:
                    result[file_id] = Observation(item["_source"], item["_seq_no"], item["_primary_term"])
        return result

    async def reverse_page(self, after_id: int, limit: int = 200) -> list[int]:
        # file_id 是严格索引契约字段; 短 PIT 只覆盖一页, 下一轮仍全量覆盖并发变化。
        self.identity_errors = {}
        if after_id == 0:
            check = await self.client.search(
                index=self.index,
                size=0,
                track_total_hits=True,
                query={
                    "bool": {
                        "should": [
                            {"bool": {"must_not": [{"exists": {"field": "file_id"}}]}},
                            {"range": {"file_id": {"lte": 0}}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
            )
            self.check_search(check)
            self.unkeyed_count = int(check["hits"]["total"]["value"])
        pit = (await self.client.open_point_in_time(index=self.index, keep_alive="2m"))["id"]
        try:
            response = await self.client.search(
                pit={"id": pit, "keep_alive": "2m"},
                size=limit,
                query={"range": {"file_id": {"gt": after_id}}},
                sort=[{"file_id": "asc"}, "_shard_doc"],
                source=["file_id"],
            )
            pit = response.get("pit_id", pit)
            self.check_search(response)
            ids = []
            for item in response.get("hits", {}).get("hits", []):
                value = int(item["_source"]["file_id"])
                if value <= after_id:
                    raise ReconcileReadError("non advancing reverse cursor")
                if str(value) != item["_id"]:
                    self.identity_errors[value] = "invalid_es_identity"
                    logger.error("fulltext reconcile invalid document identity file_id={} es_id={}", value, item["_id"])
                ids.append(value)
            if ids != sorted(ids):
                raise ReconcileReadError("invalid reverse cursor")
            return sorted(set(ids))
        finally:
            await self._close(pit)

    async def _close(self, pit: str) -> None:
        try:
            await self.client.close_point_in_time(id=pit)
        except Exception:
            logger.exception("fulltext reconcile PIT close failed; PIT will expire")

    @staticmethod
    def _key(source: KnowledgeFulltextChunkSource) -> tuple:
        if source.shared:
            return (
                source.tenant_id,
                source.canonical_document_id,
                source.canonical_version_id,
                source.content_generation,
            )
        return (source.file_id,)

    async def chunks(
        self, sources: list[KnowledgeFulltextChunkSource]
    ) -> dict[int, list[KnowledgeFulltextChunk] | Exception]:
        result = {}
        groups = defaultdict(list)
        for source in sources:
            groups[source.index_name].append(source)
        for index, group in groups.items():
            result.update(await self._isolated_chunks(index, group))
        return result

    async def _isolated_chunks(self, index, group):
        if index in self.unavailable_indexes:
            return {s.file_id: ReconcileReadError("RAG index circuit open until next continuation") for s in group}
        try:
            return await asyncio.wait_for(self._chunks_group(index, group), timeout=60)
        except (ReconcileChunkDataError, KeyError, ValueError, TypeError) as exc:
            # 数据异常拆分定位, 依赖异常不拆分, 避免将故障放大为逐文件请求。
            if len(group) > 1:
                midpoint = len(group) // 2
                left = await self._isolated_chunks(index, group[:midpoint])
                left.update(await self._isolated_chunks(index, group[midpoint:]))
                return left
            logger.exception("fulltext reconcile malformed RAG source file_id={}", group[0].file_id)
            return {group[0].file_id: ReconcileReadError(type(exc).__name__)}
        except Exception as exc:
            logger.exception("fulltext reconcile RAG batch failed index={}", index)
            self.unavailable_indexes.add(index)
            return {s.file_id: ReconcileReadError(type(exc).__name__) for s in group}

    async def _chunks_group(self, index: str, sources: list[KnowledgeFulltextChunkSource]) -> dict:
        by_key = defaultdict(list)
        for source in sources:
            by_key[self._key(source)].append(source)
        clauses = []
        for key, entries in by_key.items():
            if entries[0].shared:
                filters = [
                    {"term": {f"metadata.{name}": value}}
                    for name, value in zip(
                        ("tenant_id", "canonical_document_id", "canonical_version_id", "content_generation"),
                        key,
                        strict=True,
                    )
                ]
                filters.append({"terms": {"metadata.knowledge_ids": sorted({e.knowledge_id for e in entries})}})
                clauses.append({"bool": {"filter": filters}})
            else:
                clauses.append({"term": {"metadata.document_id": key[0]}})
        result = {s.file_id: [] for s in sources}
        pit = (await self.client.open_point_in_time(index=index, keep_alive="2m"))["id"]
        after = None
        total_bytes = 0
        deadline = time.monotonic() + 45
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise ReconcileChunkDataError("chunk group exceeds time budget")
                kwargs = {
                    "pit": {"id": pit, "keep_alive": "2m"},
                    "size": self.chunk_page_size,
                    "query": {"bool": {"should": clauses, "minimum_should_match": 1}},
                    "sort": ["_shard_doc"],
                    "source": ["text", "metadata"],
                }
                if after is not None:
                    kwargs["search_after"] = after
                response = await self.client.search(**kwargs)
                pit = response.get("pit_id", pit)
                self.check_search(response)
                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for hit in hits:
                    data = hit["_source"]
                    meta = data["metadata"]
                    shared_key = tuple(
                        meta.get(n)
                        for n in ("tenant_id", "canonical_document_id", "canonical_version_id", "content_generation")
                    )
                    entries = by_key.get(shared_key) or by_key.get((int(meta.get("document_id", 0)),))
                    if not entries:
                        raise ReconcileChunkDataError("unexpected chunk ownership")
                    text = data["text"]
                    if not isinstance(text, str):
                        raise ReconcileChunkDataError("chunk text must be a string")
                    total_bytes += len(text.encode("utf-8"))
                    if total_bytes > 64 * 1024 * 1024:
                        raise ReconcileChunkDataError("chunk batch exceeds 64 MiB")
                    for source in entries:
                        if source.shared:
                            membership = meta.get("knowledge_ids", [])
                            membership = membership if isinstance(membership, list) else [membership]
                            if source.knowledge_id not in membership:
                                continue
                        elif int(meta.get("knowledge_id", 0)) != source.knowledge_id:
                            raise ReconcileChunkDataError("unexpected chunk knowledge")
                        result[source.file_id].append(
                            KnowledgeFulltextChunk(
                                es_id=str(hit["_id"]),
                                document_id=source.file_id,
                                knowledge_id=source.knowledge_id,
                                chunk_index=int(meta["chunk_index"]),
                                text=text,
                            )
                        )
                next_after = hits[-1].get("sort")
                if not isinstance(next_after, list) or next_after == after:
                    raise ReconcileReadError("non advancing chunk cursor")
                after = next_after
        finally:
            await self._close(pit)
        return result

    def _operations(self, mutation: Mutation) -> list[dict]:
        metadata = {"_index": self.index, "_id": str(mutation.file_id)}
        if mutation.observed.source is not None:
            if mutation.observed.seq_no is None or mutation.observed.primary_term is None:
                raise ReconcileWriteError("missing conditional write version")
            metadata.update(if_seq_no=mutation.observed.seq_no, if_primary_term=mutation.observed.primary_term)
        if mutation.document is None:
            return [{"delete": metadata}]
        if mutation.observed.source is None:
            return [{"create": metadata}, mutation.document]
        data = {
            k: v
            for k, v in mutation.document.items()
            if k not in {"preview_count", "download_count", "engagement_updated_at"}
        }
        return [{"update": metadata}, {"doc": data}]

    async def write(self, mutations: list[Mutation]) -> dict[int, Exception | None]:
        result = {}
        batch, operations, size = [], [], 0

        async def flush() -> None:
            if not batch:
                return
            try:
                response = await self.client.bulk(operations=operations, refresh=False)
                for mutation in batch:
                    result[mutation.file_id] = ReconcileWriteError("missing bulk result")
                for item in response.get("items", []):
                    payload = next(iter(item.values()))
                    file_id = int(payload["_id"])
                    if file_id not in {m.file_id for m in batch}:
                        continue
                    status = int(payload.get("status", 0))
                    deleted = "delete" in item and status == 404 and payload.get("result") == "not_found"
                    result[file_id] = (
                        None if 200 <= status < 300 or deleted else ReconcileWriteError(f"bulk status {status}")
                    )
            except Exception as exc:
                logger.exception("fulltext reconcile bulk result unknown")
                for mutation in batch:
                    result[mutation.file_id] = ReconcileWriteError(f"unknown:{type(exc).__name__}")

        for mutation in mutations:
            try:
                ops = self._operations(mutation)
                byte_count = sum(
                    len(json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1 for o in ops
                )
                if byte_count > self.max_bytes:
                    raise ReconcileWriteError("single document exceeds bulk byte budget")
            except Exception as exc:
                result[mutation.file_id] = exc
                continue
            if batch and (size + byte_count > self.max_bytes or len(batch) >= 200):
                await flush()
                batch, operations, size = [], [], 0
            batch.append(mutation)
            operations.extend(ops)
            size += byte_count
        await flush()
        return result
