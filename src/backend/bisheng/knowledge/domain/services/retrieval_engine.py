"""The one retrieval engine behind every retrieval path (F052 design D5).

This is the code that used to live inside ``KnowledgeSpaceChatService`` as five
private methods. It moved out rather than being copied, because F052 needs the
same filtering strength on the open face and a second implementation is exactly
the divergence the companion PRD already caught once.

Two entries sit on top of it and nothing else is allowed to:

* ``KnowledgeSpaceChatService.aretrieve_chunks`` — the in-platform chat path,
  whose contract (400 on empty ids, ``NotFoundError``, ``KnowledgeTypeNotSupportedError``)
  is unchanged (决议-9).
* ``RetrievalFacadeService`` — the session-decoupled facade the open face uses.

The engine deliberately takes **no ``Request``**: reachability is decided by the
caller, and every permission decision in here reads ``login_user`` plus the
permission ContextVar. ``KnowledgeFileVisibilityService`` still accepts a
``request`` parameter, but its decision chain never reads it — ``request=None``
is already the shape used by the workstation and citation paths (design 坑 4).
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool

# Base candidate count handed to each retriever before the config multiplier.
_BASE_K = 100
_ScoredDocuments = list[tuple[Document, float]]


class _RetrievalChannel(VectorStore):
    """Expose one channel of a request-local, permission-filtered score batch.

    Both channels share a task so each KB is recalled and checked only once,
    while MultiRetriever retains the native scores for its cross-KB ordering.
    """

    def __init__(self, task: asyncio.Task[list[_ScoredDocuments]], channel: int):
        self.task = task
        self.channel = channel

    async def asimilarity_search_with_relevance_scores(self, query, **kwargs) -> _ScoredDocuments:
        return (await self.task)[self.channel]

    def similarity_search(self, query, k=4, **kwargs):
        raise NotImplementedError("Async retrieval-only adapter")

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError("Retrieval-only adapter")


class RetrievalEngine:
    """Retrieve chunks from knowledge spaces / document libraries, filtered."""

    def __init__(self, login_user: UserPayload, *, version_repo: Any = None, provider_retrieval=None):
        self.provider_retrieval = provider_retrieval
        self.login_user = login_user
        self.version_repo = version_repo

    # ------------------------------------------------------------------
    # Collaborators
    # ------------------------------------------------------------------

    def _require_provider_if_marked(self, target):
        # A trusted caller can supply a hydrated target before its port is
        # wired. An explicit external route must never become a native search.
        key = getattr(target, "provider_key", None)
        if self.provider_retrieval is None and isinstance(key, str) and key != "native":
            raise ValueError("provider retrieval not configured")

    def _visibility_service(self):
        """F029 two-layer ``visible`` filter, built without a ``Request``."""

        from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
            KnowledgeFileVisibilityService,
        )

        if not hasattr(self, "_knowledge_file_visibility_service"):
            svc = KnowledgeFileVisibilityService(request=None, login_user=self.login_user)
            svc.version_repo = self.version_repo
            self._knowledge_file_visibility_service = svc
        return self._knowledge_file_visibility_service

    def _qa_filter_conf(self):
        """F029 retrieval-loop config (multipliers, base k)."""
        try:
            from bisheng.common.services.config_service import settings

            return settings.knowledge_qa_filter
        except (AttributeError, ImportError):
            from bisheng.core.config.settings import KnowledgeQAFilterConf

            return KnowledgeQAFilterConf()

    # ------------------------------------------------------------------
    # The filter loop itself (AD-01 / AD-03)
    # ------------------------------------------------------------------

    async def retrieve_and_filter(
        self,
        *,
        space,
        query: str,
        candidate_file_ids: list[int] | None,
        max_content: int,
        sort_by_source_and_index: bool = True,
    ) -> list[Document]:
        """F029: two-layer ``visible`` filter retrieval loop (AD-01 / AD-03).

        Returns docs whose ``document_id`` belongs to a file the current
        identity may see. Caps at two retrieval attempts; emits one structured
        ``permission_filter`` log line per attempt (AC-27).
        """
        self._require_provider_if_marked(space)
        if self.provider_retrieval is not None and space.type == KnowledgeTypeEnum.SPACE.value:
            from bisheng.knowledge.application.provider_retrieval import RetrievalSelection

            route = await self.provider_retrieval.route(space)
            if route is not None:
                selection = RetrievalSelection(
                    file_ids=None if candidate_file_ids is None else tuple(candidate_file_ids)
                )
                hits = await self.provider_retrieval.retrieve(
                    space, route, selection, query, max_content, self._visibility_service()
                )
                return [doc for _, doc in hits]
        visibility = self._visibility_service()
        conf = self._qa_filter_conf()

        index_filter = await visibility.build_index_prefilter(space.id, candidate_file_ids)
        if index_filter.is_empty:
            logger.info(
                "permission_filter | space_id={} strategy=empty accessible_ids_size={} "
                "prefilter_candidate_size=0 retrieval_attempts=0 post_filter_dropped_count=0",
                space.id,
                index_filter.accessible_size,
            )
            return []

        base_milvus_expr = index_filter.milvus_expr
        base_es_filter = index_filter.es_filter or []
        multipliers = (
            conf.retrieval_initial_multiplier,
            conf.retrieval_expansion_multiplier,
        )

        survivors: list[Document] = []
        for attempt_idx, multiplier in enumerate(multipliers, start=1):
            milvus_kwargs: dict[str, Any] = {
                "k": _BASE_K * multiplier,
                "param": {"ef": 110},
            }
            if base_milvus_expr:
                milvus_kwargs["expr"] = base_milvus_expr
            es_kwargs: dict[str, Any] = {"k": _BASE_K * multiplier}
            if base_es_filter:
                es_kwargs["filter"] = base_es_filter

            milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
                self.login_user.user_id, knowledge=space, login_user=self.login_user
            )
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space, login_user=self.login_user)
            vector_retriever = milvus_vector.as_retriever(search_kwargs=milvus_kwargs)
            es_retriever = es_vector.as_retriever(search_kwargs=es_kwargs)

            retriever_tool = KnowledgeRetrieverTool(
                vector_retriever=vector_retriever,
                elastic_retriever=es_retriever,
                max_content=max_content,
                sort_by_source_and_index=sort_by_source_and_index,
            )
            docs: list[Document] = await retriever_tool.ainvoke(query)

            unique_file_ids = {
                int(d.metadata.get("document_id"))
                for d in docs
                if d.metadata and d.metadata.get("document_id") is not None
            }
            permitted = await visibility.post_filter_retrievable_files(space.id, unique_file_ids)
            survivors = [d for d in docs if int(d.metadata.get("document_id", -1)) in permitted]
            dropped = len(docs) - len(survivors)

            logger.info(
                "permission_filter | space_id={} strategy={} accessible_ids_size={} "
                "prefilter_candidate_size={} retrieval_attempts={} "
                "post_filter_dropped_count={}",
                space.id,
                index_filter.strategy,
                index_filter.accessible_size,
                len(docs),
                attempt_idx,
                dropped,
            )

            if survivors:
                break  # AD-03: stop on first non-empty attempt

        return survivors

    # ------------------------------------------------------------------
    # Tag resolution
    # ------------------------------------------------------------------

    async def resolve_space_file_ids_by_tags(
        self,
        knowledge_id: int,
        tag_names: list[str],
    ) -> list[int] | None:
        """Map tag names (scoped to a knowledge space) to file ids.

        Returns ``None`` when no tag filter is requested (caller treats as
        whole-space). Returns an empty list when tags are provided but resolve
        to no files (caller short-circuits and skips this knowledge base).
        """
        if not tag_names:
            return None

        resolved_tag_ids: list[int] = []
        for tag_name in tag_names:
            tags = await TagDao.get_tags_by_business(
                business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
                business_id=str(knowledge_id),
                name=tag_name,
            )
            resolved_tag_ids.extend([t.id for t in tags])
        if not resolved_tag_ids:
            return []

        tag_links = await TagDao.aget_resources_by_tags(
            resolved_tag_ids,
            resource_type=ResourceTypeEnum.SPACE_FILE,
        )
        return [int(link.resource_id) for link in tag_links]

    async def resolve_library_file_ids_by_tags(
        self,
        knowledge_id: int,
        tag_names: list[str],
    ) -> list[int] | None:
        """Map tag names (scoped to a document knowledge base) to file ids.

        ``None`` = no tag filter (whole KB). Empty list = tags given but no
        files match (caller short-circuits and skips this KB).
        """
        if not tag_names:
            return None
        resolved_tag_ids: list[int] = []
        for tag_name in tag_names:
            tags = await TagDao.get_tags_by_business(
                business_type=TagBusinessTypeEnum.KNOWLEDGE,
                business_id=str(knowledge_id),
                name=tag_name,
            )
            resolved_tag_ids.extend([t.id for t in tags])
        if not resolved_tag_ids:
            return []
        tag_links = await TagDao.aget_resources_by_tags(
            resolved_tag_ids,
            resource_type=ResourceTypeEnum.KNOWLEDGE_FILE,
        )
        return [int(link.resource_id) for link in tag_links]

    # ------------------------------------------------------------------
    # Per-type retrieval
    # ------------------------------------------------------------------

    async def retrieve_space(
        self,
        space,
        *,
        query: str,
        tag_names: list[str],
        max_content: int,
    ) -> list[tuple[int, Document]]:
        """Knowledge space (type=3): file-level ``visible`` filtering."""
        self._require_provider_if_marked(space)

        if self.provider_retrieval is not None:
            from bisheng.knowledge.application.provider_retrieval import RetrievalSelection

            route = await self.provider_retrieval.route(space)
            if route is not None:
                if tag_names:
                    raise ValueError("external spaces require stable tag references")
                return await self.provider_retrieval.retrieve(
                    space, route, RetrievalSelection(), query, max_content, self._visibility_service()
                )
        target_file_ids = await self.resolve_space_file_ids_by_tags(space.id, tag_names)
        if tag_names and not target_file_ids:
            return []

        docs = await self.retrieve_and_filter(
            space=space,
            query=query,
            candidate_file_ids=target_file_ids,
            max_content=max_content,
            sort_by_source_and_index=False,
        )
        return [(space.id, doc) for doc in docs]

    async def retrieve_library(
        self,
        library,
        *,
        query: str,
        tag_names: list[str],
        max_content: int,
    ) -> list[tuple[int, Document]]:
        """Document knowledge base (type=0): library-level ``use`` gate first.

        No folder / version-primary logic — those are knowledge-space-only
        concepts. The current permission model has no per-file visibility for
        document libraries, so "the same set as an in-platform search" holds at
        library granularity here (决议-3).
        """
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        # Library-level use permission (raises UnAuthorizedError on denial →
        # surfaced by the caller's BaseErrorCode handler).
        await KnowledgeService.permission_service.ensure_knowledge_use_async(
            login_user=self.login_user,
            owner_user_id=library.user_id,
            knowledge_id=library.id,
        )

        target_file_ids = await self.resolve_library_file_ids_by_tags(library.id, tag_names)
        if tag_names and not target_file_ids:
            return []

        docs = await self.retrieve_and_filter(
            space=library,
            query=query,
            candidate_file_ids=target_file_ids,
            max_content=max_content,
            sort_by_source_and_index=False,
        )
        return [(library.id, doc) for doc in docs]

    async def retrieve_many(
        self,
        targets: list,
        *,
        query: str,
        tag_filters: dict[int, list[str]] | None = None,
        selections: dict | None = None,
        max_content: int,
    ) -> list[tuple[int, Document]]:
        """Globally fuse the two score-ranked channels, as workflow retrieval does.

        Takes **rows**, not ids: reachability (existence, type support, grant)
        is the caller's decision, so the engine never has to answer "does this
        knowledge base exist" — which is precisely the question the open face
        must not answer distinguishably.
        """
        from itertools import zip_longest

        from bisheng.knowledge.application.provider_retrieval import RetrievalSelection

        selections = selections or {}
        if selections.keys() - {t.id for t in targets}:
            raise ValueError("selection outside retrieval scope")
        if not targets:
            return []
        if self.provider_retrieval is None:
            for target in targets:
                self._require_provider_if_marked(target)
            if selections:
                raise ValueError("provider retrieval not configured")
            return await self._retrieve_native_many(
                targets, query=query, tag_filters=tag_filters, max_content=max_content
            )
        # Resolve every route first: an all-Native request must keep the
        # historical global-ranking path. Grouping Native KBs and interleaving
        # them by per-source rank changes which chunks survive a global top-k.
        routes = {}
        for target in targets:
            route = None
            if self.provider_retrieval is not None and target.type == KnowledgeTypeEnum.SPACE.value:
                route = await self.provider_retrieval.route(target)
            routes[target.id] = route
        if not any(routes.values()):
            if selections:
                raise ValueError("provider selection on native target")
            return await self._retrieve_native_many(
                targets, query=query, tag_filters=tag_filters, max_content=max_content
            )
        groups = {}
        for target in targets:
            route = routes[target.id]
            if route is not None:
                if (tag_filters or {}).get(target.id):
                    raise ValueError("external spaces require stable tag references")
                groups[("external", target.id)] = await self.provider_retrieval.retrieve(
                    target,
                    route,
                    selections.get(target.id, RetrievalSelection()),
                    query,
                    max_content,
                    self._visibility_service(),
                )
            else:
                if target.id in selections:
                    raise ValueError("provider selection on native target")
                groups.setdefault(("native", getattr(target, "model", None)), []).append(target)
        for key, group in groups.items():
            if key[0] == "native":
                groups[key] = await self._retrieve_native_many(
                    group, query=query, tag_filters=tag_filters, max_content=max_content
                )
        # Sources are disjoint. Equal-weight reciprocal rank orders solely by
        # within-source rank; stable group order breaks ties, never raw scores.
        return [hit for level in zip_longest(*groups.values()) for hit in level if hit is not None]

    async def _retrieve_native_many(self, targets, *, query, tag_filters, max_content):
        if len(targets) == 1:
            return await self._retrieve_one(
                targets[0], query=query, tag_names=(tag_filters or {}).get(targets[0].id) or [], max_content=max_content
            )

        visibility = self._visibility_service()
        prepared = []
        # The version repository owns one request-scoped AsyncSession. Prepare
        # filters sequentially; only the search-engine I/O may run concurrently.
        for target in targets:
            tag_names = (tag_filters or {}).get(target.id) or []
            if target.type == KnowledgeTypeEnum.SPACE.value:
                file_ids = await self.resolve_space_file_ids_by_tags(target.id, tag_names)
            else:
                from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

                await KnowledgeService.permission_service.ensure_knowledge_use_async(
                    login_user=self.login_user, owner_user_id=target.user_id, knowledge_id=target.id
                )
                file_ids = await self.resolve_library_file_ids_by_tags(target.id, tag_names)
            if tag_names and not file_ids:
                continue
            index_filter = await visibility.build_index_prefilter(target.id, file_ids)
            if index_filter.is_empty:
                continue
            milvus = await KnowledgeRag.init_knowledge_milvus_vectorstore(
                self.login_user.user_id, knowledge=target, login_user=self.login_user
            )
            es = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=target, login_user=self.login_user)
            prepared.append((target, index_filter, milvus, es))
        if not prepared:
            return []

        filter_lock = asyncio.Lock()
        tasks = [
            asyncio.create_task(self._retrieve_scored_candidates(target, index_filter, milvus, es, query, filter_lock))
            for target, index_filter, milvus, es in prepared
        ]
        channels = [
            MultiRetriever(
                vectors=[_RetrievalChannel(task, channel) for task in tasks], search_kwargs=[{} for _ in tasks]
            )
            for channel in (0, 1)
        ]
        try:
            # Use the existing multi-KB score sort for each channel, then exactly
            # one RRF across those global rankings (never RRF each KB first).
            milvus_docs = await channels[0].ainvoke(query)
            es_docs = await channels[1].ainvoke(query)
        finally:
            # A failed KB must fail the request and leave no sibling DB work
            # running after its request-scoped session has been closed.
            for task in tasks:
                if not task.done():
                    task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    logger.opt(exception=outcome).error("multi_retrieval candidate failed")

        tool = KnowledgeRetrieverTool(
            vector_retriever=channels[0],
            elastic_retriever=channels[1],
            # Keep all fused candidates here; max_content remains a per-KB
            # budget below, rather than becoming a global content budget.
            max_content=sum(len(doc.page_content) for doc in [*milvus_docs, *es_docs]),
            sort_by_source_and_index=False,
        )
        docs = tool._rrf_rerank(milvus_docs, es_docs, query)
        content_sizes: dict[int, int] = {}
        results: list[tuple[int, Document]] = []
        for doc in docs:
            knowledge_id = doc.metadata["knowledge_id"]
            size = content_sizes.get(knowledge_id, 0)
            # Match KnowledgeRetrieverTool's whole-chunk length cutoff.
            if size > max_content:
                continue
            content_sizes[knowledge_id] = size + len(doc.page_content)
            results.append((knowledge_id, doc))
        return results

    async def _retrieve_scored_candidates(
        self, target, index_filter, milvus: VectorStore, es: VectorStore, query: str, filter_lock: asyncio.Lock
    ) -> list[_ScoredDocuments]:
        """Keep scores/provenance through the existing two-attempt file filter."""
        conf = self._qa_filter_conf()
        visibility = self._visibility_service()
        for attempt, multiplier in enumerate(
            (conf.retrieval_initial_multiplier, conf.retrieval_expansion_multiplier), start=1
        ):
            milvus_kwargs: dict[str, Any] = {"k": _BASE_K * multiplier, "param": {"ef": 110}}
            if index_filter.milvus_expr:
                milvus_kwargs["expr"] = index_filter.milvus_expr
            es_kwargs: dict[str, Any] = {"k": _BASE_K * multiplier}
            if index_filter.es_filter:
                es_kwargs["filter"] = deepcopy(index_filter.es_filter)
            milvus_rows = await milvus.asimilarity_search_with_relevance_scores(query, **milvus_kwargs)
            es_rows = await es.asimilarity_search_with_relevance_scores(query, **es_kwargs)
            file_ids = {
                int(doc.metadata["document_id"])
                for doc, _ in [*milvus_rows, *es_rows]
                if doc.metadata.get("document_id") is not None
            }
            async with filter_lock:
                permitted = await visibility.post_filter_retrievable_files(target.id, file_ids)
            channels = [
                [
                    (doc.model_copy(update={"metadata": {**doc.metadata, "knowledge_id": target.id}}), score)
                    for doc, score in rows
                    if int(doc.metadata.get("document_id", -1)) in permitted
                ]
                for rows in (milvus_rows, es_rows)
            ]
            logger.info(
                "permission_filter | space_id={} strategy={} accessible_ids_size={} "
                "prefilter_candidate_size={} retrieval_attempts={} post_filter_dropped_count={}",
                target.id,
                index_filter.strategy,
                index_filter.accessible_size,
                len(milvus_rows) + len(es_rows),
                attempt,
                len(milvus_rows) + len(es_rows) - sum(map(len, channels)),
            )
            if any(channels):
                break
        return channels

    async def _retrieve_one(
        self,
        target,
        *,
        query: str,
        tag_names: list[str],
        max_content: int,
    ) -> list[tuple[int, Document]]:
        if target.type == KnowledgeTypeEnum.SPACE.value:
            return await self.retrieve_space(target, query=query, tag_names=tag_names, max_content=max_content)
        return await self.retrieve_library(target, query=query, tag_names=tag_names, max_content=max_content)

    # ------------------------------------------------------------------
    # Result hydration
    # ------------------------------------------------------------------

    async def attach_document_update_time(self, results: list[tuple[int, Document]]) -> None:
        """Annotate each chunk's metadata with its source file's update time.

        The metadata ``document_id`` equals the ``KnowledgeFile`` id, so a
        single batched lookup resolves the update time for every distinct
        document. The value is formatted as ``YYYY-MM-DD HH:mm:ss``; documents
        without a record or update time get an empty string.
        """
        document_ids = {
            int(doc.metadata.get("document_id", 0)) for _, doc in results if doc.metadata.get("document_id")
        }
        document_ids.discard(0)
        if not document_ids:
            return

        files = await KnowledgeFileDao.aget_file_by_ids(list(document_ids))
        update_time_by_id = {f.id: f.update_time.strftime("%Y-%m-%d %H:%M:%S") if f.update_time else "" for f in files}
        for _, doc in results:
            doc_id = int(doc.metadata.get("document_id", 0))
            doc.metadata["document_update_time"] = update_time_by_id.get(doc_id, "")


__all__ = ["RetrievalEngine"]
