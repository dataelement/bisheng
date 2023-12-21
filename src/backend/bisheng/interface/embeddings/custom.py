from typing import List

from bisheng.settings import settings
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings


class OpenAIProxyEmbedding(Embeddings):

    def __init__(self) -> None:
        param = settings.get_knowledge().get('embeddings').get('text-embedding-ada-002')
        self.embd = OpenAIEmbeddings(**param)
        super().__init__()

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        """Embed search docs."""
        return self.embd.embed_documents(texts)

    @classmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        return self.embed_query(text)


CUSTOM_EMBEDDING = {
    'OpenAIProxyEmbedding': OpenAIProxyEmbedding,
}
