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
    """两路固定批量续取；同一请求内保留排名和已授权候选。"""

    def __init__(
        self,
        *,
        resolver,
        reader,
        candidate_limit=300,
        initial_limit=200,
        max_rounds=None,
        pool_limit=1600,
        search_timeout=30,
        batch_authorizer=None,
        source_limit=800,
        scan_limit=1600,
        context=None,
    ):
        self.resolver, self.reader = resolver, reader
        self.candidate_limit, self.initial_limit = candidate_limit, initial_limit
        self.pool_limit, self.search_timeout = pool_limit, search_timeout
        self.batch_authorizer = batch_authorizer
        self.source_limit, self.scan_limit = source_limit, scan_limit
        self.context = context

    async def retrieve(self, *, scope, query, vector, backend_filter=None, finalize=None):
        from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError

        result = QaRetrievalResult()
        result.scope_complete = False
        backend_filter = backend_filter or self.resolver.build_backend_filter(scope)
        cursors, exhausted, failed = [None, None], [False, False], [False, False]
        stagnant_pages = [0, 0]
        ranks, counts, raw, mapped, rejected = [{}, {}], [0, 0], {}, {}, set()
        names = ["vector", "keyword"]

        async def fetch(source, size):
            if cursors[source] is None:
                if source == 0:
                    if vector is None:
                        raise RuntimeError("embedding unavailable")
                    cursors[source] = await self.reader.open_milvus_cursor(
                        filter_=backend_filter, vector=vector, batch_size=size, limit=self.source_limit
                    )
                else:
                    cursors[source] = await self.reader.open_es_cursor(
                        filter_=backend_filter, query_text=query, batch_size=size, limit=self.source_limit
                    )
            return await cursors[source].next_batch()

        try:
            while True:
                remaining = self.scan_limit - sum(counts)
                active = [i for i in range(2) if not exhausted[i] and not failed[i] and counts[i] < self.source_limit]
                calls = []
                sources = []
                # 每路固定批量，剩余预算不足整批时不发起新的读取。
                for i in active:
                    size = min(self.initial_limit, self.source_limit - counts[i])
                    if remaining < size:
                        continue
                    remaining -= size
                    sources.append(i)
                    calls.append(asyncio.create_task(asyncio.wait_for(fetch(i, size), self.search_timeout)))
                if not calls:
                    break
                batch_started = time.monotonic()
                try:
                    responses = await asyncio.gather(*calls, return_exceptions=True)
                finally:
                    for task in calls:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*calls, return_exceptions=True)
                logger.info(
                    "portal_qa_stage stage=cursor_read elapsed_ms={} sources={}",
                    int((time.monotonic() - batch_started) * 1000),
                    len(sources),
                )
                new_hits = {}
                for i, response in zip(sources, responses):
                    if isinstance(response, (asyncio.CancelledError, SharedStorageContractError)):
                        raise response
                    if isinstance(response, BaseException):
                        failed[i] = True
                        result.degraded_reasons.append(names[i] + "_unavailable")
                        continue
                    if not response:
                        exhausted[i] = True
                        continue
                    if len(response) > min(self.initial_limit, self.source_limit - counts[i]):
                        raise RuntimeError("retrieval cursor exceeded batch budget")
                    previous_count = counts[i]
                    counts[i] += len(response)
                    progress = False
                    for rank, hit in enumerate(response, previous_count + 1):
                        key = canonical_key(hit)
                        if key not in ranks[i]:
                            ranks[i][key] = rank
                            progress = True
                        if key not in raw and len(raw) < self.pool_limit:
                            raw[key] = hit
                            new_hits[key] = hit
                    stagnant_pages[i] = 0 if progress else stagnant_pages[i] + 1
                    if stagnant_pages[i] >= 2:
                        failed[i] = True
                        result.degraded_reasons.append(names[i] + "_cursor_no_progress")
                if all(failed) and not raw:
                    raise QaRetrievalError(QaRetrievalErrorKind.BACKENDS, "retrieval backends unavailable")
                if new_hits:
                    authorization_started = time.monotonic()
                    accepted = await self.resolver.map_and_authorize_hits(
                        scope,
                        list(new_hits.values()),
                        entry_batch_checker=self.batch_authorizer,
                        strict_explicit=True,
                        skip_unready=True,
                        **({"context": self.context} if self.context is not None else {}),
                    )
                    logger.info(
                        "portal_qa_stage stage=authorize elapsed_ms={} raw={} dropped={}",
                        int((time.monotonic() - authorization_started) * 1000),
                        len(new_hits),
                        len(new_hits) - len(accepted),
                    )
                    mapped.update((canonical_key(hit), hit) for hit in accepted)
                ordered = sorted(
                    (key for key in mapped if key not in rejected),
                    key=lambda key: (-sum(1 / (60 + source[key]) for source in ranks if key in source), key),
                )
                selected = ordered[: self.candidate_limit]
                result.hits = [mapped[key] for key in selected]
                result.raw_hits = {key: raw[key] for key in ordered}
                result.rounds += 1
                enough = len(selected) >= self.candidate_limit
                done = all(exhausted[i] or failed[i] or counts[i] >= self.source_limit for i in range(2))
                done = done or sum(counts) >= self.scan_limit or len(raw) >= self.pool_limit
                if not done:
                    done = not any(
                        not exhausted[i]
                        and not failed[i]
                        and counts[i] < self.source_limit
                        and self.scan_limit - sum(counts) >= min(self.initial_limit, self.source_limit - counts[i])
                        for i in range(2)
                    )
                result.scope_complete = (enough or all(exhausted)) and not result.degraded_reasons
                logger.info(
                    "portal_qa_cursor batch={} scanned={} unique={} authorized={}",
                    result.rounds,
                    sum(counts),
                    len(raw),
                    len(selected),
                )
                if enough or done:
                    if finalize and result.hits:
                        changed = False
                        while result.hits:
                            previous = {canonical_key(hit) for hit in result.hits}
                            denied = set(await finalize(result)) & previous
                            if not denied:
                                break
                            changed = True
                            rejected.update(denied)
                            # 先使用当前候选池补位，避免还有备用候选时额外读取存储。
                            selected = [key for key in ordered if key not in rejected][: self.candidate_limit]
                            result.hits = [mapped[key] for key in selected]
                            if not (set(selected) - previous):
                                break
                        if changed and len(result.hits) < self.candidate_limit:
                            result.scope_complete = False
                            if not done:
                                continue
                            result.degraded_reasons.append("final_scope_changed")
                    break
            if not result.scope_complete and not result.hits:
                raise QaRetrievalError(
                    QaRetrievalErrorKind.INCOMPLETE,
                    "retrieval incomplete without authorized candidates or scope changed",
                )
            return result
        finally:
            from bisheng.knowledge.rag.shared_search_cursor import finish_inflight

            async def close_all():
                for cursor in cursors:
                    if cursor is None:
                        continue
                    try:
                        await cursor.close()
                    except Exception:
                        logger.exception("portal_qa_cursor_close_failed")

            await finish_inflight(asyncio.create_task(close_all()))


