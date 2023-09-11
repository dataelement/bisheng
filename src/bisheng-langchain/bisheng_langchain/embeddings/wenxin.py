from __future__ import annotations

import logging
# import warnings
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# import numpy as np
from langchain.embeddings.base import Embeddings
from langchain.utils import get_from_dict_or_env
from pydantic import BaseModel, Extra, Field, root_validator
from requests.exceptions import HTTPError
from tenacity import (before_sleep_log, retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

logger = logging.getLogger(__name__)


def _create_retry_decorator(
        embeddings: WenxinEmbeddings) -> Callable[[Any], Any]:
    min_seconds = 4
    max_seconds = 10
    # Wait 2^x * 1 second between each retry starting with
    # 4 seconds, then up to 10 seconds, then 10 seconds afterwards
    return retry(
        reraise=True,
        stop=stop_after_attempt(embeddings.max_retries),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=(retry_if_exception_type(HTTPError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def embed_with_retry(embeddings: WenxinEmbeddings, **kwargs: Any) -> Any:
    """Use tenacity to retry the embedding call."""
    retry_decorator = _create_retry_decorator(embeddings)

    @retry_decorator
    def _embed_with_retry(**kwargs: Any) -> Any:
        return embeddings.embed(**kwargs)

    return _embed_with_retry(**kwargs)


class WenxinEmbeddings(BaseModel, Embeddings):
    """Wenxin embedding models.

    To use, the environment variable ``WENXIN_API_KEY`` and ``WENXIN_SECRET_KEY``
    set with your API key or pass it as a named parameter to the constructor.

    Example:
        .. code-block:: python
            from bisheng_langchain.embeddings import WenxinEmbeddings
            wenxin_embeddings = WenxinEmbeddings(
               wenxin_api_key="my-api-key",
               wenxin_secret_key='xxx')

    """

    client: Optional[Any]  #: :meta private:
    model: str = 'embedding-v1'

    deployment: Optional[str] = 'default'
    wenxin_api_key: Optional[str] = None
    wenxin_secret_key: Optional[str] = None

    embedding_ctx_length: Optional[int] = 6144
    """The maximum number of tokens to embed at once."""
    """Maximum number of texts to embed in each batch"""
    max_retries: Optional[int] = 6
    """Maximum number of retries to make when generating."""
    request_timeout: Optional[Union[float, Tuple[float, float]]] = None
    """Timeout in seconds for the OpenAPI request."""

    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values['wenxin_api_key'] = get_from_dict_or_env(
            values, 'wenxin_api_key', 'WENXIN_API_KEY')
        values['wenxin_secret_key'] = get_from_dict_or_env(
            values,
            'wenxin_secret_key',
            'WENXIN_SECRET_KEY',
        )

        api_key = values['wenxin_api_key']
        sec_key = values['wenxin_secret_key']
        try:
            from .interface import WenxinEmbeddingClient
            values['client'] = WenxinEmbeddingClient(api_key=api_key,
                                                     sec_key=sec_key)
        except AttributeError:
            raise ValueError(
                'Try upgrading it with `pip install --upgrade requests`.')
        return values

    @property
    def _invocation_params(self) -> Dict:
        wenxin_args = {
            'model': self.model,
            'request_timeout': self.request_timeout,
            **self.model_kwargs,
        }

        return wenxin_args

    def embed(self, texts: List[str]) -> List[List[float]]:
        inp = {'input': texts, 'model': self.model}
        outp = self.client.create(**inp)
        if outp['status_code'] != 200:
            raise ValueError(
                f"Wenxin API returned an error: {outp['status_message']}")
        return [e['embedding'] for e in outp['data']]

    def embed_documents(self,
                        texts: List[str],
                        chunk_size: Optional[int] = 0) -> List[List[float]]:
        embeddings = embed_with_retry(self, texts=texts)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """Call out to OpenAI's embedding endpoint for embedding query text.

        Args:
            text: The text to embed.

        Returns:
            Embedding for the text.
        """

        embeddings = embed_with_retry(self, texts=[text])
        return embeddings[0]
