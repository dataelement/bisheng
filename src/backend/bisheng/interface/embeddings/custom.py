import json
from typing import Dict, List, Type, Union

import requests
from bisheng.utils.logger import logger
from langchain.embeddings.base import Embeddings


class OpenAIProxyEmbedding(Embeddings):

    @classmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        """Embed search docs."""
        texts = [text for text in texts if text]
        data = {'texts': texts}
        resp = requests.post('http://43.133.35.137:8080/chunks_embed', json=data)
        logger.info(f'texts={texts}')
        return json.loads(resp.text).get('data')

    @classmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed query text."""
        data = {'query': [text]}
        resp = requests.post('http://43.133.35.137:8080/query_embed', json=data)
        logger.info(f'texts={data}')
        return json.loads(resp.text).get('data')[0]

CUSTOM_EMBEDDING = {
    'OpenAIProxyEmbedding': OpenAIProxyEmbedding,
}