class PortalEntryAuthorizer:
    """一次授权阶段内按唯一入口复用决策，最终阶段使用新实例。"""

    def __init__(self, owner, *, space_repository=None, context=None):
        self.owner = owner
        self.context = context
        self.decisions = {}
        self.space_repository = space_repository
        self.spaces = {}

    async def __call__(self, entries):
        if self.context is not None:
            await self.context.prepare_entries(self.owner, entries)
            return self.context.evaluate_entries(entries)

        from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError, SpaceFileNotFoundError
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
        from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileAccessStatus

        pending = [entry for entry in entries if int(entry.id) not in self.decisions]
        valid = [
            entry
            for entry in pending
            if int(entry.status) == KnowledgeFileStatus.SUCCESS.value and getattr(entry, "deleted_at", None) is None
        ]
        for entry in pending:
            self.decisions[int(entry.id)] = False
        if self.space_repository is not None and valid:
            missing = {int(entry.knowledge_id) for entry in valid} - self.spaces.keys()
            if missing:
                self.spaces.update(dict.fromkeys(missing))
                rows = await self.space_repository.find_qa_spaces_by_ids(list(missing))
                for space, level in rows:
                    if int(space.tenant_id or 1) == int(self.owner.login_user.tenant_id):
                        self.spaces[int(space.id)] = level or "private"
            other = []
            for entry in valid:
                if int(getattr(entry, "tenant_id", self.owner.login_user.tenant_id) or 1) != int(
                    self.owner.login_user.tenant_id
                ):
                    continue
                level = self.spaces.get(int(entry.knowledge_id))
                if level == "public":
                    self.decisions[int(entry.id)] = True
                elif level is not None:
                    other.append(entry)
            valid = other
        if valid:
            access = self.owner.department_file_view_access_service
            if access is None:
                raise RuntimeError("portal authorization service unavailable")
            decisions = await access.evaluate_files(login_user=self.owner.login_user, files=valid)
            ordinary = []
            for entry in valid:
                decision = decisions[int(entry.id)]
                if decision.status == DepartmentFileAccessStatus.ALLOWED:
                    self.decisions[int(entry.id)] = True
                elif decision.status == DepartmentFileAccessStatus.NOT_APPLICABLE:
                    if self.space_repository is not None:
                        ordinary.append(entry)
                        continue
                    try:
                        await self.owner._require_file_view_permission(int(entry.knowledge_id), int(entry.id))
                    except (SpacePermissionDeniedError, SpaceFileNotFoundError):
                        continue
                    self.decisions[int(entry.id)] = True
            if ordinary:
                permissions = await self.owner._permission_service().batch_qa_file_view_permissions(ordinary)
                self.decisions.update({int(entry.id): permissions.get(int(entry.id), False) for entry in ordinary})
        logger.info("portal_qa_authorize unique_entries={} new_entries={}", len(self.decisions), len(pending))
        return {int(entry.id): self.decisions[int(entry.id)] for entry in entries}


