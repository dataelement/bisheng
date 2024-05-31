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
from langchain_core.documents import Document
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import PromptTemplate
from langchain_core.pydantic_v1 import Extra, Field
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus

from langchain.chains.base import Chain
from .bisheng_rag_tool import BishengRAGTool


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
        max_content: int = 15000,
        sort_by_source_and_index: bool = True,
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> BishengRetrievalQA:
        bisheng_rag_tool = BishengRAGTool(
            vector_store=vector_store, 
            keyword_store=keyword_store,
            llm=llm,
            max_content=max_content,
            sort_by_source_and_index=sort_by_source_and_index,
            **kwargs
        )
        return cls(
            bisheng_rag_tool=bisheng_rag_tool,
            callbacks=callbacks,
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