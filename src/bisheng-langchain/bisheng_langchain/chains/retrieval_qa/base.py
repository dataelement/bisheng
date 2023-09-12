from typing import List

from langchain.callbacks.manager import AsyncCallbackManagerForChainRun, CallbackManagerForChainRun
from langchain.chains.retrieval_qa.base import BaseRetrievalQA
from pydantic import Field
from langchain.schema import BaseRetriever, Document


class MultiRetrievalQA(BaseRetrievalQA):
    """Chain for question-answering against an index.

    Example:
        .. code-block:: python

            from langchain.llms import OpenAI
            from langchain.chains import RetrievalQA
            from langchain.faiss import FAISS
            from langchain.vectorstores.base import VectorStoreRetriever
            retriever = VectorStoreRetriever(vectorstore=FAISS(...))
            retrievalQA = RetrievalQA.from_llm(llm=OpenAI(), retriever=retriever)

    """

    vector_retriever: BaseRetriever = Field(exclude=True)
    keyword_retriever: BaseRetriever = Field(exclude=True)
    combine_strategy: str = 'keyword_front'  # "keyword_front, vector_front, mix"

    def _get_docs(
        self,
        question: str,
        *,
        run_manager: CallbackManagerForChainRun,
    ) -> List[Document]:
        """Get docs."""
        vector_docs = self.vector_retriever.get_relevant_documents(
            question, callbacks=run_manager.get_child())
        keyword_docs = self.keyword_retriever.get_relevant_documents(
            question, callbacks=run_manager.get_child())
        if self.combine_strategy == 'keyword_front':
            return keyword_docs + vector_docs
        elif self.combine_strategy == 'vector_front':
            return vector_docs + keyword_docs
        elif self.combine_strategy == 'mix':
            combine_docs = []
            min_len = min(len(keyword_docs), len(vector_docs))
            for i in range(min_len):
                combine_docs.append(keyword_docs[i])
                combine_docs.append(vector_docs[i])
            combine_docs.extend(keyword_docs[min_len:])
            combine_docs.extend(vector_docs[min_len:])
            return combine_docs
        else:
            raise ValueError(f'Expected combine_strategy to be one of '
                             f'(keyword_front, vector_front, mix),'
                             f'instead found {self.combine_strategy}')

    async def _aget_docs(
        self,
        question: str,
        *,
        run_manager: AsyncCallbackManagerForChainRun,
    ) -> List[Document]:
        """Get docs."""
        vector_docs = await self.vector_retriever.get_relevant_documents(
            question, callbacks=run_manager.get_child())
        keyword_docs = await self.keyword_retriever.get_relevant_documents(
            question, callbacks=run_manager.get_child())
        if self.combine_strategy == 'keyword_front':
            return keyword_docs + vector_docs
        elif self.combine_strategy == 'vector_front':
            return vector_docs + keyword_docs
        elif self.combine_strategy == 'mix':
            combine_docs = []
            min_len = min(len(keyword_docs), len(vector_docs))
            for i in range(min_len):
                combine_docs.append(keyword_docs[i])
                combine_docs.append(vector_docs[i])
            combine_docs.extend(keyword_docs[min_len:])
            combine_docs.extend(vector_docs[min_len:])
            return combine_docs
        else:
            raise ValueError(f'Expected combine_strategy to be one of '
                             f'(keyword_front, vector_front, mix),'
                             f'instead found {self.combine_strategy}')

    @property
    def _chain_type(self) -> str:
        """Return the chain type."""
        return 'multi_retrieval_qa'
