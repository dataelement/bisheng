import json
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.citation.domain.services.citation_prompt_helper import (
    annotate_rag_documents_with_citations,
    cache_citation_registry_items,
    collect_rag_citation_registry_items,
)
from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

# Content budget of one search before the first ``limit`` chunks are taken. It
# matches the daily-chat default, so both modes fuse and cut the same candidates.
SEARCH_MAX_CONTENT = 15000


class ToolInput(BaseModel):
    query: str = Field(..., description="需要检索的关键词")
    knowledge_id: str = Field(..., description="知识库或知识空间的id")
    limit: int = Field(default=2, description="返回结果的最大数量")
    call_reason: str = Field(default="", description="调用该工具的原因，原因中不要使用id来描述知识库")


class SearchKnowledgeBase(BaseTool):
    name: str = "search_knowledge_base"
    description: str = """在知识库或知识空间中检索(关键词与语义混合检索)。

        用法:当你需要从知识库 / 知识空间中检索相关内容时,调用此工具。
        本工具只检索知识库和知识空间;用户上传的文件请直接用 ls / read_file 在工作目录中查看,不要在此检索。

        Args:
            query: 需要检索的关键词
            knowledge_id: 知识库或知识空间的id
            limit: 返回结果的最大数量，默认为2

        Returns:
            包含搜索结果(chunk 列表)的字典"""
    args_schema: type[BaseModel] = ToolInput

    # C4 permission isolation: the whitelist of knowledge ids the model may
    # search — the user-visible KB ids plus this session's uploaded file ids,
    # resolved at agent-assembly time. ``None`` disables gating (back-compat for
    # callers that don't inject it). The prompt advertises these same ids, but a
    # model can hallucinate or be coaxed into an arbitrary id; without this gate
    # that id would reach ``KnowledgeDao.query_by_id`` directly and leak another
    # tenant's / unauthorised KB content.
    allowed_knowledge_ids: set[str] | None = None
    # F069: per-run citation scope (LinsightCitationScope). Every registered hit is
    # reported so the completion audit can count sources seen in BOTH the main
    # graph and the researcher sub-graph (they share this tool instance). None
    # keeps the pre-F069 behaviour.
    citation_scope: Any | None = None
    # The user of the task. Retrieval runs the daily-chat path as this user, so
    # knowledge spaces get the same view_space / view_file checks.
    login_user: Any | None = None

    def _run(self, query: str, knowledge_id: str | None = None, **kwargs) -> str:
        """Use the tool."""
        return "not supported in sync mode, please use async version"

    async def _arun(self, query: str, knowledge_id: str | None = None, **kwargs) -> str:
        limit = kwargs.get("limit", None) or 2
        if not query:
            return '{"状态": "失败", "错误信息": "检索关键词不能为空"}'

        # Enforce the whitelist before any DB/vector lookup (C4). An id outside
        # the user's accessible set is refused outright — never queried.
        if self.allowed_knowledge_ids is not None and str(knowledge_id) not in self.allowed_knowledge_ids:
            logger.warning(f"search_knowledge_base rejected out-of-whitelist knowledge_id={knowledge_id!r}")
            return json.dumps(
                {"状态": "无权限", "错误信息": "该知识库不在当前任务可用的知识库列表中"},
                ensure_ascii=False,
            )

        # knowledge_id must be a numeric knowledge-base / knowledge-space id. The
        # model sometimes hallucinates a non-numeric sentinel (e.g.
        # 'general_knowledge') or passes an uploaded file_id — uploaded files are
        # NOT searched here (they are read from the workspace via read_file), so a
        # non-numeric id is simply "no result". A tool failure must NOT raise —
        # that propagates through the deepagents tool node and kills the whole
        # task. Return a soft error so the agent can recover and continue.
        try:
            try:
                kid = int(knowledge_id)
            except (ValueError, TypeError):
                return json.dumps(
                    {"状态": "无结果", "错误信息": "knowledge_id 不是有效的知识库/知识空间 id"},
                    ensure_ascii=False,
                )
            return await self.search_knowledge(query, kid, limit)
        except Exception as e:
            logger.warning(f"search_knowledge_base failed for knowledge_id={knowledge_id!r}: {e}")
            return json.dumps(
                {
                    "状态": "失败",
                    "错误信息": FailureContextAdapter.safe_detail(e),
                    **({"failure_info": info} if (info := FailureContextAdapter.from_error(e)) else {}),
                },
                ensure_ascii=False,
            )

    async def format_documents(self, documents: list, knowledge_id=None, knowledge_name: str = "") -> str:
        """The tool result for ``documents``: citation-annotated chunks, or a no-result message."""
        if not documents:
            # "没有找到相关的知识内容"
            return '{"状态": "无结果", "错误信息":"没有找到相关的知识内容"}'
        try:
            for document in documents:
                metadata = dict(document.metadata or {})
                if knowledge_id is not None:
                    metadata.setdefault("knowledge_id", knowledge_id)
                if knowledge_name:
                    metadata.setdefault("knowledge_name", knowledge_name)
                metadata.setdefault("access_scope", "per_user")
                document.metadata = metadata
            annotated = annotate_rag_documents_with_citations(documents)
            items = collect_rag_citation_registry_items(annotated)
            await cache_citation_registry_items(items)
            handles: dict[str, str] = {}
            if self.citation_scope is not None:
                await self.citation_scope.record_seen(items)
                if getattr(self.citation_scope, "enabled", False):
                    from bisheng.citation.domain.services.citation_handle_service import assign_handles

                    handles = await assign_handles(self.citation_scope, items)
            formatted = [KnowledgeUtils.format_retrieved_chunk(doc, knowledge_name) for doc in annotated]
            if handles:
                # F069 P1: the model sees a short handle instead of the registry key.
                # format_retrieved_chunk itself is shared platform-wide and untouched;
                # an allocation failure (empty mapping) keeps the F047 shape.
                from bisheng.citation.domain.services.citation_handle_service import swap_chunk_id_for_handle

                formatted = [swap_chunk_id_for_handle(chunk, handles) for chunk in formatted]
            return json.dumps({"状态": "成功", "结果": formatted}, ensure_ascii=False, indent=2)
        except Exception:
            logger.opt(exception=True).warning("search_knowledge_base citation annotate failed; returning bare chunks")
            return json.dumps(
                {"状态": "成功", "结果": [one.page_content for one in documents]},
                ensure_ascii=False,
                indent=2,
            )

    async def search_knowledge(self, query: str, knowledge_id: int, limit: int) -> str:
        """Search one knowledge base or space the way daily chat does.

        ES and Milvus results are fused (RRF) and the user's file permissions
        apply (``WorkStationService.queryChunksFromDB``). The fused rank order
        is kept, and the first ``limit`` chunks are returned.
        """
        if self.login_user is None:
            raise Exception("search_knowledge_base has no user identity")
        from bisheng.workstation.domain.schemas.chat import UseKnowledgeBaseParam
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        # queryChunksFromDB reads the actual type of each id, so a knowledge
        # space id may sit in the organization list too.
        _, documents, failures = await WorkStationService.queryChunksFromDB(
            query,
            UseKnowledgeBaseParam(organization_knowledge_ids=[knowledge_id]),
            SEARCH_MAX_CONTENT,
            self.login_user,
            sort_by_source_and_index=False,
        )
        if not documents and failures:
            failure = failures[0]
            return json.dumps(
                {
                    "状态": "失败",
                    "错误信息": failure.get("error") or "知识库检索失败",
                    **({"failure_info": failure["failure_info"]} if failure.get("failure_info") else {}),
                },
                ensure_ascii=False,
            )
        documents = list(documents or [])[:limit]
        knowledge_name = ""
        if documents:
            from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

            knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
            knowledge_name = getattr(knowledge, "name", "") or ""
        return await self.format_documents(documents, knowledge_id=knowledge_id, knowledge_name=knowledge_name)
