import json
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.common.constants.knowledge import KNOWLEDGE_MAX_CHUNK_CHARS
from bisheng.common.errcode.knowledge import KnowledgeFileChunkMaxError


class DirectChunkTransformer(BaseDocumentTransformer):
    def __init__(self, max_chunk_limit: int = KNOWLEDGE_MAX_CHUNK_CHARS) -> None:
        self.max_chunk_limit = max_chunk_limit

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        for index, one in enumerate(documents):
            one.metadata["chunk_index"] = index
            if "bbox" not in one.metadata:
                one.metadata["bbox"] = json.dumps({"chunk_bboxes": one.metadata.get("chunk_bboxes", "")})
            if "page" not in one.metadata:
                one.metadata["page"] = one.metadata.get("chunk_bboxes", [{}])[0].get("page", index + 1)
            if len(one.page_content) > self.max_chunk_limit:
                raise KnowledgeFileChunkMaxError()
        return documents
