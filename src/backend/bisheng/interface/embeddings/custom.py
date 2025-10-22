from typing import List, Optional

from langchain.embeddings.base import Embeddings
from langchain_community.embeddings.dashscope import BATCH_SIZE
from pydantic import Field

from bisheng.llm.domain.llm.embedding import BishengEmbedding

BATCH_SIZE["text-embedding-v4"] = 10  # 设置DashScope的批处理大小为1


class OpenAIProxyEmbedding(Embeddings):
    embeddings: Optional[Embeddings] = Field(default=None)

    def __init__(self) -> None:
        super().__init__()
        from bisheng.llm.domain.services import LLMService
        self.embeddings = LLMService.get_knowledge_default_embedding()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed search docs."""
        if not texts:
            return []

        return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""

        return self.embeddings.embed_query(text)


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
    'BishengEmbedding': BishengEmbedding,
}
