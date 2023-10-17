from typing import Any, Dict, List

from langchain.callbacks.manager import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)

from langchain.schema import BaseRetriever, Document


class MixEsVectorRetriever(BaseRetriever):
    """
    This class ensemble the results of es retriever and vector retriever.

    Args:
        retrievers: A list of retrievers to ensemble.
        weights: A list of weights corresponding to the retrievers. Defaults to equal
            weighting for all retrievers.
        c: A constant added to the rank, controlling the balance between the importance
            of high-ranked items and the consideration given to lower-ranked items.
            Default is 60.
    """

    vector_retriever: BaseRetriever
    keyword_retriever: BaseRetriever
    combine_strategy: str = 'keyword_front'  # "keyword_front, vector_front, mix"

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        """
        Get the relevant documents for a given query.

        Args:
            query: The query to search for.

        Returns:
            A list of documents.
        """

        # Get fused result of the retrievers.
        vector_docs = self.vector_retriever.get_relevant_documents(
            query, callbacks=run_manager.get_child())
        keyword_docs = self.keyword_retriever.get_relevant_documents(
            query, callbacks=run_manager.get_child())

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

        return combine_docs

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> List[Document]:
        """
        Asynchronously get the relevant documents for a given query.

        Args:
            query: The query to search for.

        Returns:
            A list of reranked documents.
        """

        # Get fused result of the retrievers.
        vector_docs = await self.vector_retriever.aget_relevant_documents(
            query, callbacks=run_manager.get_child())
        keyword_docs = await self.keyword_retriever.aget_relevant_documents(
            query, callbacks=run_manager.get_child())
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

        return combine_docs
