"""门户专用统一共享召回；既有每库检索入口保持原行为。"""

import asyncio
import time

from loguru import logger

from bisheng.knowledge.domain.contracts.qa_retrieval import (
    QaRetrievalResult,
    QaRetrievalError,
    QaRetrievalErrorKind,
    canonical_key,
)


class UnifiedSharedRetriever:
    def __init__(
        self,
        *,
        resolver,
        reader,
        candidate_limit=300,
        initial_limit=200,
        max_rounds=3,
        pool_limit=1600,
        search_timeout=30,
        batch_authorizer=None,
    ):
        self.resolver = resolver
        self.reader = reader
        self.candidate_limit = candidate_limit
        self.initial_limit = initial_limit
        self.max_rounds = max_rounds
        self.pool_limit = pool_limit
        self.search_timeout = search_timeout
        self.batch_authorizer = batch_authorizer

    async def retrieve(self, *, scope, query, vector, backend_filter=None):
        result = QaRetrievalResult()
        started = time.monotonic()
        backend_filter = backend_filter or self.resolver.build_backend_filter(scope)
        for round_index in range(self.max_rounds):
            # 每轮替换 Top-K 快照，不累加已被新结果挤出的旧片段。
            ranks = [{}, {}]
            raw = {}
            limit = min(self.initial_limit * (2**round_index), 800)

            async def timed_search(name, call):
                search_started = time.monotonic()
                try:
                    return await asyncio.wait_for(call, self.search_timeout)
                finally:
                    logger.info(
                        "portal_qa_stage stage={} elapsed_ms={} limit={}",
                        name,
                        int((time.monotonic() - search_started) * 1000),
                        limit,
                    )

            async def dense():
                if vector is None:
                    raise RuntimeError("embedding unavailable")
                return await self.reader.search_milvus(filter_=backend_filter, vector=vector, limit=limit)

            calls = [
                asyncio.create_task(timed_search("vector", dense())),
                asyncio.create_task(
                    timed_search(
                        "keyword", self.reader.search_es(filter_=backend_filter, query_text=query, limit=limit)
                    )
                ),
            ]
            try:
                responses = await asyncio.gather(*calls, return_exceptions=True)
            finally:
                for task in calls:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*calls, return_exceptions=True)
            from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError

            for response in responses:
                if isinstance(response, (asyncio.CancelledError, SharedStorageContractError)):
                    raise response
            if all(isinstance(response, BaseException) for response in responses):
                raise QaRetrievalError(QaRetrievalErrorKind.BACKENDS, "retrieval backends unavailable")
            exhausted = True
            for source, response in enumerate(responses):
                if isinstance(response, BaseException):
                    reason = "vector_unavailable" if source == 0 else "keyword_unavailable"
                    if reason not in result.degraded_reasons:
                        result.degraded_reasons.append(reason)
                    continue
                exhausted = exhausted and len(response) < limit
                for rank, hit in enumerate(response, 1):
                    key = canonical_key(hit)
                    raw[key] = hit
                    ranks[source][key] = min(rank, ranks[source].get(key, rank))
            scores = {key: sum(1 / (60 + rank_list[key]) for rank_list in ranks if key in rank_list) for key in raw}
            ordered = sorted(raw, key=lambda key: (-scores[key], key))
            truncated = len(ordered) > self.pool_limit
            ordered = ordered[: self.pool_limit]
            raw = {key: raw[key] for key in ordered}
            hits = [raw[key] for key in ordered]
            authorization_started = time.monotonic()
            mapped = await self.resolver.map_and_authorize_hits(
                scope,
                hits,
                entry_batch_checker=self.batch_authorizer,
                strict_explicit=True,
                skip_unready=True,
            )
            logger.info(
                "portal_qa_stage stage=authorize elapsed_ms={} raw={} dropped={}",
                int((time.monotonic() - authorization_started) * 1000),
                len(hits),
                len(hits) - len(mapped),
            )
            mapped_by_key = {canonical_key(hit): hit for hit in mapped}
            result.hits = [mapped_by_key[key] for key in ordered if key in mapped_by_key][: self.candidate_limit]
            result.raw_hits = {key: raw[key] for key in ordered if key in mapped_by_key}
            result.rounds = round_index + 1
            enough = len(result.hits) >= self.candidate_limit
            result.scope_complete = (enough or exhausted) and not truncated and not result.degraded_reasons
            logger.info(
                "portal_qa_recall round={} spaces={} raw={} authorized={} elapsed_ms={}",
                result.rounds,
                len(getattr(scope, "requested_space_ids", ())),
                len(hits),
                len(mapped),
                int((time.monotonic() - started) * 1000),
            )
            if enough or exhausted or truncated:
                break
        if not result.scope_complete and not result.hits:
            raise QaRetrievalError(
                QaRetrievalErrorKind.INCOMPLETE, "retrieval incomplete without authorized candidates"
            )
        return result


