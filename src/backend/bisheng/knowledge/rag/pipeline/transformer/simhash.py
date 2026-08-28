"""SimHash transformer — compute and persist a 64-bit content SimHash on the knowledge file.

Designed to mirror FileEncodingTransformer:
- Synchronous transform_documents (called by the parse pipeline)
- Writes to self.knowledge_file (in-memory); commit happens upstream via KnowledgeFileDao.update
- Idempotent: skips if simhash is already populated
- Returns documents unchanged
"""
from __future__ import annotations

import threading
from typing import Any, List, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

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
            logger.info(
                f"[simhash.diag] skip_idempotent file_id={self.knowledge_file.id} "
                f"knowledge_id={self.knowledge_file.knowledge_id} "
                f"object_name={getattr(self.knowledge_file, 'object_name', None)} "
                f"existing_simhash={self.knowledge_file.simhash} "
                f"thread={threading.current_thread().name} kf_obj_id={id(self.knowledge_file)}"
            )
            return list(documents)

        # Concatenate all document text; empty -> helper returns zero-hash
        text = "\n".join(d.page_content or "" for d in documents)
        simhash_value = compute_simhash_64_hex(text)
        self.knowledge_file.simhash = simhash_value

        # [simhash.diag] Temporary diagnostic for the cross-file simhash-collision
        # incident (files with genuinely different content ending up with an
        # identical simhash in production, not reproducible on staging). Logs
        # everything needed to tell, from one log line per file, whether two
        # colliding file_ids actually fed the same text into this hash (a real
        # upstream content mixup) or whether they hashed different text that
        # coincidentally/buggily produced the same value. Remove once root-caused.
        logger.info(
            f"[simhash.diag] computed file_id={self.knowledge_file.id} "
            f"knowledge_id={self.knowledge_file.knowledge_id} "
            f"object_name={getattr(self.knowledge_file, 'object_name', None)} "
            f"doc_count={len(documents)} text_len={len(text)} "
            f"text_head={text[:120]!r} text_tail={text[-120:]!r} "
            f"simhash={simhash_value} "
            f"thread={threading.current_thread().name} kf_obj_id={id(self.knowledge_file)}"
        )

        # Return unchanged (invariant: transformer doesn't mutate documents)
        return list(documents)
