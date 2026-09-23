"""任务内部批量投影; 完整初始轮结束后才处理失败集合。"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import asdict, replace
from typing import Any

from bisheng.knowledge.domain.contracts.document_projection_batch import ProjectionBatchContext
from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentProjectionIdentity,
    ContentUpsertRequest,
    MembershipUpdateRequest,
    SharedContentChunk,
    SharedProjectionWrite,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_document_projection_service import (
    ProjectionDependencyPending,
)
from bisheng.knowledge.domain.services.shared_space_projection_support import (
    MEMBERSHIP_ENTRY_TYPES,
    aggregate_active_knowledge_ids,
)

logger = logging.getLogger(__name__)


async def run_projection_rounds(
    entry_ids: list[int],
    *,
    execute: Callable[[list[int]], Awaitable[dict[int, str]]],
    batch_size: int,
    max_attempts: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    document_keys: dict[int, int] | None = None,
) -> dict[int, str]:
    if batch_size < 1 or max_attempts < 1:
        raise ValueError("batch size and attempt limit must be positive")
    pending = list(dict.fromkeys(entry_ids))
    results = {}
    for attempt in range(max_attempts):
        if not pending:
            break
        if attempt:
            await sleep(min(2**attempt, 30))
        groups = defaultdict(list)
        for entry_id in pending:
            groups[(document_keys or {}).get(entry_id, entry_id)].append(entry_id)
        documents = list(groups.values())
        failures = []
        for offset in range(0, len(documents), batch_size):
            batch = [entry_id for group in documents[offset : offset + batch_size] for entry_id in group]
            outcomes = await execute(batch)
            results.update(outcomes)
            failures.extend(entry_id for entry_id, status in outcomes.items() if status == "failed")
        pending = failures
    return results


class DocumentProjectionBatchService:
    def __init__(
        self,
        *,
        repository_factory: Callable,
        writer: Any,
        chunk_loader: Callable | None = None,
        finalizer: Callable,
        chunk_embedder: Callable | None = None,
        rebuild_dispatch: Callable | None = None,
        allow_content_rebuild: bool = False,
        handoff_owner: str | None = None,
        content_manifests: list[dict] | None = None,
        batch_size: int = 100,
        max_attempts: int = 4,
    ) -> None:
        self.repository_factory = repository_factory
        self.writer = writer
        self.chunk_loader = chunk_loader
        self.finalizer = finalizer
        self.chunk_embedder = chunk_embedder
        self.rebuild_dispatch = rebuild_dispatch
        self.allow_content_rebuild = allow_content_rebuild
        self.handoff_owner = handoff_owner
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.owner = None
        self.lost = None
        self.content_manifests = {
            ContentProjectionIdentity(**item["identity"]): item["digest"] for item in (content_manifests or [])
        }

    @staticmethod
    def _content_manifest(chunks: Sequence[SharedContentChunk]) -> str:
        payload = [(chunk.chunk_index, chunk.text) for chunk in sorted(chunks, key=lambda item: item.chunk_index)]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()

    async def guard(self, expected_ids: list[int] | None = None) -> None:
        if self.lost:
            raise RuntimeError("projection batch heartbeat failed") from self.lost
        async with self.repository_factory() as repository:
            await repository.renew(self.owner, expected_ids)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await self.guard()
            except Exception as exc:
                self.lost = exc
                logger.exception("projection batch heartbeat failed owner=%s", self.owner)
                return

    async def run(self, tenant_id: int, entry_ids: list[int], owner: str) -> dict[int, str]:
        self.owner = owner
        self.tenant_id = tenant_id
        # 输入仅在内存保存 ID; 正文与向量只加载当前内部批次。
        document_keys = {}
        for offset in range(0, len(entry_ids), 500):
            async with self.repository_factory() as repository:
                rows = await repository.find_by_ids(entry_ids[offset : offset + 500])
                if any(int(row.tenant_id) != tenant_id for row in rows):
                    raise ValueError("projection batch cannot cross tenants")
                document_keys.update({row.id: row.reference_document_id or -row.id for row in rows})
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            return await run_projection_rounds(
                entry_ids,
                execute=self._execute,
                batch_size=self.batch_size,
                max_attempts=self.max_attempts,
                document_keys=document_keys,
            )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            # 中断后保留 pending/failed 及计数, 扫描可重新接管。
            async with self.repository_factory() as repository:
                await repository.release(owner)

    async def _plan(
        self,
        context: ProjectionBatchContext,
    ) -> tuple[list[SharedProjectionWrite], dict[int, str], set[int]]:
        memberships = defaultdict(list)
        claimed = defaultdict(list)
        for row in context.entries:
            memberships[row.reference_document_id].append(row)
        for row in context.claimed:
            claimed[row.reference_document_id].append(row)
        plans, errors, identities = [], {}, {}
        rebuild_ids: set[int] = set()
        for document_id, targets in claimed.items():
            entries = memberships[document_id]
            document = context.documents.get(document_id)
            eligible = []
            for row in targets:
                # 删除必须等新管理入口完成; 本轮先推进其余可执行入口。
                requires_manager = row.entry_status == "deleting" and row.entry_type in {
                    "publish",
                    "projection_tombstone",
                }
                manager_ready = any(
                    candidate.entry_type == "manager"
                    and candidate.entry_status == "active"
                    and candidate.projection_status == "ready"
                    and candidate.applied_content_generation >= row.desired_content_generation
                    and candidate.applied_entry_generation >= candidate.desired_entry_generation
                    for candidate in entries
                )
                if (
                    requires_manager
                    and (document is None or document.lifecycle_status == "active")
                    and not manager_ready
                ):
                    errors[row.id] = "waiting_dependency:destination manager projection is not ready"
                else:
                    eligible.append(row)
            if not eligible:
                continue
            try:
                knowledge_ids = aggregate_active_knowledge_ids(entries)
                content_generation = max(
                    [row.desired_content_generation for row in eligible]
                    + [int(document.content_generation) if document else 0]
                )
                membership_generation = max(
                    [content_generation]
                    + [
                        row.desired_entry_generation
                        for row in entries
                        if row.entry_status == "active" and row.entry_type in MEMBERSHIP_ENTRY_TYPES
                    ]
                )
                live = any(
                    row.entry_status == "active" and row.entry_type != "projection_tombstone" for row in eligible
                )
                if live:
                    version = context.versions.get(document.primary_version_id) if document else None
                    if (
                        document is None
                        or int(document.tenant_id) != self.tenant_id
                        or version is None
                        or version.document_id != document_id
                    ):
                        raise ProjectionDependencyPending("canonical document or primary version is unavailable")
                    if int(document.content_generation) != int(content_generation):
                        raise ProjectionDependencyPending("canonical content generation changed")
                if live and knowledge_ids:
                    identities[document_id] = ContentProjectionIdentity(
                        tenant_id=self.tenant_id,
                        canonical_document_id=document_id,
                        canonical_version_id=version.id,
                        content_file_id=version.knowledge_file_id,
                        content_generation=content_generation,
                        embedding_model_id=str(self.writer.schema_spec.embedding_model_id),
                    )
                plans.append(
                    SharedProjectionWrite(
                        membership=MembershipUpdateRequest(
                            tenant_id=self.tenant_id,
                            canonical_document_id=document_id,
                            knowledge_ids=knowledge_ids,
                            membership_generation=membership_generation,
                            content_generation=content_generation,
                        ),
                    )
                )
            except Exception as exc:
                logger.exception("projection batch planning failed document_id=%s", document_id)
                errors.update({row.id: f"{type(exc).__name__}:{exc}" for row in eligible})
        if not identities:
            return plans, errors, rebuild_ids
        claimed_ids = [row.id for row in context.claimed]
        try:
            inspections = await self.writer.inspect_projection_content(
                list(identities.values()),
                guard=lambda: self.guard(claimed_ids),
            )
        except Exception as exc:
            logger.exception("projection content inspection failed owner=%s", self.owner)
            for document_id in identities:
                errors.update({row.id: f"content_probe_failed:{exc}" for row in claimed[document_id]})
            return (
                [plan for plan in plans if plan.membership.canonical_document_id not in identities],
                errors,
                rebuild_ids,
            )
        resolved = []
        for plan in plans:
            document_id = plan.membership.canonical_document_id
            identity = identities.get(document_id)
            if identity is None:
                resolved.append(plan)
                continue
            try:
                inspection = inspections[document_id]
                expected_manifest = self.content_manifests.get(identity)
                if (
                    inspection.action in {"reuse", "embed"}
                    and expected_manifest
                    and self._content_manifest(inspection.chunks) != expected_manifest
                ):
                    # 写入中途失败可能让两端只剩相同前缀, 不能误认为分块完整。
                    inspection = replace(
                        inspection, action="rebuild", reason="stored content differs from attempted content"
                    )
                logger.info(
                    "projection content decision document_id=%s action=%s reason=%s",
                    document_id,
                    inspection.action,
                    inspection.reason,
                )
                physical = context.files.get(identity.content_file_id)
                if physical is not None and (
                    int(physical.tenant_id) != self.tenant_id
                    or physical.deleted_at is not None
                    or physical.status == KnowledgeFileStatus.VIOLATION.value
                ):
                    raise ProjectionDependencyPending("canonical file is unavailable for content projection")
                chunks = inspection.chunks
                if inspection.action in {"embed", "rebuild"}:
                    if not physical or physical.status != KnowledgeFileStatus.SUCCESS.value:
                        raise ProjectionDependencyPending("waiting for canonical file parsing to complete")
                    if inspection.action == "rebuild" and not physical.object_name:
                        raise ProjectionDependencyPending("canonical original file is unavailable")
                    if not self.allow_content_rebuild:
                        # 同文档一起交接, 避免默认 Worker 与解析 Worker 分占入口租约。
                        for row in claimed[document_id]:
                            rebuild_ids.add(row.id)
                            errors.pop(row.id, None)
                        continue
                    await self.guard(claimed_ids)
                    if inspection.action == "embed":
                        if self.chunk_embedder is None:
                            raise ProjectionDependencyPending("stored text embedding is unavailable")
                        chunks = await self.chunk_embedder(physical, chunks)
                    else:
                        if self.chunk_loader is None:
                            raise ProjectionDependencyPending("original content loader is unavailable")
                        chunks = await self.chunk_loader(physical)
                elif inspection.action != "reuse":
                    raise ProjectionDependencyPending(inspection.reason)
                if not chunks:
                    raise ValueError("content inspection or recovery returned no chunks")
                self.content_manifests[identity] = self._content_manifest(chunks)
                resolved.append(
                    replace(plan, content=ContentUpsertRequest(identity, plan.membership.knowledge_ids, chunks))
                )
            except Exception as exc:
                logger.exception("projection content recovery failed document_id=%s", document_id)
                errors.update({row.id: f"{type(exc).__name__}:{exc}" for row in claimed[document_id]})
        return resolved, errors, rebuild_ids

    async def _execute(self, ids: list[int]) -> dict[int, str]:
        await self.guard()
        async with self.repository_factory() as repository:
            context = await repository.claim_batch(
                ids,
                self.owner,
                self.max_attempts,
                handoff_owner=self.handoff_owner,
            )
        results = dict.fromkeys(ids, "not_claimed")
        if not context.claimed:
            return results
        plans, errors, rebuild_ids = await self._plan(context)
        claimed_ids = [row.id for row in context.claimed]
        await self.guard(claimed_ids)
        try:
            failed_documents = (
                await self.writer.apply_projection_batch(
                    plans,
                    guard=lambda: self.guard(claimed_ids),
                )
                if plans
                else {}
            )
        except Exception as exc:
            logger.exception("projection batch storage failed owner=%s", self.owner)
            failed_documents = {plan.membership.canonical_document_id: f"{type(exc).__name__}:{exc}" for plan in plans}
        for row in context.claimed:
            if row.reference_document_id in failed_documents:
                errors[row.id] = failed_documents[row.reference_document_id]
            # invalid 入口的权限清理必须先于完成状态提交。
            if row.entry_status == "invalid" and row.id not in errors and row.id not in rebuild_ids:
                try:
                    await self.finalizer(row)
                except Exception as exc:
                    logger.exception("invalid projection cleanup failed entry_id=%s", row.id)
                    errors[row.id] = f"{type(exc).__name__}:{exc}"
        await self.guard(claimed_ids)
        reservation = f"rebuild:{uuid.uuid4().hex}" if rebuild_ids else None
        async with self.repository_factory() as repository:
            outcomes = await repository.settle(
                context.claimed,
                self.owner,
                errors,
                self.max_attempts,
                rebuild_ids=rebuild_ids,
                rebuild_owner=reservation,
            )
        results.update(outcomes)
        rebuilding = [row for row in context.claimed if outcomes.get(row.id) == "rebuild_pending"]
        if rebuilding:
            try:
                if self.rebuild_dispatch is None:
                    raise RuntimeError("content rebuild dispatcher is unavailable")
                document_ids = {row.reference_document_id for row in rebuilding}
                manifests = [
                    {"identity": asdict(identity), "digest": digest}
                    for identity, digest in self.content_manifests.items()
                    if identity.canonical_document_id in document_ids
                ]
                options = {"content_manifests": manifests} if manifests else {}
                await self.rebuild_dispatch(self.tenant_id, [row.id for row in rebuilding], reservation, **options)
                results.update({row.id: "rebuild_queued" for row in rebuilding})
            except Exception as exc:
                logger.exception("projection content rebuild publish failed owner=%s", self.owner)
                async with self.repository_factory() as repository:
                    results.update(
                        await repository.settle(
                            rebuilding,
                            reservation,
                            {row.id: f"rebuild_publish_failed:{exc}" for row in rebuilding},
                            self.max_attempts,
                        )
                    )
                    await repository.release(reservation)
        finalized, cleanup_errors = [], {}
        for row in context.claimed:
            if outcomes.get(row.id) != "finalizing":
                continue
            finalized.append(row)
            try:
                await self.guard()
                if row.entry_status != "invalid":
                    await self.finalizer(row)
            except Exception as exc:
                logger.exception("projection finalization failed entry_id=%s", row.id)
                cleanup_errors[row.id] = f"{type(exc).__name__}:{exc}"
        if finalized:
            async with self.repository_factory() as repository:
                results.update(
                    await repository.settle(
                        finalized,
                        self.owner,
                        cleanup_errors,
                        self.max_attempts,
                        finalizing=True,
                    )
                )
        return results
