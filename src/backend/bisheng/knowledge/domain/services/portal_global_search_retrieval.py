"""门户文件检索的共享存储适配；范围来自已解析的门户发现集合。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from typing import Any

from loguru import logger

from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
from bisheng.knowledge.domain.contracts.retrieval_scope import RetrievalScope
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_retrieval_scope_resolver import (
    RetrievalScopeResolverSettings,
    SqlKnowledgeRetrievalScopeResolver,
)
from bisheng.knowledge.rag.async_retrieval_runtime import get_async_retrieval_runtime
from bisheng.knowledge.rag.shared_space_storage import (
    SharedSpaceStorageReader,
    SharedStoreSchemaSpec,
    aresolve_space_shared_routing,
    get_shared_storage_conf,
    shared_collection_name,
    tenant_target_embedding_model_id,
)
from bisheng.llm.domain import LLMService


@dataclass
class PortalSharedRecall:
    chunks: list[Any]
    metadata_space_ids: list[int]


async def resolve_portal_shared_snapshot(owner: Any, spaces: list[Any]) -> Any:
    """同租户 SPACE 共用一条权威路由，不按知识库反复读取路由表。"""
    if not spaces:
        return None
    tenant_id = int(owner.login_user.tenant_id)
    if any(int(space.tenant_id or 0) != tenant_id for space in spaces):
        raise SharedStorageContractError(
            SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE, "global search crosses tenant boundary", tenant_id=tenant_id
        )
    if any(int(space.type) != KnowledgeTypeEnum.SPACE.value for space in spaces):
        raise SharedStorageContractError(
            SharedStorageErrorCode.ROUTING_VERSION_MISMATCH, "global search requires SPACE routing", tenant_id=tenant_id
        )
    snapshot = await aresolve_space_shared_routing(tenant_id, KnowledgeTypeEnum.SPACE.value)
    if snapshot is not None and int(snapshot.tenant_id) != tenant_id:
        raise SharedStorageContractError(
            SharedStorageErrorCode.ROUTING_VERSION_MISMATCH, "shared route tenant mismatch", tenant_id=tenant_id
        )
    return snapshot


class PortalGlobalSearchRetriever:
    """每个兼容权限组各召回一次，映射与授权只处理有界候选。"""

    def __init__(
        self, *, owner: Any, req: Any, spaces: list[Any], snapshot: Any, reader: Any = None, runtime: Any = None
    ) -> None:
        self.owner = owner
        self.req = req
        self.spaces = spaces
        self.snapshot = snapshot
        self.reader = reader
        self.runtime = runtime
        self.permissions: dict[int, bool] = {}
        self.stats = {
            "groups": 0,
            "es_calls": 0,
            "vector_calls": 0,
            "embedding_calls": 0,
            "raw_hits": 0,
            "mapped_hits": 0,
            "denied_entries": 0,
            "failed_lanes": 0,
        }

    async def retrieve(self, *, tag_file_ids: list[int] | None) -> PortalSharedRecall:
        self.runtime = self.runtime or await get_async_retrieval_runtime()
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._retrieve(tag_file_ids), timeout=self.runtime.config.total_timeout_seconds
            )
        finally:
            logger.info(
                "portal_global_search tenant={} routing_version={} spaces={} stats={} elapsed_ms={}",
                self.snapshot.tenant_id,
                self.snapshot.routing_version,
                len(self.spaces),
                self.stats,
                int((time.monotonic() - started) * 1000),
            )

    async def _retrieve(self, tag_file_ids: list[int] | None) -> PortalSharedRecall:
        discovery = self.owner._portal_discovery_result
        if discovery is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SCOPE_SPACE_NOT_VISIBLE, "portal discovery context missing"
            )
        if tag_file_ids == []:
            return PortalSharedRecall([], [])
        for name in ("knowledge_file_repo", "doc_repo", "version_repo"):
            if getattr(self.owner, name, None) is None:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.RETRIEVAL_BACKEND_UNAVAILABLE, "global search repositories missing"
                )
        ids = {int(space.id) for space in self.spaces}
        public_ids = await self.owner._get_shougang_portal_public_space_ids(sorted(ids), spaces=self.spaces)
        content_ids = ids & (set(public_ids) | set(discovery.explicitly_visible_space_ids))
        metadata_ids = sorted((ids & set(discovery.discoverable_space_ids)) - content_ids)
        grants = {
            int(file_id): int(space_id)
            for file_id, space_id in discovery.explicit_file_space_by_id.items()
            if int(space_id) in ids - content_ids
        }
        groups = []
        full_scope = await self._scope(content_ids, tag_file_ids)
        if full_scope is not None:
            groups.append(full_scope)
        granted_ids = sorted(set(grants) & set(tag_file_ids)) if tag_file_ids is not None else sorted(grants)
        grant_scope = await self._scope(set(grants.values()), granted_ids, expected_parents=grants)
        if grant_scope is not None:
            groups.append(grant_scope)
        self.stats["groups"] = len(groups)
        if not groups:
            return PortalSharedRecall([], metadata_ids)

        resolver = self._resolver()
        filters = []
        for scope in groups:
            document_ids, version_ids = await resolver.resolve_explicit_canonical_constraints(scope)
            filters.append(
                resolver.build_backend_filter(
                    scope, canonical_document_ids=document_ids, canonical_version_ids=version_ids
                )
            )
        model_id = tenant_target_embedding_model_id(self.snapshot)
        vector = None
        started = time.monotonic()
        try:
            self.stats["embedding_calls"] += 1

            async def embed() -> list[float]:
                model = await LLMService.get_bisheng_knowledge_embedding(
                    model_id=model_id, invoke_user_id=self.owner.login_user.user_id
                )
                return await self.runtime.embed_query(model, self.req.q.strip())

            vector = await asyncio.wait_for(embed(), self.runtime.config.embedding_timeout_seconds)
        except SharedStorageContractError:
            raise
        except Exception as exc:
            # 嵌入失败不影响独立的全文召回；不改用其他模型或旧索引。
            logger.warning("portal_global_search embedding_failed error={}", type(exc).__name__)
        logger.info("portal_global_search stage=embedding elapsed_ms={}", int((time.monotonic() - started) * 1000))
        if vector is not None and self.snapshot.schema_fingerprint:
            # 与共享迁移使用同一规格计算指纹，模型/维度错误不能伪装成单路故障。
            expected = SharedStoreSchemaSpec(
                embedding_model_id=model_id,
                dimension=len(vector),
                knowledge_ids_max_capacity=get_shared_storage_conf().knowledge_ids_max_capacity,
            ).fingerprint()
            if expected != self.snapshot.schema_fingerprint:
                raise SharedStorageContractError(
                    SharedStorageErrorCode.SCHEMA_FINGERPRINT_MISMATCH,
                    "global query embedding does not match shared schema",
                    tenant_id=self.snapshot.tenant_id,
                )
        self.reader = self.reader or SharedSpaceStorageReader(
            tenant_id=self.snapshot.tenant_id,
            collection_name=self.snapshot.collection_name or shared_collection_name(self.snapshot.tenant_id),
            expected_routing_version=self.snapshot.routing_version,
            milvus_runtime=self.runtime,
        )
        jobs = []
        for backend_filter in filters:
            jobs.extend([self._query("es", backend_filter, vector), self._query("vector", backend_filter, vector)])
        tasks = [asyncio.create_task(job) for job in jobs]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, (SharedStorageContractError, asyncio.CancelledError)):
                raise result

        chunks = []
        # Repository 共用请求会话，映射阶段串行，避免 AsyncSession 并发使用。
        for index, scope in enumerate(groups):
            if all(isinstance(result, BaseException) for result in results[index * 2 : index * 2 + 2]):
                logger.warning("portal_global_search group={} both_backends_failed=true", index)
            for lane, result in zip(("es", "vector"), results[index * 2 : index * 2 + 2]):
                if isinstance(result, BaseException):
                    self.stats["failed_lanes"] += 1
                    logger.warning("portal_global_search lane={} failed error={}", lane, type(result).__name__)
                    continue
                self.stats["raw_hits"] += len(result)
                mapped = await resolver.map_and_authorize_hits(
                    scope, result, entry_batch_checker=self._authorize, strict_explicit=True, skip_unready=True
                )
                self.stats["mapped_hits"] += len(mapped)
                # 相同内容键只匹配通过结构校验的原命中，保留该路原始排名。
                ranks = {self._key(hit): rank for rank, hit in reversed(list(enumerate(result, 1)))}
                from bisheng.knowledge.domain.services.knowledge_space_service import PortalSearchChunk

                for hit in mapped:
                    chunks.append(
                        PortalSearchChunk(
                            file_id=int(hit.entry_file_id),
                            knowledge_id=int(hit.space_id),
                            canonical_document_id=int(hit.canonical_document_id),
                            canonical_version_id=int(hit.canonical_version_id),
                            chunk_index=int(hit.chunk_index),
                            content_generation=0,
                            entry_generation=0,
                            content=hit.text or "",
                            source="shared",
                            retriever=lane,
                            rank=ranks[self._key(hit)],
                            score=float(hit.score),
                            metadata={},
                        )
                    )
        return PortalSharedRecall(self._merge(chunks), metadata_ids)

    async def _scope(
        self, space_ids: set[int], file_ids: list[int] | None, expected_parents: dict[int, int] | None = None
    ) -> RetrievalScope | None:
        if not space_ids or file_ids == []:
            return None
        explicit: dict[int, tuple[int, ...]] = {}
        if file_ids is not None:
            grouped: dict[int, list[int]] = {}
            for entry in await self.owner.knowledge_file_repo.find_by_ids(sorted(set(file_ids))):
                sid, fid = int(entry.knowledge_id), int(entry.id)
                if (
                    sid not in space_ids
                    or int(entry.tenant_id or 0) != self.snapshot.tenant_id
                    or entry.reference_document_id is None
                    or (expected_parents is not None and expected_parents.get(fid) != sid)
                ):
                    continue
                if (
                    entry.status != KnowledgeFileStatus.SUCCESS.value
                    or entry.deleted_at is not None
                    or entry.entry_status != "active"
                ):
                    continue
                grouped.setdefault(sid, []).append(fid)
            if not grouped:
                return None
            explicit = {sid: tuple(sorted(fids)) for sid, fids in grouped.items()}
            space_ids = set(explicit)
        # 这里只接受门户已授权的上下文；单文件授权不要求提升为空间读取权限。
        return RetrievalScope(
            tenant_id=self.snapshot.tenant_id,
            user_id=str(self.owner.login_user.user_id),
            requested_space_ids=tuple(sorted(space_ids)),
            explicit_entry_ids_by_space=explicit,
            routing_version=self.snapshot.routing_version,
        )

    def _resolver(self) -> SqlKnowledgeRetrievalScopeResolver:
        async def no_implicit_authorization(*args: Any) -> bool:
            raise SharedStorageContractError(
                SharedStorageErrorCode.PERMISSION_DENIED, "portal search requires batch authorization"
            )

        return SqlKnowledgeRetrievalScopeResolver(
            file_repository=self.owner.knowledge_file_repo,
            document_repository=self.owner.doc_repo,
            version_repository=self.owner.version_repo,
            space_read_checker=no_implicit_authorization,
            entry_view_checker=no_implicit_authorization,
            settings_provider=lambda: RetrievalScopeResolverSettings(
                enabled=True, routing_version=self.snapshot.routing_version
            ),
        )

    async def _authorize(self, entries: list[Any]) -> dict[int, bool]:
        pending = [entry for entry in entries if int(entry.id) not in self.permissions]
        for entry in pending:
            self.permissions[int(entry.id)] = False
        valid = [
            entry
            for entry in pending
            if entry.status == KnowledgeFileStatus.SUCCESS.value
            and entry.file_type == FileType.FILE.value
            and entry.deleted_at is None
        ]
        if self.req.file_ext:
            ext = self.req.file_ext.strip().lower().lstrip(".")
            valid = [entry for entry in valid if self.owner._get_file_ext(entry.file_name) == ext]
        valid = self.owner._filter_shougang_portal_files_by_document_type(valid, self.req.document_type)
        valid = self.owner._filter_shougang_portal_files_by_subcategory_code(valid, self.req.file_subcategory_code)
        valid = self.owner._filter_shougang_portal_files_by_business_domain_code(valid, self.req.business_domain_code)
        if valid:
            visible = await self.owner._filter_shougang_portal_visible_files(valid, spaces=self.spaces)
            for entry in visible:
                decision = self.owner._portal_file_access_decision_map.get(int(entry.id))
                self.permissions[int(entry.id)] = decision is None or decision.status == "allowed"
        self.stats["denied_entries"] += sum(not self.permissions[int(entry.id)] for entry in pending)
        return {int(entry.id): self.permissions[int(entry.id)] for entry in entries}

    async def _query(self, lane: str, backend_filter: Any, vector: list[float] | None) -> list[Any]:
        started = time.monotonic()
        try:
            if lane == "es":
                self.stats["es_calls"] += 1
                return await asyncio.wait_for(
                    self.reader.search_es(
                        filter_=backend_filter, query_text=self.req.q.strip(), limit=240, phrase_boost=3.0
                    ),
                    self.runtime.config.elasticsearch_timeout_seconds,
                )
            if vector is None:
                raise RuntimeError("query embedding unavailable")
            self.stats["vector_calls"] += 1
            return await asyncio.wait_for(
                self.reader.search_milvus(filter_=backend_filter, vector=vector, limit=72),
                self.runtime.config.milvus_timeout_seconds,
            )
        finally:
            logger.info("portal_global_search stage={} elapsed_ms={}", lane, int((time.monotonic() - started) * 1000))

    async def recheck_content_candidates(self, candidates: list[Any], file_map: dict[int, Any]) -> list[Any]:
        """外发重排/响应前重新校验正文入口；发现候选保留原安全投影。"""
        entries = [file_map[c.file_id] for c in candidates if c.chunks and c.file_id in file_map]
        self.permissions.clear()
        decisions = await self._authorize(entries)
        return [
            candidate for candidate in candidates if not candidate.chunks or decisions.get(candidate.file_id, False)
        ]

    @staticmethod
    def _key(hit: Any) -> tuple[int, int, int]:
        return int(hit.canonical_document_id), int(hit.canonical_version_id), int(hit.chunk_index)

    @classmethod
    def _merge(cls, chunks: list[Any]) -> list[Any]:
        # 完整内容组先于单文件组；同一文档始终引用同一个已授权入口。
        representative = {}
        for chunk in chunks:
            representative.setdefault(chunk.canonical_document_id, (chunk.file_id, chunk.knowledge_id))
        unique = {}
        for chunk in chunks:
            key = (*cls._key(chunk), chunk.retriever)
            current = unique.get(key)
            if current is None or chunk.rank < current.rank:
                fid, sid = representative[chunk.canonical_document_id]
                unique[key] = replace(chunk, file_id=fid, knowledge_id=sid)
        return sorted(unique.values(), key=lambda c: (c.retriever, c.rank, cls._key(c)))
