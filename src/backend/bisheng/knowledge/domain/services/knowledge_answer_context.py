"""Fair, deterministic context selection without changing legacy recall."""

import json
from collections import deque

from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import KnowledgeAnswerRetrievalError
from bisheng.knowledge.domain.schemas.knowledge_answer_schema import KnowledgeAnswerReference


def _source_integer(value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise KnowledgeAnswerRetrievalError()
    try:
        result = int(value)
    except ValueError as exc:
        raise KnowledgeAnswerRetrievalError() from exc
    if result < minimum:
        raise KnowledgeAnswerRetrievalError()
    return result


def build_answer_context(
    results_by_space: dict[int, list[Document]], *, top_k: int, max_content: int
) -> tuple[str, list[KnowledgeAnswerReference]]:
    """Round-robin ranked chunks; cap actual body characters across all spaces."""
    queues: dict[int, deque] = {}
    seen_chunks: set[tuple[int, int, int]] = set()
    for space_id in sorted(results_by_space):
        queues[space_id] = deque()
        for document in results_by_space[space_id]:
            if not isinstance(document.page_content, str):
                raise KnowledgeAnswerRetrievalError()
            text = document.page_content.strip()
            if not text:
                continue
            metadata = document.metadata or {}
            file_id = _source_integer(metadata.get("document_id"), minimum=1)
            index = _source_integer(metadata.get("chunk_index"), minimum=0)
            key = (space_id, file_id, index)
            if key in seen_chunks:
                continue
            seen_chunks.add(key)
            reference = KnowledgeAnswerReference(
                knowledge_id=space_id,
                document_id=file_id,
                document_name=str(metadata.get("document_name") or ""),
                document_update_time=str(metadata.get("document_update_time") or ""),
            )
            queues[space_id].append((reference, index, text))

    chunks: list[dict] = []
    references: dict[tuple[int, int], KnowledgeAnswerReference] = {}
    length = 0
    while len(chunks) < top_k and length < max_content:
        progressed = False
        for queue in queues.values():
            if not queue:
                continue
            reference, index, text = queue.popleft()
            body = text[: max_content - length]
            chunks.append(
                {**reference.model_dump(), "chunk_index": index, "content": body, "truncated": len(body) < len(text)}
            )
            references.setdefault((reference.knowledge_id, reference.document_id), reference)
            length += len(body)
            progressed = True
            if len(chunks) >= top_k or length >= max_content:
                break
        if not progressed:
            break
    if not chunks:
        return "", []
    return json.dumps({"reference_chunks": chunks}, ensure_ascii=False), list(references.values())
