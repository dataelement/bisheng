from typing import Optional, Sequence

from httpx import Client, AsyncClient
from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from pydantic import Field, model_validator
from typing_extensions import Self

from ..base import BaseRerank


class CommonRerank(BaseRerank):
    """Document compressor that support `/v1/rerank` router and results simial vllm."""

    base_url: str = Field(..., description="server base url， example: http://localhost:9997")
    rerank_endpoint: str = Field(default="/v1/rerank", description="rerank endpoint for base url")

    api_key: Optional[str] = Field(default="", description="api key for rerank server")
    model: str = Field(..., description="model name for rerank model")

    client: Optional[Client] = Field(default=None, description="client instance")
    async_client: Optional[AsyncClient] = Field(default=None, description="async client instance")

    @model_validator(mode="after")
    def validate_client(self) -> Self:
        """Validate that client exists in environment."""
        self.base_url = self.base_url.rstrip("/") if self.base_url else self.base_url
        if not self.client:
            self.client = Client(base_url=self.base_url)
        if not self.async_client:
            self.async_client = AsyncClient(base_url=self.base_url)
        return self

    def get_default_headers(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_default_params(self):
        params = {}
        if self.model:
            params["model"] = self.model
        return params

    def get_req_data(
            self,
            documents: Sequence[Document],
            query: str
    ) -> dict:
        if len(documents) == 0:  # to avoid empty api call
            return {}
        docs = [
            doc.page_content if isinstance(doc, Document) else doc for doc in documents
        ]

        req_data = self.get_default_params()
        req_data["query"] = query
        req_data["documents"] = docs
        return req_data

    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """Rerank retrieved documents given the query context.

        Args:
            documents: The retrieved documents.
            query: The query context.
            callbacks: Optional callbacks to run during compression.

        Returns:
            The compressed documents.
        """
        req_data = self.get_req_data(documents, query)
        if not req_data:
            return []

        resp = self.client.post(self.rerank_endpoint, json=req_data, headers=self.get_default_headers())
        if resp.status_code != 200:
            raise ValueError(f"Rerank request failed with status code {resp.status_code}: {resp.text}")
        results = resp.json().get("results", [])
        return self.sort_rerank_result(documents, results)

    async def acompress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        """Async rerank retrieved documents given the query context.

        Args:
            documents: The retrieved documents.
            query: The query context.
            callbacks: Optional callbacks to run during compression.

        Returns:
            The compressed documents.
        """
        req_data = self.get_req_data(documents, query)
        if not req_data:
            return []
        resp = await self.async_client.post(self.rerank_endpoint, json=req_data, headers=self.get_default_headers())
        if resp.status_code != 200:
            raise ValueError(f"Rerank request failed with status code {resp.status_code}: {resp.text}")
        results = resp.json().get("results", [])
        return self.sort_rerank_result(documents, results)
