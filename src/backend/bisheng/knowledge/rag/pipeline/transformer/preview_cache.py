from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode.knowledge import KnowledgePreviewError
from bisheng.knowledge.domain.repositories.upload_preview_repository import FROZEN_PREFIX
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


class PreviewCacheTransformer(BaseDocumentTransformer):
    def __init__(self, preview_cache_key: str, file_metadata: dict) -> None:
        super().__init__()
        self.preview_cache_key = preview_cache_key
        self.file_metadata = file_metadata

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        all_chunk_info = KnowledgeUtils.get_preview_cache(self.preview_cache_key) if self.preview_cache_key else None
        if self.preview_cache_key and self.preview_cache_key.startswith(FROZEN_PREFIX) and not all_chunk_info:
            raise KnowledgePreviewError()
        required = bool(self.preview_cache_key and self.preview_cache_key.startswith(FROZEN_PREFIX))
        if required and any(
            not str(key).isdigit()
            or not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or not isinstance(value.get("metadata"), dict)
            or value["metadata"].get("chunk_index") != int(key)
            for key, value in all_chunk_info.items()
        ):
            raise KnowledgePreviewError()
        knowledge_metadata_fields = {one.field_name for one in KNOWLEDGE_RAG_METADATA_SCHEMA}
        if all_chunk_info:
            logger.info("get file chunk from preview cache")
            documents = []
            ordered = (
                sorted(all_chunk_info.items(), key=lambda item: int(item[0])) if required else all_chunk_info.items()
            )
            for _, val in ordered:
                one_metadata = val["metadata"]
                one_metadata.update(self.file_metadata)
                for k in one_metadata.keys() - knowledge_metadata_fields:
                    del one_metadata[k]
                doc = Document(
                    page_content=KnowledgeUtils.aggregate_chunk_metadata(val["text"], one_metadata),
                    metadata=one_metadata,
                )
                documents.append(doc)
        else:
            # aggregate chunk
            for doc in documents:
                for k in doc.metadata.keys() - knowledge_metadata_fields:
                    del doc.metadata[k]
                doc.metadata.update(self.file_metadata)
                doc.page_content = KnowledgeUtils.aggregate_chunk_metadata(doc.page_content, doc.metadata)

        return documents
