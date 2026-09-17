"""每日逐批对比再修复; 文档、批次、存储端各自隔离失败。"""

import asyncio
import logging
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

from bisheng.knowledge.domain.contracts.shared_storage_reconcile import (
    DocumentSnapshot,
    MetadataRepair,
    ReconcileLockLost,
)

logger = logging.getLogger(__name__)
SIDES = ("es", "milvus")
T = TypeVar("T")


class SharedStorageReconcileService:
    def __init__(
        self,
        *,
        source_factory: Callable[[], AbstractAsyncContextManager[Any]],
        store: Any,
        guard: Callable[[], Awaitable[None]],
        dispatch: Callable[[int], Awaitable[None]],
        run_id: str,
        batch_size: int = 100,
        retry_delays: tuple[float, ...] = (2, 5),
        circuit_threshold: int = 3,
    ) -> None:
        self.source_factory = source_factory
        self.store = store
        self.guard = guard
        self.dispatch = dispatch
        self.run_id = run_id
        self.batch_size = batch_size
        self.retry_delays = retry_delays
        self.circuit_threshold = circuit_threshold
        self.query_failures = Counter()
        self.write_failures = Counter()
        self.batch_range: tuple[int, int] | None = None
        self.stats = Counter(
            scanned=0, differences=0, repaired=0, failed=0, skipped=0, rebuild_submitted=0, rebuild_pending=0
        )

    def _log(
        self,
        stage: str,
        *,
        document_id: int | None = None,
        side: str | None = None,
        error: Exception | None = None,
        **extra: Any,
    ) -> None:
        logger.warning(
            "shared_reconcile run_id=%s batch=%s stage=%s document_id=%s side=%s error_type=%s details=%s",
            self.run_id,
            self.batch_range,
            stage,
            document_id,
            side,
            type(error).__name__ if error else None,
            extra,
        )

    async def _retry(self, operation: Callable[[], Awaitable[T]], stage: str) -> T:
        for attempt in range(len(self.retry_delays) + 1):
            await self.guard()
            try:
                return await operation()
            except ReconcileLockLost:
                raise
            except Exception as exc:
                self._log(stage, error=exc, attempt=attempt + 1)
                if isinstance(exc, (ValueError, TypeError)) or attempt == len(self.retry_delays):
                    raise
                await asyncio.sleep(self.retry_delays[attempt])

    async def _source_read(self, method: str, *args: Any) -> Any:
        async with self.source_factory() as source:
            return await asyncio.wait_for(getattr(source, method)(*args), timeout=30)

    async def run(self) -> dict[str, Any]:
        incomplete = False
        after = 0
        try:
            upper = await self._retry(lambda: self._source_read("upper_bound"), "mysql_upper_bound")
            while after < upper:
                ids = await self._retry(
                    lambda after=after: self._source_read("page_ids", after, upper, self.batch_size),
                    "mysql_page",
                )
                if not ids:
                    break
                if ids != sorted(set(ids)) or ids[0] <= after:
                    raise ValueError("non advancing MySQL cursor")
                after = ids[-1]
                self.batch_range = (ids[0], ids[-1])
                self.stats["scanned"] += len(ids)
                try:
                    snapshots = await self._retry(lambda ids=ids: self._source_read("snapshots", ids), "mysql_snapshot")
                    await self._batch(ids, snapshots)
                except ReconcileLockLost:
                    raise
                except Exception as exc:
                    self.stats["failed"] += len(ids)
                    self._log("batch_failed", error=exc, first_id=ids[0], last_id=ids[-1])
        except Exception as exc:
            incomplete = True
            self._log("scan_stopped", error=exc, last_id=after)
        status = (
            "incomplete"
            if incomplete
            else (
                "completed_with_errors"
                if self.stats["failed"] or self.stats["skipped"]
                else (
                    "completed_with_pending"
                    if self.stats["rebuild_pending"] or self.stats["rebuild_submitted"]
                    else "completed"
                )
            )
        )
        result = {"run_id": self.run_id, "status": status, "last_document_id": after, **dict(self.stats)}
        logger.info("shared_reconcile summary=%s", result)
        return result

    async def _batch(self, ids: list[int], snapshots: dict[int, DocumentSnapshot]) -> None:
        eligible = {}
        for doc_id in ids:
            snapshot = snapshots.get(doc_id)
            if (
                snapshot is None
                or snapshot.skip_reason
                or snapshot.tenant_id != getattr(self.store, "tenant_id", snapshot.tenant_id)
            ):
                self.stats["skipped"] += 1
                self._log(
                    "source_skipped",
                    document_id=doc_id,
                    reason=(snapshot.skip_reason or "tenant_mismatch") if snapshot else "source_missing",
                )
            else:
                eligible[doc_id] = snapshot
        if not eligible:
            return
        observed = {}
        for side in SIDES:
            if max(self.query_failures[side], self.write_failures[side]) >= self.circuit_threshold:
                self.stats["failed"] += len(eligible)
                self._log("backend_suspended", side=side, documents=len(eligible))
                continue
            try:
                observed[side] = await self._retry(
                    lambda side=side: self.store.read(side, list(eligible)),
                    f"{side}_query",
                )
                self.query_failures[side] = 0
            except ReconcileLockLost:
                raise
            except Exception as exc:
                self.query_failures[side] += 1
                self.stats["failed"] += len(eligible)
                self._log("query_failed", side=side, error=exc, documents=len(eligible))

        plans = {side: {} for side in SIDES}
        rebuilds = {}
        # 此循环只比较; 整批差异收集完成后才进入修改阶段。
        for doc_id, snapshot in eligible.items():
            try:
                content_bad = any(
                    self._content_bad(snapshot, data.get(doc_id, []), side) for side, data in observed.items()
                )
                if len(observed) == 2 and not content_bad:
                    content_bad = self._texts(observed["es"][doc_id]) != self._texts(observed["milvus"][doc_id])
                if content_bad:
                    self.stats["differences"] += 1
                    if len(observed) == 2:
                        rebuilds[doc_id] = snapshot
                        self._log("content_rebuild_required", document_id=doc_id)
                    else:
                        self.stats["skipped"] += 1
                        self._log("content_check_deferred", document_id=doc_id)
                    continue
                different = False
                for side, data in observed.items():
                    rows = data[doc_id]
                    fields = set()
                    expected = snapshot.expected_metadata
                    for row in rows:
                        fields.update(k for k, v in expected.items() if row.get(k) != v)
                    if fields:
                        different = True
                        plans[side][doc_id] = MetadataRepair(snapshot, rows)
                        self._log("metadata_difference", document_id=doc_id, side=side, fields=sorted(fields))
                if different:
                    self.stats["differences"] += 1
            except Exception as exc:
                self.stats["failed"] += 1
                self._log("compare_failed", document_id=doc_id, error=exc)

        candidates = sorted(set(rebuilds) | set(plans["es"]) | set(plans["milvus"]))
        # 有界小批锁定, 避免 100 篇长时间占用数据库业务锁。
        for offset in range(0, len(candidates), 10):
            group = candidates[offset : offset + 10]
            queued = []
            try:
                async with self.source_factory() as source:
                    fresh = await asyncio.wait_for(source.snapshots(group, lock=True), timeout=30)
                    valid = []
                    for doc_id in group:
                        current = fresh.get(doc_id)
                        if current is None or current.skip_reason or current.signature != eligible[doc_id].signature:
                            self.stats["skipped"] += 1
                            self._log("source_changed", document_id=doc_id)
                        else:
                            valid.append(doc_id)
                    for doc_id in valid:
                        if doc_id not in rebuilds:
                            continue
                        try:
                            await self.guard()
                            entry_id = await source.queue_rebuild(fresh[doc_id])
                            queued.append((doc_id, entry_id))
                        except ReconcileLockLost:
                            raise
                        except Exception as exc:
                            self.stats["failed"] += 1
                            self._log("rebuild_mark_failed", document_id=doc_id, error=exc)
                    for side in SIDES:
                        updates = [plans[side][i] for i in valid if i in plans[side]]
                        if updates:
                            await self._repair(side, updates)
                # 只有 MySQL pending 意图提交成功后才发送消息。
                for doc_id, entry_id in queued:
                    self.stats["rebuild_pending"] += 1
                    try:
                        await self._retry(lambda entry_id=entry_id: self.dispatch(entry_id), "rebuild_dispatch")
                        self.stats["rebuild_pending"] -= 1
                        self.stats["rebuild_submitted"] += 1
                    except ReconcileLockLost:
                        raise
                    except Exception as exc:
                        self.stats["failed"] += 1
                        self._log("rebuild_dispatch_failed", document_id=doc_id, error=exc)
            except ReconcileLockLost:
                raise
            except Exception as exc:
                self.stats["failed"] += len(group)
                self._log("repair_group_failed", error=exc, document_ids=group)

    async def _repair(self, side: str, plans: list[MetadataRepair]) -> None:
        if self.write_failures[side] >= self.circuit_threshold:
            self.stats["failed"] += len(plans)
            self._log("writes_suspended", side=side, document_ids=[p.snapshot.document_id for p in plans])
            return
        remaining = plans
        for attempt in range(len(self.retry_delays) + 1):
            await self.guard()
            try:
                results = await self.store.repair(side, remaining)
            except ReconcileLockLost:
                raise
            except Exception as exc:
                self._log("bulk_failed", side=side, error=exc, documents=len(remaining))
                if len(remaining) > 1:
                    middle = len(remaining) // 2
                    await self._repair(side, remaining[:middle])
                    await self._repair(side, remaining[middle:])
                    return
                results = {p.snapshot.document_id: type(exc).__name__ for p in remaining}
            succeeded = [
                p for p in remaining if p.snapshot.document_id in results and results[p.snapshot.document_id] is None
            ]
            if succeeded:
                try:
                    actual = await self._retry(
                        lambda succeeded=succeeded: self.store.read(side, [p.snapshot.document_id for p in succeeded]),
                        "repair_verify",
                    )
                    for plan in succeeded:
                        s = plan.snapshot
                        rows = actual.get(s.document_id, [])
                        expected = s.expected_metadata
                        if self._content_bad(s, rows, side) or any(
                            any(row.get(k) != v for k, v in expected.items()) for row in rows
                        ):
                            results[s.document_id] = "verification_failed"
                        else:
                            self.stats["repaired"] += 1
                            self.stats[f"{side}_repaired"] += 1
                except ReconcileLockLost:
                    raise
                except Exception as exc:
                    self._log("verify_failed", side=side, error=exc)
                    for p in succeeded:
                        results[p.snapshot.document_id] = "verification_unavailable"
            remaining = [p for p in remaining if results.get(p.snapshot.document_id, "missing_result") is not None]
            if not remaining:
                self.write_failures[side] = 0
                return
            if attempt < len(self.retry_delays):
                await asyncio.sleep(self.retry_delays[attempt])
        self.stats["failed"] += len(remaining)
        self.write_failures[side] += 1
        for p in remaining:
            self._log(
                "repair_failed",
                document_id=p.snapshot.document_id,
                side=side,
                reason=results.get(p.snapshot.document_id, "missing_result"),
            )

    def _content_bad(self, snapshot: DocumentSnapshot, rows: list[dict[str, Any]], side: str) -> bool:
        if not rows:
            return True
        indexes = []
        for row in rows:
            if not isinstance(row.get("text"), str):
                return True
            if any(
                row.get(k) != value
                for k, value in {
                    "canonical_document_id": snapshot.document_id,
                    "canonical_version_id": snapshot.version_id,
                    "content_file_id": snapshot.file_id,
                    "content_generation": snapshot.generation,
                }.items()
            ) or str(row.get("embedding_model_id")) != str(self.store.embedding_model_id):
                return True
            indexes.append(int(row["chunk_index"]))
            if side == "milvus":
                vector = row.get("vector")
                if (
                    vector is None
                    or len(vector) != self.store.vector_dimension
                    or not all(math.isfinite(v) for v in vector)
                ):
                    return True
        return len(set(indexes)) != len(indexes) or sorted(indexes) != list(range(len(indexes)))

    @staticmethod
    def _texts(rows: list[dict[str, Any]]) -> dict[int, str | None]:
        return {int(row["chunk_index"]): row.get("text") for row in rows}
