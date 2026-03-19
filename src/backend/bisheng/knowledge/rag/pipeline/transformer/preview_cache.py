from typing import Sequence, Any, Dict

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


class PreviewCacheTransformer(BaseDocumentTransformer):
    def __init__(self, preview_cache_key: str, file_metadata: Dict) -> None:
        super().__init__()
        self.preview_cache_key = preview_cache_key
        self.file_metadata = file_metadata

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        all_chunk_info = KnowledgeUtils.get_preview_cache(self.preview_cache_key)
        if all_chunk_info:
            logger.info("get file chunk from preview cache")
            documents = []
            for key, val in all_chunk_info.items():
                documents.append(
                    Document(page_content=val["text"], metadata=Metadata(**val["metadata"], **self.file_metadata)))
        return documents
