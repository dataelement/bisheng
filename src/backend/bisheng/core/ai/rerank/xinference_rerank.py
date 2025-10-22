from typing import Sequence, Optional

from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from pydantic import Field, model_validator
from typing_extensions import Self
from xinference.client import Client

from ..base import BaseRerank


class XinferenceRerank(BaseRerank):
    """Document compressor that uses `Xinference Rerank API`."""
    base_url: str = Field(..., description="xinference server base url， example: http://localhost:9997")
    api_key: Optional[str] = Field(default="", description="api key for xinference server")
    model_uid: str = Field(..., description="model uid for xinference rerank model")

    client: Optional[Client] = Field(default=None, description="xinference client instance")

    @model_validator(mode="after")
    def validate_client(self) -> Self:
        """Validate that client exists in environment."""
        if self.base_url.endswith(("/v1", "/v1/")):
            self.base_url = self.base_url.rsplit("/v1", 1)[0]
        if not self.client:
            self.client = Client(base_url=self.base_url, api_key=self.api_key)
        return self

    def compress_documents(
            self,
            documents: Sequence[Document],
            query: str,
            callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        if len(documents) == 0:  # to avoid empty api call
            return []
        docs = [
            doc.page_content if isinstance(doc, Document) else doc for doc in documents
        ]
        model = self.client.get_model(self.model_uid)  # ensure model exists
        result = model.rerank(docs, query)

        results = result.get("results", [])
        return self.sort_rerank_result(documents, results)
