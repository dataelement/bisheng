import json
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document


class DirectChunkTransformer(BaseDocumentTransformer):
    def __init__(self, max_chunk_limit: int = 10000) -> None:
        self.max_chunk_limit = max_chunk_limit

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        limited_documents = []
        for one in documents:
            text = one.page_content or ""
            segments = [
                text[start:start + self.max_chunk_limit]
                for start in range(0, len(text), self.max_chunk_limit)
            ] or [""]
            limited_documents.extend(
                Document(page_content=segment, metadata=one.metadata.copy())
                for segment in segments
            )

        for index, one in enumerate(limited_documents):
            one.metadata["chunk_index"] = index
            if "bbox" not in one.metadata:
                one.metadata["bbox"] = json.dumps({"chunk_bboxes": one.metadata.get("chunk_bboxes", "")})
            if "page" not in one.metadata:
                chunk_bboxes = one.metadata.get("chunk_bboxes") or [{}]
                one.metadata["page"] = chunk_bboxes[0].get("page", index + 1)
        return limited_documents
