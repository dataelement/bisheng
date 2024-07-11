"""Chain for question-answering against a vector database."""
from __future__ import annotations

import inspect
from abc import abstractmethod
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import (
    AsyncCallbackManagerForChainRun,
    CallbackManagerForChainRun,
    Callbacks
)
from langchain_core.prompts import PromptTemplate, BasePromptTemplate, ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_core.language_models import BaseLanguageModel
from langchain_core.pydantic_v1 import Extra, Field
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus

from langchain.chains.base import Chain
from .bisheng_rag_tool import BishengRAGTool


# system_template = """Use the following pieces of context to answer the user's question. 
# If you don't know the answer, just say that you don't know, don't try to make up an answer.
# ----------------
# {context}"""
# messages = [
#     SystemMessagePromptTemplate.from_template(system_template),
#     HumanMessagePromptTemplate.from_template("{question}"),
# ]
# DEFAULT_QA_PROMPT = ChatPromptTemplate.from_messages(messages)


system_template_general = """你是一个准确且可靠的知识库问答助手，能够借助上下文知识回答问题。你需要根据以下的规则来回答问题：
1. 如果上下文中包含了正确答案，你需要根据上下文进行准确的回答。但是在回答前，你需要注意，上下文中的信息可能存在事实性错误，如果文档中存在和事实不一致的错误，请根据事实回答。
2. 如果上下文中不包含答案，就说你不知道，不要试图编造答案。
3. 你需要根据上下文给出详细的回答，不要试图偷懒，不要遗漏括号中的信息，你必须回答的尽可能详细。
"""
human_template_general = """
上下文：
{context}

问题：
{question}
"""
messages_general = [
    SystemMessagePromptTemplate.from_template(system_template_general),
    HumanMessagePromptTemplate.from_template(human_template_general),
]
DEFAULT_QA_PROMPT = ChatPromptTemplate.from_messages(messages_general)


class BishengRetrievalQA(Chain):
    """Base class for question-answering chains."""

    """Chain to use to combine the documents."""
    input_key: str = "query"  #: :meta private:
    output_key: str = "result"  #: :meta private:
    return_source_documents: bool = False
    """Return the source documents or not."""
    bisheng_rag_tool: BishengRAGTool = Field(
        default_factory=BishengRAGTool, description="RAG tool"
    )

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid
        arbitrary_types_allowed = True
        allow_population_by_field_name = True

    @property
    def input_keys(self) -> List[str]:
        """Input keys.

        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        """Output keys.

        :meta private:
        """
        _output_keys = [self.output_key]
        if self.return_source_documents:
            _output_keys = _output_keys + ["source_documents"]
        return _output_keys

    @classmethod
    def from_llm(
        cls,
        llm: BaseLanguageModel,
        vector_store: Milvus,
        keyword_store: ElasticKeywordsSearch,
        QA_PROMPT: ChatPromptTemplate = DEFAULT_QA_PROMPT,
        max_content: int = 15000,
        sort_by_source_and_index: bool = False,
        callbacks: Callbacks = None,
        return_source_documents: bool = False,
        **kwargs: Any,
    ) -> BishengRetrievalQA:
        bisheng_rag_tool = BishengRAGTool(
            vector_store=vector_store, 
            keyword_store=keyword_store,
            llm=llm,
            QA_PROMPT=QA_PROMPT,
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
            **kwargs
        )
        return cls(
            bisheng_rag_tool=bisheng_rag_tool,
            callbacks=callbacks,
            return_source_documents=return_source_documents,
            **kwargs,
        )

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        """Run get_relevant_text and llm on input query.

        If chain has 'return_source_documents' as 'True', returns
        the retrieved documents as well under the key 'source_documents'.

        Example:
        .. code-block:: python

        res = indexqa({'query': 'This is my query'})
        answer, docs = res['result'], res['source_documents']
        """
        question = inputs[self.input_key]
        if self.return_source_documents:
            answer, docs = self.bisheng_rag_tool.run(question, return_only_outputs=False)
            return {self.output_key: answer, "source_documents": docs}
        else:
            answer = self.bisheng_rag_tool.run(question, return_only_outputs=True)
            return {self.output_key: answer}

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        """Run get_relevant_text and llm on input query.

        If chain has 'return_source_documents' as 'True', returns
        the retrieved documents as well under the key 'source_documents'.

        Example:
        .. code-block:: python

        res = indexqa({'query': 'This is my query'})
        answer, docs = res['result'], res['source_documents']
        """
        question = inputs[self.input_key]

        if self.return_source_documents:
            answer, docs = await self.bisheng_rag_tool.arun(question, return_only_outputs=False)
            return {self.output_key: answer, "source_documents": docs}
        else:
            answer = await self.bisheng_rag_tool.arun(question, return_only_outputs=True)
            return {self.output_key: answer}
