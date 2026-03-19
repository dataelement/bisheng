from typing import Sequence, Any, Dict

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
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
        knowledge_metadata_fields = {one.field_name for one in KNOWLEDGE_RAG_METADATA_SCHEMA}
        if all_chunk_info:
            logger.info("get file chunk from preview cache")
            documents = []
            for key, val in all_chunk_info.items():
                one_metadata = val["metadata"]
                one_metadata.update(self.file_metadata)
                for k in one_metadata:
                    if k not in knowledge_metadata_fields:
                        del one_metadata[k]
                doc = Document(
                    page_content=KnowledgeUtils.aggregate_chunk_metadata(val["text"], one_metadata),
                    metadata=one_metadata,
                )
                documents.append(doc)
        else:
            # aggregate chunk
            for doc in documents:
                for k in doc.metadata:
                    if k not in knowledge_metadata_fields:
                        del doc.metadata[k]
                doc.page_content = KnowledgeUtils.aggregate_chunk_metadata(doc.page_content, doc.metadata)

        return documents
