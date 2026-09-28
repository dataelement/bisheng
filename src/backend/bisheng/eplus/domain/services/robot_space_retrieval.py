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
from pydantic import Field
from sqlmodel import col, select

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
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
    async def valid_file_ids(
        self,
        *,
        tenant_id: int,
        space_ids: tuple[int, ...],
        file_ids: set[int],
    ) -> set[int]: ...


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
    ) -> list[Document]: ...


class DatabaseRobotDocumentStateReader:
    async def valid_file_ids(
        self,
        *,
        tenant_id: int,
        space_ids: tuple[int, ...],
        file_ids: set[int],
    ) -> set[int]:
        if not space_ids or not file_ids:
            return set()
        async with get_async_db_session() as session:
            statement = select(KnowledgeFile.id).where(
                KnowledgeFile.tenant_id == tenant_id,
                col(KnowledgeFile.knowledge_id).in_(space_ids),
                col(KnowledgeFile.id).in_(file_ids),
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
            )
            return {int(file_id) for file_id in (await session.exec(statement)).all()}


class DatabaseRobotRetrievalBackend:
    async def retrieve_space(
        self,
        *,
        tenant_id: int,
        space_id: int,
        query: str,
        invoke_user_id: int,
        max_content: int,
        sort_by_source_and_index: bool,
    ) -> list[Document]:
        async with get_async_db_session() as session:
            statement = select(Knowledge).where(
                Knowledge.tenant_id == tenant_id,
                Knowledge.id == space_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
            space = (await session.exec(statement)).first()
        if space is None:
            return []

        vector_store = await KnowledgeRag.init_knowledge_milvus_vectorstore(invoke_user_id, knowledge=space)
        elastic_store = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=space)
        retriever = KnowledgeRetrieverTool(
            vector_retriever=vector_store.as_retriever(),
            elastic_retriever=elastic_store.as_retriever(),
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
            rrf_weights=_DEFAULT_RRF_WEIGHTS,
            rrf_remove_zero_score=True,
        )
        return await retriever._arun(query)


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
    ) -> list[Document]:
        space_ids = tuple(sorted({int(space_id) for space_id in expected_scope.space_ids}))
        if not space_ids:
            return []

        candidates: list[Document] = []
        for space_id in space_ids:
            candidates.extend(
                await self.retrieval_backend.retrieve_space(
                    space_id=space_id,
                    tenant_id=self.tenant_id,
                    query=query,
                    invoke_user_id=self.invoke_user_id,
                    max_content=max_content,
                    sort_by_source_and_index=sort_by_source_and_index,
                )
            )

        file_ids = {_document_id(doc) for doc in candidates}
        file_ids.discard(None)
        valid_file_ids = await self.document_state_reader.valid_file_ids(
            tenant_id=self.tenant_id,
            space_ids=space_ids,
            file_ids={int(file_id) for file_id in file_ids},
        )

        result: list[Document] = []
        seen: set[tuple[int, int, str]] = set()
        content_size = 0
        for document in candidates:
            file_id = _document_id(document)
            if file_id is None or file_id not in valid_file_ids:
                continue
            metadata = document.metadata or {}
            key = (file_id, int(metadata.get("chunk_index") or 0), document.page_content)
            if key in seen:
                continue
            if result and content_size >= max_content:
                break
            seen.add(key)
            metadata["access_scope"] = "robot_bound"
            document.metadata = metadata
            result.append(document)
            content_size += len(document.page_content)
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
            description="仅在当前 E+ 机器人绑定的知识空间中检索与查询相关的文档内容。",
            llm=llm,
            knowledge_retriever_tool=retriever,
        )


class RobotSpaceRetrieverTool(KnowledgeRetrieverTool):
    policy: Any = Field(exclude=True)
    expected_scope: Any = Field(exclude=True)

    def _run(self, query: str, **kwargs: Any) -> list[Document]:
        return run_async_safe(self._aretrieve(query), timeout=120)

    async def _arun(self, query: str, **kwargs: Any) -> list[Document]:
        return await self._aretrieve(query)

    async def _aretrieve(self, query: str) -> list[Document]:
        return await self.policy.retrieve(
            query,
            expected_scope=self.expected_scope,
            max_content=self.max_content,
            sort_by_source_and_index=self.sort_by_source_and_index,
        )


class RobotKnowledgeRagTool(KnowledgeRagTool):
    robot_scope_enforced: bool = True


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
