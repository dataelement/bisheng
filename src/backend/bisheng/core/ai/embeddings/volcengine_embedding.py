import logging
from typing import List, Optional

import requests
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class VolcengineEmbeddings(OpenAIEmbeddings):
    """
    Volcengine embedding wrapper to support standard endpoints and the 
    new multimodal format for `doubao-embedding-vision-251215`.
    """

    def _get_multimodal_url(self) -> str:
        base = self.openai_api_base or "https://ark.cn-beijing.volces.com/api/v3"
        base = base.rstrip('/')
        if base.endswith('/v3'):
            return f"{base}/embeddings/multimodal"
        elif 'ark.cn-beijing.volces.com' in base:
            return "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
        return f"{base}/embeddings/multimodal"

    def embed_documents(self, texts: List[str], chunk_size: Optional[int] = 0, **kwargs) -> List[List[float]]:
        chunk_size = chunk_size or self.chunk_size
        return self._embed_multimodal(texts, chunk_size=chunk_size)

    def embed_query(self, text: str, **kwargs) -> list[float]:
        return self._embed_multimodal([text])[0]

    async def aembed_documents(self, texts: List[str], chunk_size: Optional[int] = 0, **kwargs) -> List[List[float]]:
        import asyncio
        return await asyncio.to_thread(self.embed_documents, texts, chunk_size=chunk_size, **kwargs)

    async def aembed_query(self, text: str, **kwargs) -> List[float]:
        import asyncio
        return await asyncio.to_thread(self.embed_query, text, **kwargs)

    def _embed_multimodal(self, texts: List[str], chunk_size: Optional[int] = 0) -> List[List[float]]:
        url = self._get_multimodal_url()
        api_key = self.openai_api_key.get_secret_value() if hasattr(self.openai_api_key,
                                                                    'get_secret_value') else self.openai_api_key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        all_embeddings = []
        for text in texts:
            payload = {
                "model": self.model,
                "input": [
                    {
                        "type": "text",
                        "text": text
                    }
                ],
                "encoding_format": "float"
            }
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.request_timeout or 60)
                response.raise_for_status()
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    embedding = data["data"][0].get("embedding") if isinstance(data["data"], list) else (
                        data["data"].get("embedding"))
                    all_embeddings.append(embedding)
                else:
                    logger.error(f"Volcengine multimodal embedding error: {data}")
                    raise Exception(f"Invalid response from Volcengine multimodal API: {data}")
            except Exception as e:
                logger.error(f"Volcengine multimodal embedding request failed: {str(e)}")
                raise e
        return all_embeddings
