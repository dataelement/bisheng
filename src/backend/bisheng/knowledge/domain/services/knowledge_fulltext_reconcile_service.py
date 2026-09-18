"""每日全量对账协调: 批次异常隔离, 当前任务不执行重新解析。"""

import asyncio
import random
import time
from datetime import datetime
from uuid import uuid4

from loguru import logger

from bisheng.knowledge.domain.contracts.fulltext_reconcile import (
    Mutation,
    ReconcileDependencyUnavailable,
    ReconcileLeaseLost,
    matches,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import KnowledgeFulltextDocumentService
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextChunkCorruptedError,
    KnowledgeFulltextChunkNotReadyError,
    KnowledgeFulltextRebuildService,
)


class KnowledgeFulltextReconcileService:
    def __init__(
        self, *, repository_factory, es, guard, now=datetime.now, batch_size=200, body_batch_size=20, budget_seconds=240
    ):
        self.repository_factory = repository_factory
        self.es = es
        self.guard = guard
        self.now = now
        self.batch_size = batch_size
        self.body_batch_size = body_batch_size
        self.budget_seconds = budget_seconds
        self.document = KnowledgeFulltextDocumentService(index_schema_version=1)
        self.rebuild = KnowledgeFulltextRebuildService()
        self.batch_failures = 0
        self.retry_delays = (2, 5)

    async def _retry(self, operation):
        from elastic_transport import ConnectionError as ESConnectionError
        from elasticsearch import ApiError
        from sqlalchemy.exc import OperationalError

        for attempt in range(len(self.retry_delays) + 1):
            await self.guard()
            try:
                return await asyncio.wait_for(operation(), timeout=30)
            except (
                ConnectionError,
                ESConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
                OperationalError,
                ApiError,
            ) as exc:
                if isinstance(exc, ApiError) and exc.status_code not in {429, 502, 503, 504}:
                    raise
                if attempt == len(self.retry_delays):
                    raise
                logger.warning("fulltext reconcile short retry attempt={} error={}", attempt + 1, type(exc).__name__)
                await asyncio.sleep(self.retry_delays[attempt] + random.uniform(0, 0.2))

    async def run(self, *, create: bool = True) -> dict:
        await self.guard()
        async with self.repository_factory() as repo:
            upper = await repo.source.upper_bound() if create else 0
            run = await repo.state.load_or_create(self.now(), upper, create=create)
            if run is None:
                return {"status": "idle"}
            run_id = run.id
            if run.status in {"completed", "completed_with_errors"}:
                return {"run_id": run.id, "status": run.status, "counters": run.counters}
        deadline = time.monotonic() + self.budget_seconds
        while time.monotonic() < deadline:
            await self.guard()
            async with self.repository_factory() as repo:
                run = await repo.state.load_or_create(self.now(), 0, create=False)
                if run is None:
                    return {"run_id": run_id, "status": "completed"}
                phase = run.phase
                if phase == "forward":
                    ids = await repo.source.page_ids(run.cursor, run.upper_id, self.batch_size)
                elif phase == "retry":
                    ids = [i.file_id for i in await repo.state.due(run.id, self.now(), self.batch_size)]
                else:
                    ids = None
            if phase == "reverse":
                ids = await self._retry(lambda cursor=run.cursor: self.es.reverse_page(cursor, self.batch_size))
                if run.cursor == 0 and getattr(self.es, "unkeyed_count", 0):
                    async with self.repository_factory() as repo:
                        await repo.state.checkpoint(
                            run.id,
                            phase,
                            run.cursor,
                            {0: f"invalid_es_identity:unkeyed_count={self.es.unkeyed_count}"},
                            {},
                            self.now(),
                        )
            if not ids:
                async with self.repository_factory() as repo:
                    if phase == "retry":
                        status = await repo.state.finish_scan(run.id, self.now())
                        logger.info(
                            "fulltext reconcile round run_id={} status={} counters={}", run.id, status, run.counters
                        )
                        if create and status != "waiting" and run.day != self.now().date().isoformat():
                            next_run = await repo.state.load_or_create(self.now(), await repo.source.upper_bound())
                            run_id = next_run.id
                            continue
                        return {"run_id": run.id, "status": status, "counters": run.counters}
                    await repo.state.transition(run.id, "reverse" if phase == "forward" else "retry", self.now())
                continue
            if phase != "retry" and (ids != sorted(set(ids)) or ids[0] <= run.cursor):
                raise RuntimeError("non advancing reconcile cursor")
            for start in range(0, len(ids), self.body_batch_size):
                if time.monotonic() >= deadline:
                    return {"run_id": run_id, "status": "continuation_pending"}
                group = ids[start : start + self.body_batch_size]
                identity_errors = getattr(self.es, "identity_errors", {}) if phase == "reverse" else {}
                operation = self.reverse_batch if phase == "reverse" else self.batch
                failures, successes = await operation([i for i in group if i not in identity_errors], run.id)
                failures.update({i: identity_errors[i] for i in group if i in identity_errors})
                await self.guard()
                async with self.repository_factory() as repo:
                    await repo.state.checkpoint(run.id, phase, group[-1], failures, successes, self.now())
        return {"run_id": run_id, "status": "continuation_pending"}

    async def reverse_batch(self, ids, run_id):
        if not ids:
            return {}, {}
        try:
            async with self.repository_factory() as repo:
                snapshots = await repo.source.snapshots(ids)
            candidates, failures, successes = [], {}, {}
            for file_id in ids:
                snapshot = snapshots.get(file_id)
                if isinstance(snapshot, Exception):
                    failures[file_id] = "source_relation_failed"
                elif snapshot is None or self.document.decide(snapshot).value == "delete":
                    candidates.append(file_id)
                else:
                    # 正向已承担正文校验; 反向只找残留, 避免对所有合法文件重读 RAG。
                    successes[file_id] = "reverse_existing"
            bad, good = await self.batch(candidates, run_id)
            failures.update(bad)
            successes.update(good)
            if not candidates:
                self.batch_failures = 0
            return failures, successes
        except (ReconcileLeaseLost, ReconcileDependencyUnavailable):
            raise
        except Exception as exc:
            logger.exception("fulltext reconcile reverse batch failed run_id={}", run_id)
            self.batch_failures += 1
            if self.batch_failures >= 3:
                raise ReconcileDependencyUnavailable("three reverse batch failures") from exc
            return {i: f"batch:{type(exc).__name__}" for i in ids}, {}

    async def batch(self, ids: list[int], run_id: str) -> tuple[dict, dict]:
        failures, successes = {}, {}
        for start in range(0, len(ids), self.body_batch_size):
            group = ids[start : start + self.body_batch_size]
            await self.guard()
            try:
                bad, good = await self._batch(group, run_id)
                failures.update(bad)
                successes.update(good)
                self.batch_failures = 0
            except ReconcileLeaseLost:
                raise
            except Exception as exc:
                logger.exception(
                    "fulltext reconcile batch failed run_id={} first={} last={}", run_id, group[0], group[-1]
                )
                failures.update({i: f"batch:{type(exc).__name__}" for i in group})
                self.batch_failures += 1
                if self.batch_failures >= 3:
                    raise ReconcileDependencyUnavailable(
                        "three consecutive batch failures; resume from checkpoint"
                    ) from exc
        return failures, successes

    async def _repair(self, snapshot, run_id, *, wait_for_chunks=False):
        try:
            async with self.repository_factory() as repo:
                if wait_for_chunks and not await repo.state.has_issue(run_id, snapshot.file_id):
                    return "chunk_not_ready"
                return await repo.request_repair(snapshot, self.now())
        except ReconcileLeaseLost:
            raise
        except Exception as exc:
            logger.exception("fulltext reconcile repair intent failed file_id={}", snapshot.file_id)
            return f"repair_intent:{type(exc).__name__}"

    async def _batch(self, ids: list[int], run_id: str) -> tuple[dict, dict]:
        failures, successes, eligible = {}, {}, []
        async with self.repository_factory() as repo:
            snapshots = await repo.source.snapshots(ids)
            for file_id in ids:
                snapshot = snapshots.get(file_id)
                if isinstance(snapshot, Exception):
                    failures[file_id] = f"source:{type(snapshot).__name__}"
                elif snapshot is not None and self.document.decide(snapshot).value == "upsert":
                    eligible.append(snapshot)
            sources = await repo.source.chunk_sources(eligible) if eligible else {}
        observed = await self._retry(lambda: self.es.read(ids))
        if ids and all(isinstance(observed.get(i), Exception) or observed.get(i) is None for i in ids):
            raise ReconcileDependencyUnavailable("all fulltext mget items failed")
        chunks = await asyncio.wait_for(
            self.es.chunks([s for s in sources.values() if not isinstance(s, Exception)]), timeout=90
        )
        mutations = []
        rebuilt_sources = {}
        for file_id in ids:
            if file_id in failures:
                continue
            snapshot = snapshots.get(file_id)
            actual = observed.get(file_id)
            if actual is None or isinstance(actual, Exception):
                failures[file_id] = "es_read_failed"
                continue
            action = self.document.decide(snapshot).value if snapshot else "delete"
            if action == "keep":
                if (
                    snapshot.status == "2"
                    and snapshot.logical_document_id is not None
                    and snapshot.projection_status == "failed"
                ):
                    failures[file_id] = await self._repair(snapshot, run_id)
                else:
                    failures[file_id] = "waiting_source"
                continue
            try:
                expected = None
                if action == "upsert":
                    source = sources.get(file_id)
                    data = chunks.get(file_id)
                    if isinstance(source, Exception):
                        raise source
                    if isinstance(data, Exception):
                        raise data
                    if data is None:
                        raise RuntimeError("missing chunk batch response")
                    key = (
                        source.index_name,
                        source.canonical_document_id,
                        source.canonical_version_id,
                        source.content_generation,
                        tuple(c.es_id for c in data),
                    )
                    rebuilt = rebuilt_sources.get(key)
                    if rebuilt is None:
                        rebuilt = self.rebuild.rebuild(data, file_id=file_id, knowledge_id=snapshot.knowledge_id)
                        rebuilt_sources[key] = rebuilt
                    expected = self.document.build(
                        snapshot,
                        content=rebuilt.content,
                        chunk_count=rebuilt.chunk_count,
                        content_hash=rebuilt.content_hash,
                        sync_revision=1,
                        indexed_at=self.now(),
                    ).model_dump(mode="json")
                if matches(expected, actual):
                    successes[file_id] = "consistent"
                else:
                    mutations.append(Mutation(file_id, expected, actual))
            except (KnowledgeFulltextChunkCorruptedError, KnowledgeFulltextChunkNotReadyError) as exc:
                # 初次缺失只登记, 给正常分块写入留出时间。
                failures[file_id] = await self._repair(
                    snapshot, run_id, wait_for_chunks=isinstance(exc, KnowledgeFulltextChunkNotReadyError)
                )
            except Exception as exc:
                logger.exception("fulltext reconcile file comparison failed file_id={}", file_id)
                failures[file_id] = f"compare:{type(exc).__name__}"
        if not mutations:
            return failures, successes
        new_ids = [m.file_id for m in mutations if m.document is not None and m.observed.source is None]
        if new_ids:
            try:
                totals = await self._retry(lambda: self.es.totals(new_ids))
                for mutation in mutations:
                    if mutation.file_id in new_ids:
                        mutation.document.update(totals[mutation.file_id])
                        mutation.document["engagement_updated_at"] = self.now().isoformat()
            except Exception as exc:
                if isinstance(exc, ReconcileLeaseLost):
                    raise
                logger.exception("fulltext reconcile engagement batch failed")
                failures.update(dict.fromkeys(new_ids, "engagement_read_failed"))
                mutations = [m for m in mutations if m.file_id not in new_ids]
                if not mutations:
                    return failures, successes
        owner = f"reconcile:{uuid4().hex}"
        await self.guard()
        async with self.repository_factory() as repo:
            claimed, rejected = await repo.claim_mutations(mutations, snapshots, owner, self.now())
            failures.update(rejected)
            changes = [m for m in mutations if m.file_id in claimed]
            if not changes:
                return failures, successes
            await self.guard()
            # 条目写入失败或结果未知都通过实际回读确认; 不盲目整批重放。
            try:
                outcomes = await asyncio.wait_for(self.es.write(changes), timeout=60)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                outcomes = {m.file_id: exc for m in changes}
            await self.guard()
            actual = await self._retry(lambda: self.es.read([m.file_id for m in changes]))
            verified = set()
            for change in changes:
                value = actual.get(change.file_id)
                if value is not None and not isinstance(value, Exception) and matches(change.document, value):
                    verified.add(change.file_id)
                    successes[change.file_id] = "deleted" if change.document is None else "repaired"
                else:
                    failures[change.file_id] = (
                        "verify_failed" if outcomes.get(change.file_id) is None else "write_or_verify_failed"
                    )
            await repo.finish_mutations(claimed, verified, owner, self.now())
        return failures, successes
