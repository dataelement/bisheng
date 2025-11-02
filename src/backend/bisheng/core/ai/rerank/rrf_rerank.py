from typing import Sequence, Optional, List, Any, Dict

from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from pydantic import model_validator

from bisheng.core.ai.base import BaseRerank


class RRFRerank(BaseRerank):
    """
    Perform weighted Reciprocal Rank Fusion on multiple rank lists.
    You can find more details about RRF here:
    https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf

    It uses a rank fusion.

    Args:
        retrievers: A list of retrievers to ensemble.
        weights: A list of weights corresponding to the retrievers. Defaults to equal
            weighting for all retrievers.
        c: A constant added to the rank, controlling the balance between the importance
            of high-ranked items and the consideration given to lower-ranked items.
            Default is 60.
    """
    retrievers: List[Any]
    weights: List[float]
    c: int = 60
    remove_zero_score: bool = False

    @model_validator(mode='before')
    @classmethod
    def set_weights(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not values.get("weights"):
            n_retrievers = len(values["retrievers"])
            values["weights"] = [1 / n_retrievers] * n_retrievers
        return values

    def compress_documents(
            self,
            documents: List[List[Document]],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """
        Args:
            documents: A list of document lists for each retriever search list[document].
            query: The query to use for computing weighted reciprocal rank.
            callbacks: Optional callbacks to use for computing weighted reciprocal rank.

        Returns:
            list: The final aggregated list of items sorted by their weighted RRF
                    scores in descending order. and remove duplicates document.
                """
        if len(documents) != len(self.weights):
            raise ValueError("Number of rank lists must be equal to the number of weights.")

        # Create a union of all unique documents in the input doc_lists
        all_documents = set()
        for doc_list in documents:
            for doc in doc_list:
                all_documents.add(doc.page_content)

        # Initialize the RRF score dictionary for each document
        rrf_score_dic = {doc: 0.0 for doc in all_documents}

        # Calculate RRF scores for each document
        for doc_list, weight in zip(documents, self.weights):
            for rank, doc in enumerate(doc_list, start=1):
                rrf_score = weight * (1 / (rank + self.c))
                rrf_score_dic[doc.page_content] += rrf_score

        # Sort documents by their RRF scores in descending order
        sorted_documents = sorted(rrf_score_dic.keys(), key=lambda x: rrf_score_dic[x], reverse=True)

        # Map the sorted page_content back to the original document objects
        page_content_to_doc_map = {doc.page_content: doc for doc_list in documents for doc in doc_list}
        if self.remove_zero_score:
            sorted_docs = [page_content_to_doc_map[page_content] for page_content in sorted_documents if
                           rrf_score_dic[page_content] > 0]
        else:
            sorted_docs = [page_content_to_doc_map[page_content] for page_content in sorted_documents]
        return sorted_docs
