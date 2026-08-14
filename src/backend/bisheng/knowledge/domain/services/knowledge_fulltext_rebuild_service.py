"""对 RAG Chunk 做完整性校验并确定性重建可检索全文。"""

from __future__ import annotations

import hashlib
import re

from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextChunk,
    KnowledgeFulltextRebuiltContent,
)


class KnowledgeFulltextChunkNotReadyError(RuntimeError):
    """Chunk 尚未写入完成。"""


class KnowledgeFulltextProjectionNotReadyError(KnowledgeFulltextChunkNotReadyError):
    """投影或知识库 RAG 索引尚未就绪，不代表文件 Chunk 已损坏。"""


class KnowledgeFulltextChunkCorruptedError(RuntimeError):
    """Chunk 序列或归属损坏。"""


class KnowledgeFulltextRebuildService:
    _MARKDOWN_HEADING = re.compile(r"^(?:#{1,6}\s+.+\n)+")

    def __init__(self, *, max_overlap_chars: int = 1000):
        if max_overlap_chars < 0:
            raise ValueError("max_overlap_chars must not be negative")
        self.max_overlap_chars = max_overlap_chars

    def rebuild(
        self,
        chunks: list[KnowledgeFulltextChunk],
        *,
        file_id: int,
        knowledge_id: int,
    ) -> KnowledgeFulltextRebuiltContent:
        if not chunks:
            raise KnowledgeFulltextChunkNotReadyError("no RAG chunks are available")
        ordered = sorted(chunks, key=lambda item: (item.chunk_index, item.es_id))
        indexes = [item.chunk_index for item in ordered]
        if indexes != list(range(len(ordered))):
            raise KnowledgeFulltextChunkCorruptedError("chunk indexes must be unique and contiguous from zero")
        for item in ordered:
            if item.document_id != file_id or item.knowledge_id != knowledge_id:
                raise KnowledgeFulltextChunkCorruptedError("chunk belongs to another file or knowledge")

        parts: list[str] = []
        for item in ordered:
            text = self._unwrap_chunk(item.text).strip()
            if not parts:
                parts.append(text)
                continue
            text = self._remove_exact_overlap(parts[-1], text)
            text = self._remove_repeated_heading(parts[-1], text)
            if text:
                parts.append(text)
        content = "\n".join(part for part in parts if part)
        if not content:
            raise KnowledgeFulltextChunkNotReadyError("RAG chunks contain no searchable content")
        return KnowledgeFulltextRebuiltContent(
            content=content,
            chunk_count=len(ordered),
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _unwrap_chunk(text: str) -> str:
        """兼容 KnowledgeUtils.split_chunk_metadata 的新旧包装格式。"""
        paragraph_start = "<paragraph_content>"
        paragraph_end = "</paragraph_content>"
        if paragraph_start in text:
            body = text.split(paragraph_start, 1)[1]
            return body.split(paragraph_end, 1)[0]
        return text.split("\n----------\n")[-1]

    def _remove_exact_overlap(self, previous: str, current: str) -> str:
        maximum = min(self.max_overlap_chars, len(previous), len(current))
        for length in range(maximum, 0, -1):
            if previous[-length:] == current[:length]:
                return current[length:].lstrip("\n")
        return current

    def _remove_repeated_heading(self, previous: str, current: str) -> str:
        match = self._MARKDOWN_HEADING.match(current)
        if not match:
            return current
        heading = match.group(0).rstrip("\n")
        if previous.endswith(heading):
            return current[match.end() :].lstrip("\n")
        return current
