"""文件统计快照的批量差异对账; 读取失败不能当作记录缺失。"""

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from elasticsearch import Elasticsearch
from loguru import logger

from bisheng.telemetry.domain.mid_table.retry_budget import checkpoint

if TYPE_CHECKING:
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentRecord

VOLATILE_FIELDS = frozenset({"sync_run_id", "projection_updated_at"})


class BatchWriteError(RuntimeError):
    def __init__(self, failures: dict, successful_ids=()):
        self.failed_ids = set(failures)
        self.successful_ids = set(successful_ids)
        super().__init__(f"Projection bulk failed: {failures}")


def business_fields(source: dict[str, Any]) -> dict[str, Any]:
    """轮次标记不参与比较, 空可选字段与省略字段视为相同。"""
    return {key: value for key, value in source.items() if key not in VOLATILE_FIELDS and value is not None}


class ContentStatReconciler:
    def __init__(self, client: Elasticsearch, index: str, id_type: Callable = int):
        self.client = client
        self.index = index
        self.id_type = id_type

    def read(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        checkpoint()
        if not ids:
            return {}
        response = self.client.mget(index=self.index, ids=ids, realtime=True)
        expected_ids = set(ids)
        result = {}
        for item in response.get("docs", []):
            key = item.get("_id")
            if key not in expected_ids or key in result or item.get("error"):
                raise RuntimeError(f"Content stat mget invalid response id={key}")
            if item.get("found") is True:
                if not isinstance(item.get("_source"), dict):
                    raise RuntimeError(f"Content stat mget missing source id={key}")
                self.version(item)
            elif item.get("found") is not False:
                raise RuntimeError(f"Content stat mget missing found state id={key}")
            result[key] = item
        if set(result) != expected_ids:
            raise RuntimeError("Content stat mget incomplete batch")
        return result

    @staticmethod
    def version(item: dict[str, Any]) -> dict[str, int]:
        if item.get("_seq_no") is None or item.get("_primary_term") is None:
            raise RuntimeError(f"Content stat missing concurrency metadata id={item.get('_id')}")
        return {"if_seq_no": item["_seq_no"], "if_primary_term": item["_primary_term"]}

    def compare(self, records: list["KnowledgeSpaceContentRecord"]) -> tuple[list[dict], list[dict], int]:
        """先完成整批读取与比较, 再交给调用方一次性写入差异。"""
        return self.compare_documents({str(r.es_id): r.model_dump(exclude={"es_id"}) for r in records})

    def compare_documents(self, documents: dict[str, dict], merge: Callable | None = None) -> tuple[list, list, int]:
        observed = self.read(list(documents))
        operations, differences = [], []
        for key, document in documents.items():
            current = observed[key]
            desired = merge(current.get("_source", {}), document) if merge else document
            if current["found"]:
                old, new = business_fields(current["_source"]), business_fields(desired)
                if old == new:
                    continue
                fields = sorted(field for field in old.keys() | new.keys() if old.get(field) != new.get(field))
                metadata = {"_index": self.index, "_id": key, **self.version(current)}
                operations.append({"index": metadata})
            else:
                fields = ["missing"]
                operations.append({"create": {"_index": self.index, "_id": key}})
            operations.append(desired)
            differences.append({"file_id": self.id_type(key), "fields": fields})
        return operations, differences, len(documents) - len(differences)

    def reconcile(self, documents: dict[str, dict], merge: Callable | None = None) -> dict:
        operations, differences, unchanged = self.compare_documents(documents, merge)
        if differences:
            logger.info("telemetry.reconcile.differences index={} records={}", self.index, differences)
        try:
            result = self.write(operations)
        except BatchWriteError as exc:
            exc.successful_ids.update(set(documents) - exc.failed_ids)
            raise
        if result["conflict_ids"]:
            failures = {str(key): 409 for key in result["conflict_ids"]}
            raise BatchWriteError(failures, set(documents) - set(failures))
        return {**result, "checked": len(documents), "unchanged": unchanged}

    def write(self, operations: list[dict]) -> dict[str, Any]:
        checkpoint()
        result = {"created": 0, "updated": 0, "deleted": 0, "conflict_ids": []}
        if not operations:
            return result
        expected = []
        offset = 0
        while offset < len(operations):
            kind, metadata = next(iter(operations[offset].items()))
            expected.append((kind, metadata["_id"]))
            offset += 1 if kind == "delete" else 2
        response = self.client.bulk(operations=operations, refresh=False)
        items = response.get("items", [])
        if len(items) != len(expected):
            raise RuntimeError("Content stat bulk incomplete response")
        failures, successful = {}, []
        for item, (kind, key) in zip(items, expected, strict=True):
            payload = item.get(kind, {})
            if payload.get("_id") != key:
                raise RuntimeError("Content stat bulk mismatched response")
            status = payload.get("status", 0)
            if status == 409:
                result["conflict_ids"].append(self.id_type(key))
            elif kind == "delete" and status == 404:
                successful.append(key)
            elif 200 <= status < 300:
                result[{"create": "created", "index": "updated", "delete": "deleted"}[kind]] += 1
                successful.append(key)
            else:
                failures[key] = status
        if failures:
            failures.update({str(key): 409 for key in result["conflict_ids"]})
            raise BatchWriteError(failures, successful)
        return result

    def file_batches(self, guard: Callable[[], None], batch_size: int = 1000) -> Iterator[list[dict]]:
        """只扫描文件快照, 保留阅读、下载、收藏的历史日聚合。"""
        scroll_id = None
        try:
            guard()
            response = self.client.search(
                index=self.index,
                query={"term": {"record_type": "file"}},
                size=batch_size,
                sort=["_doc"],
                scroll="5m",
                seq_no_primary_term=True,
                source=["file_id"],
            )
            while True:
                scroll_id = response.get("_scroll_id", scroll_id)
                if (
                    response.get("timed_out")
                    or response.get("terminated_early")
                    or response.get("_shards", {}).get("failed", 0)
                ):
                    raise RuntimeError("Content stat reverse scan incomplete response")
                if "hits" not in response or "hits" not in response["hits"]:
                    raise RuntimeError("Content stat reverse scan missing hits")
                hits = response["hits"]["hits"]
                if not hits:
                    break
                if not scroll_id:
                    raise RuntimeError("Content stat reverse scan missing cursor")
                guard()
                yield hits
                guard()
                response = self.client.scroll(scroll_id=scroll_id, scroll="5m")
        finally:
            if scroll_id:
                try:
                    self.client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    logger.exception("Content stat reverse scan cursor cleanup failed")

    def deletion_operations(self, hits: list[dict], valid_ids: set[int]) -> list[dict]:
        return [
            {"delete": {"_index": self.index, "_id": hit["_id"], **self.version(hit)}}
            for hit in hits
            if int(hit["_id"]) not in valid_ids
        ]
