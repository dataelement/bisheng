from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests
from langchain.embeddings.base import Embeddings
from langchain.utils import get_from_dict_or_env
from pydantic import BaseModel, Extra, Field, root_validator
from tenacity import (before_sleep_log, retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

logger = logging.getLogger(__name__)


def _create_retry_decorator(
        embeddings: HostEmbeddings) -> Callable[[Any], Any]:
    min_seconds = 4
    max_seconds = 10
    # Wait 2^x * 1 second between each retry starting with
    # 4 seconds, then up to 10 seconds, then 10 seconds afterwards
    return retry(
        reraise=True,
        stop=stop_after_attempt(embeddings.max_retries),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=(retry_if_exception_type(Exception)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def embed_with_retry(embeddings: HostEmbeddings, **kwargs: Any) -> Any:
    """Use tenacity to retry the embedding call."""
    retry_decorator = _create_retry_decorator(embeddings)

    @retry_decorator
    def _embed_with_retry(**kwargs: Any) -> Any:
        return embeddings.embed(**kwargs)

    return _embed_with_retry(**kwargs)


class HostEmbeddings(BaseModel, Embeddings):
    """host embedding models.
    """

    client: Optional[Any]  #: :meta private:
    """Model name to use."""
    model: str = 'embedding-host'
    host_base_url: str = None

    deployment: Optional[str] = 'default'

    embedding_ctx_length: Optional[int] = 6144
    """The maximum number of tokens to embed at once."""
    """Maximum number of texts to embed in each batch"""
    max_retries: Optional[int] = 6
    """Maximum number of retries to make when generating."""
    request_timeout: Optional[Union[float, Tuple[float, float]]] = None
    """Timeout in seconds for the OpenAPI request."""

    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""

    verbose: Optional[bool] = False

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values['host_base_url'] = get_from_dict_or_env(values, 'host_base_url',
                                                       'HostBaseUrl')

        try:
            values['client'] = requests.post
        except AttributeError:
            raise ValueError(
                'Try upgrading it with `pip install --upgrade requests`.')
        return values

    @property
    def _invocation_params(self) -> Dict:
        api_args = {
            'model': self.model,
            'request_timeout': self.request_timeout,
            **self.model_kwargs,
        }
        return api_args

    def embed(self, texts: List[str], **kwargs) -> List[List[float]]:
        emb_type = kwargs.get('type', 'raw')
        inp = {'texts': texts, 'model': self.model, 'type': emb_type}
        if self.verbose:
            print('payload', inp)

        url = f'{self.host_base_url}/{self.model}/infer'
        outp = self.client(url=url, json=inp).json()
        if outp['status_code'] != 200:
            raise ValueError(
                f"API returned an error: {outp['status_message']}")
        return outp['embeddings']

    def embed_documents(self,
                        texts: List[str],
                        chunk_size: Optional[int] = 0) -> List[List[float]]:
        if not texts:
            return []
        """Embed search docs."""
        texts = [text for text in texts if text]
        embeddings = embed_with_retry(self, texts=texts, type='doc')
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        embeddings = embed_with_retry(self, texts=[text], type='query')
        return embeddings[0]


class ME5Embedding(HostEmbeddings):
    model: str = 'multi-e5'
    embedding_ctx_length: int = 512


class BGEZhEmbedding(HostEmbeddings):
    model: str = 'bge-zh'
    embedding_ctx_length: int = 512


class GTEEmbedding(HostEmbeddings):
    model: str = 'gte'
    embedding_ctx_length: int = 512