class PortalEntryAuthorizer:
    """一次授权阶段内按唯一入口复用决策，最终阶段使用新实例。"""

    def __init__(self, owner):
        self.owner = owner
        self.decisions = {}

    async def __call__(self, entries):
        from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError, SpaceFileNotFoundError
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
        from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileAccessStatus

        pending = [entry for entry in entries if int(entry.id) not in self.decisions]
        valid = [entry for entry in pending if int(entry.status) == KnowledgeFileStatus.SUCCESS.value]
        for entry in pending:
            self.decisions[int(entry.id)] = False
        if valid:
            access = self.owner.department_file_view_access_service
            if access is None:
                raise RuntimeError("portal authorization service unavailable")
            decisions = await access.evaluate_files(login_user=self.owner.login_user, files=valid)
            # 保留普通文件原有 can_read 与 view_file 两层校验，只按唯一入口调用。
            for entry in valid:
                decision = decisions[int(entry.id)]
                if decision.status == DepartmentFileAccessStatus.ALLOWED:
                    self.decisions[int(entry.id)] = True
                elif decision.status == DepartmentFileAccessStatus.NOT_APPLICABLE:
                    try:
                        await self.owner._require_file_view_permission(int(entry.knowledge_id), int(entry.id))
                    except (SpacePermissionDeniedError, SpaceFileNotFoundError):
                        continue
                    self.decisions[int(entry.id)] = True
        logger.info("portal_qa_authorize unique_entries={} new_entries={}", len(self.decisions), len(pending))
        return {int(entry.id): self.decisions[int(entry.id)] for entry in entries}


