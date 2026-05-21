"""SimHash transformer — compute and persist a 64-bit content SimHash on the knowledge file.

Designed to mirror FileEncodingTransformer:
- Synchronous transform_documents (called by the parse pipeline)
- Writes to self.knowledge_file (in-memory); commit happens upstream via KnowledgeFileDao.update
- Idempotent: skips if simhash is already populated
- Returns documents unchanged
"""
from __future__ import annotations

from typing import Any, List, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.common.utils.simhash_utils import compute_simhash_64_hex
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


class SimHashTransformer(BaseDocumentTransformer):
    """Compute 64-bit SimHash hex and store on `knowledge_file.simhash`."""

    def __init__(self, knowledge_file: KnowledgeFile) -> None:
        self.knowledge_file = knowledge_file

    def transform_documents(
        self, documents: Sequence[Document], **kwargs: Any,
    ) -> List[Document]:
        # Idempotent: skip if already computed (re-parse safety)
        if self.knowledge_file.simhash:
            return list(documents)

        # Concatenate all document text; empty -> helper returns zero-hash
        text = "\n".join(d.page_content or "" for d in documents)
        self.knowledge_file.simhash = compute_simhash_64_hex(text)

        # Return unchanged (invariant: transformer doesn't mutate documents)
        return list(documents)
