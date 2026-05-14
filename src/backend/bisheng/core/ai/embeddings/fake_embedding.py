from typing import List

from langchain_core.embeddings import Embeddings


class FakeEmbeddings(Embeddings):
    """To ensure amilvusWait, you can continue to use it when the model is offline"""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        return []

    def embed_query(self, text: str) -> List[float]:
        """embedding"""
        return []