async def retrieve_portal_qa(*, request, user, plan, query, config, max_chars):
    """在独立读取会话中召回，外部重排后重新读取并复核最终入口。"""
    from contextlib import asynccontextmanager
    from langchain_core.documents import Document
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.portal_search_context_repository_impl import (
        PortalSearchContextRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.portal_qa_context import PortalQaContext
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
    async def resources(phase="candidates"):
        async with get_async_db_session() as session:
            owner = KnowledgeSpaceChatService(request, user)
            owner.department_file_view_access_service = DepartmentFileViewAccessService(
                session=session,
                grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
                persist_stale_grant_revalidation=True,
            )

            async def space_read(tenant, uid, sid):
                raise RuntimeError("portal QA must authorize candidates after retrieval")

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
                authorize_spaces=False,
            )
            logger.info("portal_qa_stage stage=scope elapsed_ms={}", int((time.monotonic() - scope_started) * 1000))
            context = PortalQaContext(
                tenant_id=int(user.tenant_id), user_id=int(user.user_id),
                routing_version=int(snapshot.routing_version), space_ids=list(plan.space_ids),
                repository=PortalSearchContextRepositoryImpl(user.user_id, session_factory=get_async_db_session),
                phase=phase,
            )
            context.bind_scope(scope)
            if phase == "candidates":
                context.seed("spaces", {int(space.id): space for space in spaces})
            try:
                yield resolver, scope, PortalEntryAuthorizer(owner, context=context)
            finally:
                from bisheng.knowledge.rag.shared_search_cursor import finish_inflight

                await finish_inflight(asyncio.create_task(context.close()))

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

    final_documents = []

    async def finalize(result):
        nonlocal final_documents
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
        async with resources("final") as (resolver, scope, authorizer):
            checked = await resolver.map_and_authorize_hits(
                scope,
                [result.raw_hits[key] for key in keys],
                entry_batch_checker=authorizer,
                strict_explicit=True,
                skip_unready=True,
                context=authorizer.context,
            )
        logger.info(
            "portal_qa_stage stage=final_check elapsed_ms={} candidates={} retained={}",
            int((time.monotonic() - phase_started) * 1000),
            len(keys),
            len(checked),
        )
        mapped = {canonical_key(hit): hit for hit in checked}
        final_documents = [to_document(mapped[key]) for key in keys if key in mapped]
        return set(keys) - set(mapped)

    async with resources() as (resolver, scope, authorizer):
        ids, versions = await resolver.resolve_explicit_canonical_constraints(scope)
        query_filter = resolver.build_backend_filter(scope, canonical_document_ids=ids, canonical_version_ids=versions)
        engine = UnifiedSharedRetriever(
            resolver=resolver,
            reader=reader,
            candidate_limit=config.portal_qa_candidate_limit,
            initial_limit=config.portal_qa_initial_limit,
            source_limit=config.portal_qa_cursor_source_limit,
            scan_limit=config.portal_qa_cursor_scan_limit,
            pool_limit=config.portal_qa_pool_limit,
            search_timeout=max(config.milvus_timeout_seconds, config.elasticsearch_timeout_seconds),
            batch_authorizer=authorizer,
            context=authorizer.context,
        )
        result = await engine.retrieve(
            scope=scope, query=query, vector=vector, backend_filter=query_filter, finalize=finalize
        )

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
            # 此处只解析 durable reference，授权在候选阶段统一进行。
            return set()

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
            defer_authorization=True,
        )
    return QaRetrievalPlan(tuple(sorted(filters)), filters)