async def retrieve_portal_qa(*, request, user, plan, query, config, max_chars):
    """在独立读取会话中召回，外部重排后重新读取并复核最终入口。"""
    from contextlib import asynccontextmanager
    from langchain_core.documents import Document
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.contracts.retrieval_scope import EntryRef
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
        DepartmentFileViewGrantRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileViewAccessService
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.knowledge.domain.services.knowledge_retrieval_scope_resolver import (
        SqlKnowledgeRetrievalScopeResolver,
        RetrievalScopeResolverSettings,
    )
    from bisheng.knowledge.rag.shared_space_storage import (
        SharedSpaceStorageReader,
        aresolve_space_shared_routing,
        shared_collection_name,
    )
    from bisheng.knowledge.rag.async_retrieval_runtime import get_async_retrieval_runtime
    from bisheng.core.search.elasticsearch.manager import get_es_connection
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.llm.domain import LLMService
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    if not plan.space_ids or (plan.file_ids_by_space is not None and not any(plan.file_ids_by_space.values())):
        return [], QaRetrievalResult()
    phase_started = time.monotonic()
    spaces = await KnowledgeDao.aget_list_by_ids(list(plan.space_ids))
    if {int(space.id) for space in spaces} != set(plan.space_ids):
        raise ValueError("requested knowledge space unavailable")
    if any(int(space.tenant_id or 1) != int(user.tenant_id) for space in spaces):
        raise PermissionError("cross tenant retrieval denied")
    snapshots = [
        await aresolve_space_shared_routing(tenant, kind)
        for tenant, kind in sorted({(int(space.tenant_id or 1), int(space.type)) for space in spaces})
    ]
    if not snapshots or any(snapshot is None or not snapshot.shared_enabled for snapshot in snapshots):
        raise RuntimeError("shared retrieval routing unavailable")
    snapshot = snapshots[0]
    if any(
        (item.collection_name, item.routing_version) != (snapshot.collection_name, snapshot.routing_version)
        for item in snapshots
    ):
        raise RuntimeError("mixed shared retrieval routing")

    logger.info(
        "portal_qa_stage stage=routing elapsed_ms={} spaces={}",
        int((time.monotonic() - phase_started) * 1000),
        len(spaces),
    )

    @asynccontextmanager
    async def resources():
        async with get_async_db_session() as session:
            owner = KnowledgeSpaceChatService(request, user)
            owner.department_file_view_access_service = DepartmentFileViewAccessService(
                session=session,
                grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
                persist_stale_grant_revalidation=True,
            )

            async def space_read(tenant, uid, sid):
                await owner._permission_service()._require_read_permission(int(sid))
                return True

            async def unused_entry_check(*args):
                raise RuntimeError("batch entry authorization required")

            resolver = SqlKnowledgeRetrievalScopeResolver(
                file_repository=KnowledgeFileRepositoryImpl(session),
                document_repository=KnowledgeDocumentRepositoryImpl(session),
                version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
                space_read_checker=space_read,
                entry_view_checker=unused_entry_check,
                settings_provider=lambda: RetrievalScopeResolverSettings(
                    enabled=True, routing_version=int(snapshot.routing_version)
                ),
            )
            refs = (
                None
                if plan.file_ids_by_space is None
                else [
                    EntryRef(space_id=sid, entry_file_id=fid)
                    for sid, ids in plan.file_ids_by_space.items()
                    for fid in ids
                ]
            )
            scope_started = time.monotonic()
            scope = await resolver.resolve_request(
                user_id=str(user.user_id),
                tenant_id=int(user.tenant_id),
                space_ids=list(plan.space_ids),
                entry_refs=refs,
            )
            logger.info("portal_qa_stage stage=scope elapsed_ms={}", int((time.monotonic() - scope_started) * 1000))
            yield resolver, scope, PortalEntryAuthorizer(owner)

    runtime = await get_async_retrieval_runtime()
    vector = None
    phase_started = time.monotonic()
    try:

        async def embed():
            model = await LLMService.aget_knowledge_default_embedding(user.user_id, tenant_id=int(user.tenant_id))
            return await runtime.embed_query(model, query)

        vector = await asyncio.wait_for(embed(), config.embedding_timeout_seconds)
    except Exception:
        logger.warning("portal_qa_embedding_unavailable")
    logger.info("portal_qa_stage stage=embedding elapsed_ms={}", int((time.monotonic() - phase_started) * 1000))
    reader = SharedSpaceStorageReader(
        tenant_id=int(user.tenant_id),
        collection_name=snapshot.collection_name or shared_collection_name(int(user.tenant_id)),
        milvus_runtime=runtime,
        es_client=await get_es_connection(),
        expected_routing_version=snapshot.routing_version,
    )
    async with resources() as (resolver, scope, authorizer):
        ids, versions = await resolver.resolve_explicit_canonical_constraints(scope)
        query_filter = resolver.build_backend_filter(scope, canonical_document_ids=ids, canonical_version_ids=versions)
        engine = UnifiedSharedRetriever(
            resolver=resolver,
            reader=reader,
            candidate_limit=config.portal_qa_candidate_limit,
            initial_limit=config.portal_qa_initial_limit,
            max_rounds=config.portal_qa_max_rounds,
            pool_limit=config.portal_qa_pool_limit,
            search_timeout=max(config.milvus_timeout_seconds, config.elasticsearch_timeout_seconds),
            batch_authorizer=authorizer,
        )
        result = await engine.retrieve(scope=scope, query=query, vector=vector, backend_filter=query_filter)

    def to_document(hit):
        return Document(
            page_content=(hit.text or "")[:max_chars],
            metadata={
                "knowledge_id": int(hit.space_id),
                "document_id": int(hit.entry_file_id),
                "entry_file_id": int(hit.entry_file_id),
                "document_name": hit.document_name or "",
                "canonical_document_id": int(hit.canonical_document_id),
                "canonical_version_id": int(hit.canonical_version_id),
                "chunk_index": int(hit.chunk_index),
                "retrieval_source": "unified_shared",
            },
        )

    documents = [to_document(hit) for hit in result.hits]
    phase_started = time.monotonic()
    documents = await WorkStationService._rerank_retrieval_candidates(
        question=query, candidates=documents, login_user=user, degraded_reasons=result.degraded_reasons
    )
    logger.info(
        "portal_qa_stage stage=rerank elapsed_ms={} candidates={}",
        int((time.monotonic() - phase_started) * 1000),
        len(documents),
    )
    # 在有界排序候选内复核并补齐，失效的前序片段不挤占上下文预算。
    keys = [
        (
            int(doc.metadata["canonical_document_id"]),
            int(doc.metadata["canonical_version_id"]),
            int(doc.metadata["chunk_index"]),
        )
        for doc in documents
    ]
    phase_started = time.monotonic()
    async with resources() as (resolver, scope, authorizer):
        checked = await resolver.map_and_authorize_hits(
            scope,
            [result.raw_hits[key] for key in keys],
            entry_batch_checker=authorizer,
            strict_explicit=True,
            skip_unready=True,
        )
    logger.info(
        "portal_qa_stage stage=final_check elapsed_ms={} candidates={} retained={}",
        int((time.monotonic() - phase_started) * 1000),
        len(keys),
        len(checked),
    )
    mapped = {canonical_key(hit): hit for hit in checked}
    if len(mapped) < len(keys):
        result.scope_complete = False
        result.degraded_reasons.append("final_scope_changed")
    if keys and not mapped:
        raise QaRetrievalError(QaRetrievalErrorKind.SCOPE_CHANGED, "authorized retrieval scope changed")
    final_documents = [to_document(mapped[key]) for key in keys if key in mapped]
    _, final_documents = WorkStationService._truncate_ranked_documents_by_chars(final_documents, max_chars)
    return final_documents, result


