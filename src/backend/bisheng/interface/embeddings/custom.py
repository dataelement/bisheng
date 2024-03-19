from typing import List

from bisheng.utils.embedding import decide_embeddings
from langchain.embeddings.base import Embeddings


class OpenAIProxyEmbedding(Embeddings):

    def __init__(self) -> None:

        super().__init__()

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs."""
        if not texts:
            return []

        embedding = decide_embeddings('text-embedding-ada-002')
        return embedding.embed_documents(texts)

    @classmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""

        embedding = decide_embeddings('text-embedding-ada-002')
        return embedding.embed_query(text)


class FakeEmbedding(Embeddings):
    """为了保证milvus等，在模型下线还能继续用"""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """embedding"""
        return []

    def embed_query(self, text: str) -> List[float]:
        """embedding"""
        return []


CUSTOM_EMBEDDING = {
    'OpenAIProxyEmbedding': OpenAIProxyEmbedding,
}
