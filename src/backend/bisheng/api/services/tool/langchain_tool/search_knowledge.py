import json
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.api.services.knowledge_imp import decide_vectorstores
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.database.models.llm_server import LLMDao
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.utils.embedding import decide_embeddings


class ToolInput(BaseModel):
    query: str = Field(..., description='需要检索的关键词')
    file_id: Optional[str] = Field(default=None, description='文件储存在语义检索库中的id')
    knowledge_id: Optional[str] = Field(default=None, description='知识库储存在语义检索库中的id')
    limit: Optional[int] = Field(default=2, description='返回结果的最大数量')
    call_reason: str = Field(default='', description='调用该工具的原因，原因中不要使用id来描述文件或知识库')


class SearchKnowledgeBase(BaseTool):
    name: str = "search_knowledge_base"
    description: str = """在语义检索库中搜索相关内容。

        用法：在你需要从大量文件中或大文件中进行语义搜索时，调用此工具。file_id和knowledge_id只能输入其中一个。

        Args:
            query: 需要检索的关键词
            file_id: 文件储存在语义检索库中的id
            knowledge_id: 知识库储存在语义检索库中的id
            limit: 返回结果的最大数量，默认为2

        Returns:
            包含搜索结果（chunk的列表）的字典"""
    args_schema: Type[BaseModel] = ToolInput

    def _run(self, query: str, file_id: Optional[str] = None, knowledge_id: Optional[str] = None,
             **kwargs) -> str:
        """Use the tool."""
        return "not supported in sync mode, please use async version"

    async def _arun(self, query: str, file_id: Optional[str] = None, knowledge_id: Optional[str] = None,
                    **kwargs) -> str:
        limit = kwargs.get('limit', None) or 2
        if not query:
            return ""
        if file_id and file_id.strip() and knowledge_id and knowledge_id.strip():
            raise Exception("只能提供file_id或knowledge_id其中一个参数，不能同时提供")

        if file_id and file_id.strip():
            return await self.search_linsight_file(query, file_id, limit)
        elif knowledge_id and knowledge_id.strip():
            return await self.search_knowledge(query, knowledge_id, limit)
        else:
            raise Exception("必须提供file_id或knowledge_id其中一个参数来进行检索")

    async def search_linsight_file(self, query: str, file_id: str, limit: int) -> str:
        """检索Linsight用户上传的文件"""
        session_info = await LinsightSessionVersionDao.get_session_version_by_file_id(file_id=file_id)
        if not session_info:
            return '{"状态": "错误", "错误信息":"文件不存在或已被删除"}'
        files = session_info.files
        file_info = None
        for one in files:
            if one.get("file_id") == file_id:
                file_info = one
                break
        if not file_info:
            return '{"状态": "错误", "错误信息":"文件不存在或已被删除"}'
        class_obj = import_vectorstore('Milvus')
        embeddings = decide_embeddings(file_info.get("embedding_model_id"))
        params = {
            'collection_name': file_info.get("collection_name"),
            'embedding': embeddings,
            'metadata_expr': f'file_id in {[file_id]}'
        }
        milvus_client = instantiate_vectorstore('Milvus', class_object=class_obj, params=params)
        documents = await milvus_client.asimilarity_search(query, k=limit)
        if not documents:
            # "没有找到相关的知识内容"
            return '{"状态": "无结果", "错误信息":"没有找到相关的知识内容"}'
        result = {
            "状态": "成功",
            "结果": [one.page_content for one in documents]
        }
        result = json.dumps(result, ensure_ascii=False, indent=2)

        return result

    async def search_knowledge(self, query: str, knowledge_id: str, limit: int) -> str:
        knowledge_info = KnowledgeDao.query_by_id(int(knowledge_id))
        if not knowledge_info:
            return '{"状态": "错误", "错误信息":"知识库不存在或已被删除"}'
        if not knowledge_info.model:
            # "知识库未配置embedding模型"
            return '{"状态": "错误", "错误信息":"知识库未配置embedding模型"}'
        embed_info = LLMDao.get_model_by_id(int(knowledge_info.model))
        if not embed_info:
            # "知识库配置的embedding模型不存在或已被删除"
            return '{"状态": "错误", "错误信息":"知识库配置的embedding模型不存在或已被删除"}'
        embeddings = decide_embeddings(knowledge_info.model)
        vector_client = decide_vectorstores(
            knowledge_info.collection_name, "Milvus", embeddings
        )
        documents = await vector_client.asimilarity_search(query, k=limit)
        if not documents:
            # "没有找到相关的知识内容"
            return '{"状态": "无结果", "错误信息":"没有找到相关的知识内容"}'
        result = {
            "状态": "成功",
            "结果": [one.page_content for one in documents]
        }
        result = json.dumps(result, ensure_ascii=False, indent=2)

        return result
