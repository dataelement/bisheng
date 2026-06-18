import json

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.llm.domain.share_fallback import (
    get_model_by_id_with_share_fallback,
)


class ToolInput(BaseModel):
    query: str = Field(..., description="需要检索的关键词")
    knowledge_id: str = Field(..., description="知识库或知识空间的id")
    limit: int = Field(default=2, description="返回结果的最大数量")
    call_reason: str = Field(default="", description="调用该工具的原因，原因中不要使用id来描述知识库")


class SearchKnowledgeBase(BaseTool):
    name: str = "search_knowledge_base"
    description: str = """在知识库或知识空间中进行语义检索。

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
                {"状态": "无结果", "错误信息": f"知识库检索失败或知识库不存在: {e}"},
                ensure_ascii=False,
            )

    async def base_search(self, vector_client, query: str, k: int, **kwargs) -> str:
        documents = await vector_client.asimilarity_search(query, k=k, **kwargs)
        if not documents:
            # "没有找到相关的知识内容"
            return '{"状态": "无结果", "错误信息":"没有找到相关的知识内容"}'
        result = {"状态": "成功", "结果": [one.page_content for one in documents]}
        result = json.dumps(result, ensure_ascii=False, indent=2)

        return result

    async def search_knowledge(self, query: str, knowledge_id: int, limit: int) -> str:
        knowledge_info = KnowledgeDao.query_by_id(knowledge_id)
        if not knowledge_info:
            raise Exception("Knowledgebase does not exist or has been deleted")
        if not knowledge_info.model:
            # "Knowledge Base Not ConfiguredembeddingModels"
            raise Exception("Knowledge Base Not ConfiguredembeddingModels")
        # The KB embedding may be a Root-shared system default; read via
        # the share fallback so child tenants can resolve Root-owned rows.
        embed_info = get_model_by_id_with_share_fallback(int(knowledge_info.model))
        if not embed_info:
            # "Configured by the Knowledge BaseembeddingModel does not exist or has been deleted"
            raise Exception("Configured by the Knowledge BaseembeddingModel does not exist or has been deleted")
        milvus_client = await KnowledgeRag.init_knowledge_milvus_vectorstore(0, knowledge=knowledge_info)
        return await self.base_search(milvus_client, query, limit)
