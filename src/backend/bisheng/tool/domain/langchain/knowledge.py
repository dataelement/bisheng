from typing import Any, Type, List

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate, ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from bisheng.core.ai.rerank.rrf_rerank import RRFRerank

system_template = """# 任务
你是一位知识库问答助手，遵守以下规则回答问题：
1. 严谨、专业地回答用户的问题。
2. 回答时须严格基于【参考文本】中的内容：
- 如果【参考文本】中有明确与用户问题相关的文字内容，请依据相关内容进行回答；如果【参考文本】中没有任何与用户问题相关的内容，则直接回复：“没有找到相关内容”。
- 如果相关内容中包含 markdown 格式的图片（例如 ![image](路径/IMAGE_1.png)），必须严格保留其原始 markdown 格式，不得添加引号、代码块（`或```）或其他特殊符号，也不得修改图片路径，保证可以正常渲染 markdown 图片。
3. 当【参考文本】中的内容来源于多个不同的信息源时，若相关内容存在明显差异或冲突，请分别列出这些差异或冲突的答案；若无差异或冲突，只给出一个统一的回答即可。

# 参考文本
{context}"""
messages = [
    SystemMessagePromptTemplate.from_template(system_template),
    HumanMessagePromptTemplate.from_template("{question}"),
]
CHAT_PROMPT = ChatPromptTemplate.from_messages(messages)


class ToolInputSchema(BaseModel):
    query: str = Field(description='question asked by the user.')


class KnowledgeRagTool(BaseTool):
    vector_retriever: BaseRetriever
    elastic_retriever: BaseRetriever
    llm: BaseChatModel
    max_content: int = Field(default=15000, description='The max length of the combined document content.')
    sort_by_source_and_index: bool = Field(default=False, description='Sort by document name & chunk index.')

    name: str
    description: str
    args_schema: Type[BaseModel] = ToolInputSchema

    @classmethod
    def init_knowledge_rag_tool(cls, name: str, description: str, **kwargs) -> BaseTool:
        return cls(name=name,
                   description=description,
                   args_schema=ToolInputSchema,
                   **kwargs)

    def _run(self, query: str) -> Any:
        # 1. retrieve documents
        milvus_docs = self.vector_retriever.invoke(query)
        es_docs = self.elastic_retriever.invoke(query)
        return self._rag(query, milvus_docs, es_docs)

    async def _arun(self, query: str) -> Any:
        milvus_docs = await self.vector_retriever.ainvoke(query)
        es_docs = await self.elastic_retriever.ainvoke(query)
        return self._rag(query, milvus_docs, es_docs)

    def _rag(self, query: str, milvus_docs: List[Document], es_docs: List[Document]) -> Any:
        # 2. merge documents
        rrf_rerank = RRFRerank(retrievers=[self.vector_retriever, self.elastic_retriever],
                               remove_zero_score=False)
        finally_docs = rrf_rerank.compress_documents(documents=[es_docs, milvus_docs], query=query)

        # 4. limit by max_chunk_size
        doc_num, doc_content_sum = 0, 0
        same_file_id = set()

        for doc in finally_docs:
            if doc_content_sum > self.max_content:
                break
            doc_content_sum += len(doc.page_content)
            same_file_id.add(doc.metadata.get('document_id') or doc.metadata.get('file_id'))
            doc_num += 1
        finally_docs = finally_docs[:doc_num]

        if self.sort_by_source_and_index and len(same_file_id) == 1:
            finally_docs = sorted(finally_docs,
                                  key=lambda x: (x.metadata.get('document_name', ""), x.metadata['chunk_index']))

        qa_chain = create_stuff_documents_chain(llm=self.llm, prompt=CHAT_PROMPT)
        inputs = {
            "context": finally_docs,
        }
        if "question" in CHAT_PROMPT.input_variables:
            inputs["question"] = query
        return qa_chain.invoke(inputs)
