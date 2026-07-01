"""F041: knowledge-space retrieval helpers shared by workflow nodes and assistants.

Adds knowledge-space (``type=3``) support to the flow / assistant retrieval path,
reusing F029's two-layer ``view_file`` filter (`KnowledgeFileVisibilityService`).
The filter identity is chosen by the「用户知识库权限校验」toggle:

  - toggle ON  → runtime user (workflow ``self.user_id`` / assistant ``invoke_user_id``)
  - toggle OFF → config author (``Flow.user_id`` / ``Assistant.user_id``), resolved
                 within the current (flow) tenant WITHOUT switching the tenant
                 ContextVar.

Lives in the knowledge domain (not ``workflow/common``) so both workflow nodes and
``AssistantAgent`` can import it without a cross-module workflow dependency.
See ``features/v2.6.0/041-knowledge-space-select-flow-assistant/design.md``
(decisions 1/2/3, gotchas 5.2/5.3/5.10).
"""

from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.user.domain.models.user import UserDao


async def abuild_scoped_login_user(user_id: int | None, tenant_id: int | None) -> UserPayload | None:
    """Build a ``UserPayload`` for ``user_id`` scoped to ``tenant_id`` WITHOUT
    switching the current tenant ContextVar.

    Unlike ``resolve_operator`` (F030), this NEVER calls ``set_current_tenant_id``:
    the workflow node / assistant is mid-execution in the flow's tenant, and
    switching to the author's active tenant would pollute subsequent
    tenant-scoped queries in the same node (design gotcha 5.10). The author is
    resolved within the current (flow) tenant, which is correct because the
    selected knowledge spaces live in that tenant.

    Returns ``None`` when ``user_id`` is falsy or the user no longer exists — the
    caller treats a ``None`` identity as "no visible files" (empty retrieval).
    """
    if not user_id:
        return None
    user = await UserDao.aget_user(user_id)
    if not user:
        return None
    return await UserPayload.init_login_user(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id if tenant_id is not None else DEFAULT_TENANT_ID,
    )


def _and_milvus_expr(*exprs: str | None) -> str | None:
    """AND-combine Milvus boolean expressions, ignoring empties."""
    parts = [f"({e})" for e in exprs if e]
    return " and ".join(parts) if parts else None


def _merge_es_clauses(*clause_lists: list | None) -> list:
    """Concatenate ES filter-clause lists (ES ``filter`` is AND across clauses)."""
    merged: list = []
    for clauses in clause_lists:
        if clauses:
            merged.extend(clauses)
    return merged


async def _aretrieve_one_space(
    *,
    space,
    query: str,
    identity_user: UserPayload,
    max_content: int,
    extra_milvus_expr: str | None,
    extra_es_filter: list | None,
    rrf_weights: list | None,
    rerank: Any,
    sort_by_source_and_index: bool,
    version_repo: Any,
    request: Any,
) -> list[Document]:
    """Retrieve view_file-filtered docs from a single knowledge space.

    Mirrors F029 ``KnowledgeSpaceChatService._retrieve_and_filter`` (index prefilter
    → 2-attempt retrieval → result-layer post_filter) but AND-combines the caller's
    metadata filter (AC-08) and honors the node's advanced-retrieval knobs. The
    filter identity is ``identity_user`` (runtime user when the toggle is ON, config
    author when OFF).
    """
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
        KnowledgeFileVisibilityService,
    )
    from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool

    visibility = KnowledgeFileVisibilityService(request, identity_user)
    visibility.version_repo = version_repo

    index_filter = await visibility.build_index_prefilter(space.id, None)
    if index_filter.is_empty:
        logger.info(
            "space_flow_retrieval | space_id={} strategy=empty identity_user={} dropped=all",
            space.id,
            identity_user.user_id,
        )
        return []

    base_milvus = _and_milvus_expr(index_filter.milvus_expr, extra_milvus_expr)
    base_es = _merge_es_clauses(index_filter.es_filter, extra_es_filter)

    conf = visibility._config()
    multipliers = (conf.retrieval_initial_multiplier, conf.retrieval_expansion_multiplier)

    survivors: list[Document] = []
    for attempt_idx, multiplier in enumerate(multipliers, start=1):
        base_k = 100
        milvus_kwargs: dict[str, Any] = {"k": base_k * multiplier, "param": {"ef": 110}}
        if base_milvus:
            milvus_kwargs["expr"] = base_milvus
        es_kwargs: dict[str, Any] = {"k": base_k * multiplier}
        if base_es:
            es_kwargs["filter"] = base_es

        milvus_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(identity_user.user_id, knowledge=space)
        es_vector = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        retriever_tool = KnowledgeRetrieverTool(
            vector_retriever=milvus_vector.as_retriever(search_kwargs=milvus_kwargs),
            elastic_retriever=es_vector.as_retriever(search_kwargs=es_kwargs),
            max_content=max_content,
            rrf_weights=rrf_weights,
            rrf_remove_zero_score=True,
            rerank=rerank,
            sort_by_source_and_index=sort_by_source_and_index,
        )
        docs: list[Document] = await retriever_tool.ainvoke(query)

        unique_file_ids = {
            int(d.metadata.get("document_id")) for d in docs if d.metadata and d.metadata.get("document_id") is not None
        }
        permitted = await visibility.post_filter_visible_files(space.id, unique_file_ids)
        survivors = [d for d in docs if int(d.metadata.get("document_id", -1)) in permitted]

        logger.info(
            "space_flow_retrieval | space_id={} strategy={} identity_user={} attempt={} hit={} kept={} dropped={}",
            space.id,
            index_filter.strategy,
            identity_user.user_id,
            attempt_idx,
            len(docs),
            len(survivors),
            len(docs) - len(survivors),
        )
        if survivors:
            break
    return survivors


async def aretrieve_space_documents(
    *,
    space_ids: list[int | str],
    query: str,
    identity_user: UserPayload | None,
    max_content: int,
    extra_milvus_expr: str | None = None,
    extra_es_filter: list | None = None,
    rrf_weights: list | None = None,
    rerank: Any = None,
    sort_by_source_and_index: bool = True,
    version_repo: Any = None,
    request: Any = None,
) -> list[Document]:
    """Retrieve view_file-filtered chunks across one or more knowledge spaces.

    F041 entry shared by workflow nodes (rag / knowledge_retriever / agent) and
    ``AssistantAgent``. ``identity_user`` decides the filter identity (runtime user
    ON / config author OFF). Returns Documents in the same shape as document-KB
    retrieval, so the caller can reuse the unified citation path (6.3).

    ``identity_user is None`` (e.g. author could not be resolved) → empty result,
    treated as "no visible files".
    """
    if identity_user is None or not space_ids:
        return []

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

    docs: list[Document] = []
    for raw_id in space_ids:
        try:
            space = await KnowledgeDao.aquery_by_id(int(raw_id))
        except (TypeError, ValueError):
            continue
        if not space:
            continue
        docs.extend(
            await _aretrieve_one_space(
                space=space,
                query=query,
                identity_user=identity_user,
                max_content=max_content,
                extra_milvus_expr=extra_milvus_expr,
                extra_es_filter=extra_es_filter,
                rrf_weights=rrf_weights,
                rerank=rerank,
                sort_by_source_and_index=sort_by_source_and_index,
                version_repo=version_repo,
                request=request,
            )
        )
    return docs
