from typing import List

from bisheng.settings import settings
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings


class OpenAIProxyEmbedding(Embeddings):

    def __init__(self) -> None:

        super().__init__()

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        """Embed search docs."""
        params = settings.get_knowledge().get('embeddings').get('text-embedding-ada-002')
        embedding = OpenAIEmbeddings(**params)
        return embedding.embed_documents(texts)

    @classmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        params = settings.get_knowledge().get('embeddings').get('text-embedding-ada-002')
        embedding = OpenAIEmbeddings(**params)
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
