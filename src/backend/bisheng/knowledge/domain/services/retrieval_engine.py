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
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool

# Base candidate count handed to each retriever before the config multiplier.
_BASE_K = 100


class RetrievalEngine:
    """Retrieve chunks from knowledge spaces / document libraries, filtered."""

    def __init__(self, login_user: UserPayload, *, version_repo: Any = None):
        self.login_user = login_user
        self.version_repo = version_repo

    # ------------------------------------------------------------------
    # Collaborators
    # ------------------------------------------------------------------

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
                self.login_user.user_id, knowledge=space
            )
            es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
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
        max_content: int,
    ) -> list[tuple[int, Document]]:
        """Fan out over already-loaded knowledge rows and flatten the results.

        Takes **rows**, not ids: reachability (existence, type support, grant)
        is the caller's decision, so the engine never has to answer "does this
        knowledge base exist" — which is precisely the question the open face
        must not answer distinguishably.
        """
        filters = tag_filters or {}
        per_target = await asyncio.gather(
            *(
                self._retrieve_one(target, query=query, tag_names=filters.get(target.id) or [], max_content=max_content)
                for target in targets
            )
        )
        flattened: list[tuple[int, Document]] = []
        for chunks in per_target:
            flattened.extend(chunks)
        return flattened

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
