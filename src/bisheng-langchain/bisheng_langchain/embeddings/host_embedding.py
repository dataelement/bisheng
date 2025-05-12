from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests
from langchain.embeddings.base import Embeddings
from langchain.utils import get_from_dict_or_env
from pydantic import model_validator, BaseModel, Field
from tenacity import (before_sleep_log, retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

logger = logging.getLogger(__name__)


def _create_retry_decorator(embeddings: HostEmbeddings) -> Callable[[Any], Any]:
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

    client: Optional[Any] = None  #: :meta private:
    """Model name to use."""
    model: str = 'embedding-host'
    host_base_url: str = None

    deployment: Optional[str] = 'default'

    embedding_ctx_length: Optional[int] = 6144
    """The maximum number of tokens to embed at once."""
    """Maximum number of texts to embed in each batch"""
    max_retries: Optional[int] = 6
    """Maximum number of retries to make when generating."""
    request_timeout: Optional[Union[float, Tuple[float, float]]] = 200
    """Timeout in seconds for the OpenAPI request."""

    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""

    verbose: Optional[bool] = False

    url_ep: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values['host_base_url'] = get_from_dict_or_env(values, 'host_base_url', 'HostBaseUrl')
        model = values['model']
        try:
            url = values['host_base_url']
            values['url_ep'] = f'{url}/{model}/infer'
        except Exception:
            raise Exception(f'Failed to set url ep failed for model {model}')

        try:
            values['client'] = requests.post
        except AttributeError:
            raise ValueError('Try upgrading it with `pip install --upgrade requests`.')
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

        max_text_to_split = 200
        outp = None

        start_index = 0
        len_text = len(texts)
        while start_index < len_text:
            inp_local = {
                'texts': texts[start_index:min(start_index + max_text_to_split, len_text)],
                'model': self.model,
                'type': emb_type
            }
            try:
                outp_single = self.client(url=self.url_ep,
                                          json=inp_local,
                                          timeout=self.request_timeout).json()
                if outp is None:
                    outp = outp_single
                else:
                    outp['embeddings'] += outp_single['embeddings']
            except requests.exceptions.Timeout:
                raise Exception(f'timeout in host embedding infer, url=[{self.url_ep}]')
            except Exception as e:
                raise Exception(f'exception in host embedding infer: [{e}]')

            if outp_single['status_code'] != 200:
                raise ValueError(f"API returned an error: {outp['status_message']}")
            start_index += max_text_to_split
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


class JINAEmbedding(HostEmbeddings):
    model: str = 'jina'
    embedding_ctx_length: int = 512


class CustomHostEmbedding(HostEmbeddings):
    model: str = Field('custom-embedding', alias='model')
    embedding_ctx_length: int = 512

    @model_validator(mode='before')
    @classmethod
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values['host_base_url'] = get_from_dict_or_env(values, 'host_base_url', 'HostBaseUrl')
        try:
            values['url_ep'] = values['host_base_url']
        except Exception:
            raise Exception('Failed to set url ep for custom host embedding')

        try:
            values['client'] = requests.post
        except AttributeError:
            raise ValueError('Try upgrading it with `pip install --upgrade requests`.')
        return values
