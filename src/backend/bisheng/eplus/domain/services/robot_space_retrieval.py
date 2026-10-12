"""E+ robot knowledge scope enforcement.

The robot binding is the complete authorization boundary for E+ retrieval. It
does not intersect with, or expand from, the sender's personal knowledge-space
permissions. Every turn supplies an immutable binding snapshot, and retrieval
post-filters returned chunks against current successful file rows so stale
vector hits cannot escape that turn's configured scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from langchain_core.documents import Document
from loguru import logger
from pydantic import Field

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.eplus.domain.schemas.knowledge import RobotFileSource, RobotKnowledgeInput
from bisheng.eplus.domain.services.retrieval_ranking import rank_robot_candidates, trim_robot_candidates
from bisheng.tool.domain.langchain.knowledge import KnowledgeRagTool, KnowledgeRetrieverTool
from bisheng.utils.async_utils import run_async_safe

_DEFAULT_RRF_WEIGHTS = [0.5, 0.5]
_BISHENG_KNOWLEDGE_ENDPOINTS = (
    "/api/v1/knowledge",
    "/api/v1/filelib",
    "/api/v2/knowledge",
    "/api/v2/filelib",
)
_KNOWLEDGE_FLOW_NODE_TYPES = {
    "knowledge",
    "knowledge_retriever",
    "knowledge_retrieval",
    "rag",
    "qa_retriever",
}


class RobotToolScopeViolation(PermissionError):
    """Raised when an E+ execution could bypass the robot-bound knowledge scope."""


class RobotDocumentStateReader(Protocol):
    async def search_file_sources(
        self, *, tenant_id: int, space_ids: tuple[int, ...], keywords: tuple[str, ...], limit: int = 50
    ) -> dict[int, RobotFileSource]: ...

    async def file_sources(
        self,
        *,
        tenant_id: int,
        space_ids: tuple[int, ...],
        file_ids: set[int] | None = None,
        file_name: str | None = None,
    ) -> dict[int, RobotFileSource]: ...


class RobotRetrievalBackend(Protocol):
    async def retrieve_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        query: str,
        invoke_user_id: int,
        max_content: int,
        sort_by_source_and_index: bool,
        file_ids: tuple[int, ...] | None = None,
    ) -> list[Document]: ...


class RobotSpaceRetrievalPolicy:
    def __init__(
        self,
        *,
        tenant_id: int,
        bot_config_id: int,
        invoke_user_id: int,
        document_state_reader: RobotDocumentStateReader | None = None,
        retrieval_backend: RobotRetrievalBackend | None = None,
    ) -> None:
        from bisheng.eplus.infrastructure.robot_retrieval import (
            DatabaseRobotDocumentStateReader,
            DatabaseRobotRetrievalBackend,
        )

        self.tenant_id = int(tenant_id)
        self.bot_config_id = int(bot_config_id)
        self.invoke_user_id = int(invoke_user_id)
        self.document_state_reader = document_state_reader or DatabaseRobotDocumentStateReader()
        self.retrieval_backend = retrieval_backend or DatabaseRobotRetrievalBackend()

    async def retrieve(
        self,
        query: str,
        *,
        expected_scope: AssistantRobotScope,
        max_content: int = 15000,
        sort_by_source_and_index: bool = False,
        file_name: str | None = None,
        file_name_query: str | None = None,
    ) -> list[Document]:
        space_ids = tuple(sorted({int(space_id) for space_id in expected_scope.space_ids}))
        if not space_ids:
            return []

        if file_name_query is not None:
            keywords = tuple(dict.fromkeys(file_name_query.split()))
            if not keywords or file_name is not None:
                raise ValueError("filename keywords must be nonblank and exclusive of exact filename")
            matches = await self.document_state_reader.search_file_sources(
                tenant_id=self.tenant_id, space_ids=space_ids, keywords=keywords
            )
            logger.info("E+ filename search bot={} spaces={} matched={}", self.bot_config_id, space_ids, len(matches))
            if matches:
                return [
                    Document(page_content="", metadata={**_source_metadata(source), "source_only": True})
                    for source in matches.values()
                ]

        matched_sources = None
        if file_name is not None:
            matched_sources = await self.document_state_reader.file_sources(
                tenant_id=self.tenant_id,
                space_ids=space_ids,
                file_name=file_name,
            )
            if not matched_sources:
                return []

        candidates: list[Document] = []
        recalled = {}
        for space_id in space_ids:
            selected_ids = (
                None
                if matched_sources is None
                else tuple(fid for fid, source in matched_sources.items() if source.space_id == space_id)
            )
            if selected_ids == ():
                continue
            documents = await self.retrieval_backend.retrieve_space(
                space_id=space_id,
                tenant_id=self.tenant_id,
                query=query,
                invoke_user_id=self.invoke_user_id,
                max_content=max_content,
                sort_by_source_and_index=sort_by_source_and_index,
                file_ids=selected_ids,
            )
            recalled[space_id] = len(documents)
            for rank, doc in enumerate(documents, 1):
                candidates.append(
                    Document(page_content=doc.page_content, metadata={"robot_recall_rank": rank, **doc.metadata})
                )

        file_ids = {_document_id(doc) for doc in candidates}
        file_ids.discard(None)
        sources = await self.document_state_reader.file_sources(
            tenant_id=self.tenant_id,
            space_ids=space_ids,
            file_ids=set(matched_sources) if matched_sources is not None else {int(file_id) for file_id in file_ids},
            file_name=file_name,
        )

        result: list[Document] = []
        seen: set[tuple[int, int, str]] = set()
        for document in candidates:
            file_id = _document_id(document)
            if file_id is None or file_id not in sources:
                continue
            metadata = dict(document.metadata or {})
            key = (file_id, int(metadata.get("chunk_index") or 0), document.page_content)
            if key in seen:
                continue
            seen.add(key)
            source = sources[file_id]
            metadata.update(_source_metadata(source))
            result.append(Document(page_content=document.page_content, metadata=metadata))
        result = trim_robot_candidates(rank_robot_candidates(result, query), max_content)
        # Index order is only restored for one retained file, never across spaces.
        if sort_by_source_and_index and len({_document_id(doc) for doc in result}) == 1:
            result.sort(key=lambda doc: int(doc.metadata.get("chunk_index") or 0))
        retained = {space_id: sum(doc.metadata["knowledge_id"] == space_id for doc in result) for space_id in space_ids}
        logger.info(
            "E+ retrieval fusion bot={} recalled={} retained={} content_chars={}",
            self.bot_config_id,
            recalled,
            retained,
            sum(len(doc.page_content) for doc in result),
        )
        if matched_sources is not None:
            retrieved_ids = {_document_id(doc) for doc in result}
            for file_id, source in sources.items():
                if file_id not in retrieved_ids:
                    result.append(Document(page_content="", metadata={**_source_metadata(source), "source_only": True}))
        return result

    async def build_tool(
        self,
        *,
        llm: Any,
        expected_scope: AssistantRobotScope,
        max_content: int = 15000,
        sort_by_source_and_index: bool = False,
    ) -> KnowledgeRagTool:
        retriever = RobotSpaceRetrieverTool(
            policy=self,
            expected_scope=expected_scope,
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
            rrf_weights=_DEFAULT_RRF_WEIGHTS,
        )
        return RobotKnowledgeRagTool(
            name="eplus_robot_knowledge",
            description=(
                "检索机器人可用知识空间中的文档内容, 或核实具体文件的归属。"
                "用户指定完整文件名时必须传 file_name, 仅查询该文件, 不用其他文件代替。"
                "用户问某主题有哪些文件时, 传 file_name_query 为主题关键词(多词用空格分隔), 优先按真实文件名查找;"
                "文件名未命中时回退正文检索。具体内容问答不传 file_name_query。"
                "sources 是后台核实的文件归属, chunks 仅是相关正文, 正文中的名称和编号不是来源。"
                "只能说明本次命中的文件, 不能列出空间完整目录或推断部门归属; 未命中不代表不存在。"
            ),
            llm=llm,
            knowledge_retriever_tool=retriever,
        )


class RobotSpaceRetrieverTool(KnowledgeRetrieverTool):
    args_schema: type = RobotKnowledgeInput
    policy: Any = Field(exclude=True)
    expected_scope: Any = Field(exclude=True)

    def _run(self, query: str, **kwargs: Any) -> list[Document]:
        return run_async_safe(
            self._aretrieve(query, file_name=kwargs.get("file_name"), file_name_query=kwargs.get("file_name_query")),
            timeout=120,
        )

    async def _arun(self, query: str, **kwargs: Any) -> list[Document]:
        return await self._aretrieve(
            query, file_name=kwargs.get("file_name"), file_name_query=kwargs.get("file_name_query")
        )

    async def _aretrieve(
        self, query: str, *, file_name: str | None = None, file_name_query: str | None = None
    ) -> list[Document]:
        return await self.policy.retrieve(
            query,
            expected_scope=self.expected_scope,
            max_content=self.max_content,
            sort_by_source_and_index=self.sort_by_source_and_index,
            file_name=file_name,
            file_name_query=file_name_query,
        )


class RobotKnowledgeRagTool(KnowledgeRagTool):
    args_schema: type = RobotKnowledgeInput
    robot_scope_enforced: bool = True


def _source_metadata(source: RobotFileSource) -> dict[str, Any]:
    return {
        "document_id": source.file_id,
        "document_name": source.file_name,
        "knowledge_id": source.space_id,
        "kb_id": source.space_id,
        "knowledge_name": source.space_name,
        "access_scope": "robot_bound",
    }


def _document_id(document: Document) -> int | None:
    value = (document.metadata or {}).get("document_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iter_endpoint_values(value: Any, *, depth: int = 0) -> Sequence[str]:
    if value is None or depth > 5:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, nested in value.items():
            if str(key).lower() in {"endpoint", "url", "path", "route", "schema", "api_schema"}:
                values.extend(_iter_endpoint_values(nested, depth=depth + 1))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = []
        for nested in value:
            values.extend(_iter_endpoint_values(nested, depth=depth + 1))
        return values

    values = []
    for attribute in ("endpoint", "url", "path", "route", "schema", "api_schema", "tool_instance"):
        if hasattr(value, attribute):
            values.extend(_iter_endpoint_values(getattr(value, attribute), depth=depth + 1))
    return values


def assert_eplus_tool_scope(tool: Any) -> Any:
    if getattr(tool, "robot_scope_enforced", False):
        return tool
    endpoints = "\n".join(_iter_endpoint_values(tool)).lower()
    if any(route in endpoints for route in _BISHENG_KNOWLEDGE_ENDPOINTS):
        raise RobotToolScopeViolation("E+ tool targets a BiSheng knowledge endpoint without robot scope")
    return tool


def flow_uses_bisheng_knowledge(flow_data: Any) -> bool:
    if isinstance(flow_data, Mapping):
        node_type = flow_data.get("type") or flow_data.get("node_type")
        if isinstance(node_type, str) and node_type.lower() in _KNOWLEDGE_FLOW_NODE_TYPES:
            return True
        if any(key in flow_data for key in ("knowledge_id", "knowledge_ids", "space_ids")):
            return True
        return any(flow_uses_bisheng_knowledge(value) for value in flow_data.values())
    if isinstance(flow_data, Sequence) and not isinstance(flow_data, (str, bytes, bytearray)):
        return any(flow_uses_bisheng_knowledge(value) for value in flow_data)
    return False
