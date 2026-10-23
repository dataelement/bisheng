"""Ingest caller-provided text chunks into a document knowledge base.

The open API ``POST /api/v2/filelib/chunks_string`` receives text that the
caller has already prepared. It skips file parsing, but its chunks must carry
the same metadata as chunks of an uploaded file: retrieval filters on
``document_id`` and the Milvus collection of a document knowledge base uses
``KNOWLEDGE_RAG_METADATA_SCHEMA`` (no dynamic fields). This pipeline therefore
reuses ``KnowledgeFilePipeline.file_metadata`` and its abstract step, and only
replaces the loader and the splitter.
"""

import copy
import json
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_text_splitters import CharacterTextSplitter

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode.knowledge import KnowledgeFileEmptyError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline
from bisheng.knowledge.rag.pipeline.base import NormalPipeline
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import PipelineConfig, PipelineResult

# Fixed split rule of this endpoint (unchanged from the earlier implementation).
TEXT_CHUNK_SEPARATOR = "\n\n"
TEXT_CHUNK_SIZE = 1000
TEXT_CHUNK_OVERLAP = 100

# Chunk metadata keys that a document knowledge base stores. Milvus rejects other
# keys (the collection is not dynamic), so the pipeline emits exactly these.
KNOWLEDGE_CHUNK_METADATA_KEYS = frozenset(schema.field_name for schema in KNOWLEDGE_RAG_METADATA_SCHEMA)

# Same value that SplitterTransformer writes for a text file without positions.
_EMPTY_BBOX = json.dumps({"chunk_bboxes": ""})


def _chunk_page(value: Any) -> int:
    """Return the caller page as an int; a missing or invalid page becomes 0 (text upload default)."""
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _chunk_bbox(value: Any) -> str:
    """Return the caller bbox as the string that the bbox text field stores."""
    if value is None or value == "":
        return _EMPTY_BBOX
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class _PreparedChunksLoader(BaseBishengLoader):
    """Return chunks that the pipeline built in memory; no file is read."""

    def __init__(self, chunks: list[Document], file_metadata: dict):
        super().__init__(file_path="", file_metadata=file_metadata, file_extension="txt", tmp_dir="")
        self._chunks = chunks

    def load(self) -> list[Document]:
        return self._chunks


class _SchemaFieldsTransformer(BaseDocumentTransformer):
    """Keep only the metadata keys of KNOWLEDGE_RAG_METADATA_SCHEMA (runs last)."""

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        for document in documents:
            document.metadata = {k: v for k, v in document.metadata.items() if k in KNOWLEDGE_CHUNK_METADATA_KEYS}
        return documents


class KnowledgeChunksPipeline(KnowledgeFilePipeline):
    """Write caller-provided text chunks with the metadata of the file upload pipeline.

    Each caller document is split with the fixed rule of this endpoint. Every
    resulting chunk gets ``file_metadata`` (document_id, document_name,
    knowledge_id, upload_time, update_time, uploader, updater, user_metadata,
    abstract), a global ``chunk_index``, and the caller ``page`` and ``bbox``.
    Other caller metadata keys are not stored: the document knowledge base
    schema has no field for free-form chunk metadata.
    """

    def __init__(self, invoke_user_id: int, db_file: KnowledgeFile, documents: list[Document], **kwargs):
        super().__init__(invoke_user_id=invoke_user_id, db_file=db_file, **kwargs)
        self.source_documents = documents

    def build_chunks(self) -> list[Document]:
        splitter = CharacterTextSplitter(
            separator=TEXT_CHUNK_SEPARATOR,
            chunk_size=TEXT_CHUNK_SIZE,
            chunk_overlap=TEXT_CHUNK_OVERLAP,
        )
        chunks: list[Document] = []
        for document in self.source_documents:
            caller_metadata = document.metadata or {}
            page = _chunk_page(caller_metadata.get("page"))
            bbox = _chunk_bbox(caller_metadata.get("bbox"))
            for text in splitter.split_text(document.page_content or ""):
                metadata = copy.deepcopy(self.file_metadata)
                metadata.update(chunk_index=len(chunks), page=page, bbox=bbox)
                chunks.append(Document(page_content=text, metadata=metadata))
        return chunks

    def _init_chunk_transformers(self) -> list[BaseDocumentTransformer]:
        transformers = self._init_abstract_transformers()
        transformers.append(_SchemaFieldsTransformer())
        return transformers

    def run(self, config: PipelineConfig = None) -> PipelineResult:
        chunks = self.build_chunks()
        if not chunks:
            # Same rule as the upload pipeline: no text means a failed ingestion.
            raise KnowledgeFileEmptyError()
        self.loader = _PreparedChunksLoader(chunks, self.file_metadata)
        self.transformers = self._init_chunk_transformers()
        pipeline = NormalPipeline(loader=self.loader, transformers=self.transformers, vector_store=self.vector_store)
        return pipeline.run(config)
