"""共享存储对账适配器: 分页读取、条件更新和保留向量的重写。"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from bisheng.knowledge.domain.contracts.shared_storage_reconcile import MetadataRepair, ReconcileQueryError
from bisheng.knowledge.rag.shared_space_storage import (
    TenantRoutingSnapshot,
    build_shared_space_components_for_tenant,
    es_routing_value,
    get_shared_storage_conf,
    load_tenant_routing_snapshot,
    require_initialized_shared_routing,
)

logger = logging.getLogger(__name__)
TIMEOUT = 30
PAGE_SIZE = 500


class SharedStorageReconcileAdapter:
    def __init__(
        self,
        snapshot: TenantRoutingSnapshot,
        *,
        guard: Callable[[], Awaitable[None]],
        routing_provider: Callable[[int], TenantRoutingSnapshot | None] = load_tenant_routing_snapshot,
        writer_factory: Callable[[int], Any] = build_shared_space_components_for_tenant,
        es_client: Any = None,
    ) -> None:
        self.snapshot = snapshot
        self.tenant_id = snapshot.tenant_id
        self.guard = guard
        self.routing_provider = routing_provider
        self.writer_factory = writer_factory
        self.es_client = es_client
        self.writer = None
        self.embedding_model_id = str(snapshot.embedding_model_id)
        self.vector_dimension = 0

    async def _check(self) -> None:
        await self.guard()
        current = await asyncio.wait_for(
            asyncio.to_thread(self.routing_provider, self.snapshot.tenant_id),
            timeout=TIMEOUT,
        )
        current = require_initialized_shared_routing(self.snapshot.tenant_id, current)
        if current.write_frozen or any(
            getattr(current, key) != getattr(self.snapshot, key)
            for key in ("routing_version", "collection_name", "index_name", "embedding_model_id", "schema_fingerprint")
        ):
            raise ValueError("shared routing changed or writes frozen")

    async def _es(self) -> Any:
        if self.es_client is None:
            from elasticsearch import Elasticsearch

            from bisheng.common.services.config_service import settings

            conf = settings.get_vectors_conf().elasticsearch
            self.es_client = Elasticsearch(hosts=conf.elasticsearch_url, **conf.ssl_verify)
        return self.es_client.options(request_timeout=TIMEOUT, max_retries=0)

    async def _writer(self) -> Any:
        if self.writer is None:
            self.writer, _ = await asyncio.wait_for(
                asyncio.to_thread(self.writer_factory, self.snapshot.tenant_id),
                timeout=TIMEOUT,
            )
            for field in self.writer.collection.schema.fields:
                if field.name == "vector":
                    self.vector_dimension = int(field.params["dim"])
        await asyncio.wait_for(
            asyncio.to_thread(self.writer._assert_writable, embedding_model_id=self.embedding_model_id),
            timeout=TIMEOUT,
        )
        return self.writer

    async def read(self, side: str, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        await self._check()
        if not ids:
            return {}
        if side == "es":
            return await self._read_es(ids)
        if side == "milvus":
            return await self._read_milvus(ids)
        raise ValueError("unknown shared storage backend")

    @staticmethod
    def _group(ids: list[int], rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        result = {i: [] for i in ids}
        for row in rows:
            doc_id = int(row["canonical_document_id"])
            if doc_id not in result:
                raise ReconcileQueryError("response contains an unexpected document")
            result[doc_id].append(row)
        return result

    async def _read_es(self, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        client = await self._es()
        scroll_id = None
        rows = []
        try:
            response = await asyncio.to_thread(
                client.search,
                index=self.snapshot.index_name,
                query={"terms": {"metadata.canonical_document_id": list(ids)}},
                sort=["_doc"],
                size=PAGE_SIZE,
                scroll="2m",
                source=True,
                seq_no_primary_term=True,
                stored_fields=["_routing"],
                allow_partial_search_results=False,
            )
            while True:
                scroll_id = response.get("_scroll_id", scroll_id)
                if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
                    raise ReconcileQueryError("incomplete Elasticsearch search")
                hits = response["hits"]["hits"]
                if not hits:
                    break
                for hit in hits:
                    source = hit["_source"]
                    rows.append(
                        {
                            **source["metadata"],
                            "text": source.get("text"),
                            "_id": hit["_id"],
                            "_seq_no": hit["_seq_no"],
                            "_primary_term": hit["_primary_term"],
                            "_routing": hit.get("_routing")
                            or next(iter(hit.get("fields", {}).get("_routing", [])), None),
                        }
                    )
                if not scroll_id:
                    raise ReconcileQueryError("missing Elasticsearch scroll cursor")
                await self._check()
                response = await asyncio.to_thread(client.scroll, scroll_id=scroll_id, scroll="2m")
        finally:
            if scroll_id:
                try:
                    await asyncio.to_thread(client.clear_scroll, scroll_id=scroll_id)
                except Exception as exc:
                    logger.warning("shared_reconcile scroll_close_failed error_type=%s", type(exc).__name__)
        return self._group(ids, rows)

    async def _read_milvus(self, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        writer = await self._writer()
        iterator = await asyncio.to_thread(
            writer.collection.query_iterator,
            expr=f"canonical_document_id in {list(map(int, ids))}",
            output_fields=[field.name for field in writer.collection.schema.fields],
            batch_size=PAGE_SIZE,
            timeout=TIMEOUT,
            consistency_level="Strong",
        )
        rows = []
        try:
            while True:
                await self._check()
                batch = await asyncio.to_thread(iterator.next)
                if not batch:
                    break
                rows.extend(batch)
        finally:
            try:
                await asyncio.to_thread(iterator.close)
            except Exception as exc:
                logger.warning("shared_reconcile iterator_close_failed error_type=%s", type(exc).__name__)
        return self._group(ids, rows)

    @staticmethod
    def _expected(plan: MetadataRepair) -> dict[str, Any]:
        return plan.snapshot.expected_metadata

    @staticmethod
    def _valid_rows(plan: MetadataRepair, current: list[dict[str, Any]], *, vector: bool = False) -> bool:
        # 重试必须重新读取; 上一次插入可能已成功, 不能盲目再次插入。
        expected = {int(row["chunk_index"]): row for row in plan.rows}
        if not current or {int(row["chunk_index"]) for row in current} != set(expected):
            return False
        keys = ["canonical_version_id", "content_generation", "content_file_id", "embedding_model_id", "text"]
        for row in current:
            old = expected[int(row["chunk_index"])]
            if any(row.get(k) != old.get(k) for k in keys):
                return False
            if vector and list(row["vector"]) != list(old["vector"]):
                return False
        return True

    async def repair(self, side: str, plans: list[MetadataRepair]) -> dict[int, str | None]:
        await self._check()
        actual = await self.read(side, [p.snapshot.document_id for p in plans])
        valid, result = [], {}
        for plan in plans:
            doc_id = plan.snapshot.document_id
            if not self._valid_rows(plan, actual.get(doc_id, []), vector=side == "milvus"):
                result[doc_id] = "target_changed"
            else:
                valid.append(plan)
        if not valid:
            return result
        if side == "es":
            result.update(await self._repair_es(valid, actual))
        else:
            result.update(await self._repair_milvus(valid, actual))
        return result

    async def _repair_es(
        self, plans: list[MetadataRepair], actual: dict[int, list[dict[str, Any]]]
    ) -> dict[int, str | None]:
        client = await self._es()
        actions = []
        result = {p.snapshot.document_id: None for p in plans}
        for plan in plans:
            for row in actual[plan.snapshot.document_id]:
                update = {
                    "_index": self.snapshot.index_name,
                    "_id": row["_id"],
                    "if_seq_no": row["_seq_no"],
                    "if_primary_term": row["_primary_term"],
                }
                routing = row.get("_routing")
                if routing is None and get_shared_storage_conf().es_routing_enabled:
                    routing = es_routing_value(self.snapshot.tenant_id, plan.snapshot.document_id)
                if routing is not None:
                    update["routing"] = routing
                actions.append(
                    (
                        plan.snapshot.document_id,
                        {"update": update},
                        {
                            "script": {
                                "lang": "painless",
                                "source": "for (def e : params.metadata.entrySet()) { ctx._source.metadata[e.getKey()] = e.getValue(); }",
                                "params": {"metadata": self._expected(plan)},
                            }
                        },
                    )
                )
        for offset in range(0, len(actions), PAGE_SIZE):
            batch = actions[offset : offset + PAGE_SIZE]
            await self._check()
            response = await asyncio.to_thread(
                client.bulk,
                operations=[part for _, action, doc in batch for part in (action, doc)],
                refresh="wait_for",
            )
            items = response.get("items", [])
            if len(items) != len(batch):
                raise ReconcileQueryError("incomplete Elasticsearch bulk response")
            for (doc_id, _, _), item in zip(batch, items, strict=True):
                update = item.get("update", {})
                if not 200 <= int(update.get("status", 0)) < 300 or update.get("error"):
                    result[doc_id] = f"bulk_status_{update.get('status', 0)}"
        return result

    async def _repair_milvus(
        self, plans: list[MetadataRepair], actual: dict[int, list[dict[str, Any]]]
    ) -> dict[int, str | None]:
        writer = await self._writer()
        insertions, delete_pks = [], []
        for plan in plans:
            expected = self._expected(plan)
            writer._check_membership_limits(plan.snapshot.knowledge_ids)
            chunks = defaultdict(list)
            for row in actual[plan.snapshot.document_id]:
                chunks[int(row["chunk_index"])].append(row)
            for rows in chunks.values():
                matching = [r for r in rows if all(r.get(k) == v for k, v in expected.items())]
                if matching:
                    keep = max(matching, key=lambda r: int(r["pk"]))
                    delete_pks.extend(int(r["pk"]) for r in rows if r["pk"] != keep["pk"])
                    continue
                row = dict(max(rows, key=lambda r: int(r["pk"])))
                row.pop("pk")
                row.update(expected)
                insertions.append(row)
                delete_pks.extend(int(r["pk"]) for r in rows)
        for offset in range(0, len(insertions), PAGE_SIZE):
            await self._check()
            batch = insertions[offset : offset + PAGE_SIZE]
            response = await asyncio.to_thread(writer.collection.insert, batch, timeout=TIMEOUT)
            if int(response.insert_count) != len(batch):
                raise ReconcileQueryError("incomplete Milvus insertion")
        # 所有新行确认写入后, 只清理本次已经读取的旧主键。
        for offset in range(0, len(delete_pks), PAGE_SIZE):
            await self._check()
            await asyncio.to_thread(
                writer.collection.delete, expr=f"pk in {delete_pks[offset : offset + PAGE_SIZE]}", timeout=TIMEOUT
            )
        return {p.snapshot.document_id: None for p in plans}

    async def close(self) -> None:
        if self.es_client is not None:
            await asyncio.to_thread(self.es_client.close)
        if self.writer is not None:
            await asyncio.to_thread(self.writer.es_client.close)
