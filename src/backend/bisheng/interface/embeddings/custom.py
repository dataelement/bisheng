import json
from typing import List

from bisheng.utils.logger import logger
from bisheng_langchain.utils.requests import TextRequestsWrapper
from langchain.embeddings.base import Embeddings


class OpenAIProxyEmbedding(Embeddings):
    request = TextRequestsWrapper()

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        """Embed search docs."""
        texts = [text for text in texts if text]
        data = {'texts': texts}
        resp = self.request.post(url='http://43.133.35.137:8080/chunks_embed', data=data)
        logger.info(f'texts={texts}')
        return json.loads(resp).get('data')

    @classmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        data = {'query': [text]}
        resp = self.request.post(url='http://43.133.35.137:8080/query_embed', data=data)
        logger.info(f'texts={data}')
        return json.loads(resp).get('data')[0]


CUSTOM_EMBEDDING = {
    'OpenAIProxyEmbedding': OpenAIProxyEmbedding,
}