async def build_portal_qa_plan(*, request, user, knowledge_base, department_access):
    from bisheng.knowledge.domain.contracts.qa_retrieval import QaRetrievalPlan
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    if knowledge_base is None:
        return QaRetrievalPlan(())
    scope = knowledge_base.knowledge_scope
    ids = list(knowledge_base.knowledge_space_ids or [])
    if scope is None or scope.mode == "knowledge_space":
        if scope is not None and scope.knowledge_space_id:
            ids.append(int(scope.knowledge_space_id))
        return QaRetrievalPlan(tuple(sorted(set(int(sid) for sid in ids if int(sid) > 0))))
    if scope.mode != "files":
        raise ValueError("unsupported knowledge scope")
    service = KnowledgeSpaceService(request, user)
    service.department_file_view_access_service = department_access
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import (
        KnowledgeDocumentEntryResolver,
        KnowledgeDocumentDurableReferenceResolver,
    )

    async with get_async_db_session() as session:
        service.knowledge_file_repo = KnowledgeFileRepositoryImpl(session)
        service.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
        service.doc_repo = KnowledgeDocumentRepositoryImpl(session)

        async def permission_loader(fid, sid):
            return await service._get_effective_permission_ids("knowledge_file", fid, space_id=sid)

        entry_resolver = KnowledgeDocumentEntryResolver(
            document_repository=service.doc_repo,
            version_repository=service.version_repo,
            file_repository=service.knowledge_file_repo,
            permission_loader=permission_loader,
        )
        service.document_durable_reference_resolver = KnowledgeDocumentDurableReferenceResolver(
            entry_resolver=entry_resolver,
            version_repository=service.version_repo,
            file_repository=service.knowledge_file_repo,
        )
        filters = await service.resolve_shougang_portal_qa_scope_file_ids(
            mode="files",
            knowledge_space_ids=ids,
            folder_refs=list(scope.folder_refs or []),
            file_refs=list(scope.file_refs or []),
            max_files=None,
            subtree_page_size=200,
        )
    return QaRetrievalPlan(tuple(sorted(filters)), filters)
