"""Robot-only candidate ranking without a provider/model call.

BM25 is computed over the same authorized candidate corpus for all spaces.
RRF combines that global lexical rank with each candidate's local recall rank;
provider scores and cross-space embedding distances are never compared.
"""

import math
from collections import Counter
from collections.abc import Sequence

import jieba
from langchain_core.documents import Document

from bisheng.eplus.domain.services.knowledge_result import robot_document_body


def _tokens(text: str) -> list[str]:
    return [term.casefold() for term in jieba.lcut(text) if any(char.isalnum() for char in term)]


def rank_robot_candidates(documents: Sequence[Document], query: str) -> list[Document]:
    if not documents:
        return []
    terms = set(_tokens(query))
    counts = [
        Counter(_tokens(f"{doc.metadata.get('document_name', '')}\n{robot_document_body(doc.page_content)}"))
        for doc in documents
    ]
    lengths = [sum(count.values()) for count in counts]
    average = max(sum(lengths) / len(lengths), 1)
    frequencies = {term: sum(term in count for count in counts) for term in terms}
    lexical_scores = []
    for count, length in zip(counts, lengths, strict=True):
        score = 0.0
        for term in terms:
            frequency = count.get(term, 0)
            if frequency:
                inverse = math.log(1 + (len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                score += inverse * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average))
        lexical_scores.append(score)

    # Canonical ties are independent of binding order, unlike list concatenation.
    def tie(index: int) -> tuple:
        doc = documents[index]
        return (int(doc.metadata["document_id"]), int(doc.metadata.get("chunk_index") or 0), doc.page_content)

    lexical_order = sorted(range(len(documents)), key=lambda index: (-lexical_scores[index], tie(index)))
    lexical_ranks = {index: rank for rank, index in enumerate(lexical_order, 1) if lexical_scores[index] > 0}

    def score(index: int) -> float:
        local_rank = max(int(documents[index].metadata.get("robot_recall_rank", 1)), 1)
        lexical_rank = lexical_ranks.get(index)
        return 0.5 / (60 + local_rank) + (0.5 / (60 + lexical_rank) if lexical_rank is not None else 0)

    return [documents[index] for index in sorted(range(len(documents)), key=lambda index: (-score(index), tie(index)))]


def trim_robot_candidates(documents: Sequence[Document], max_content: int) -> list[Document]:
    remaining = max(int(max_content), 0)
    result = []
    for doc in documents:
        if remaining <= 0:
            break
        body = robot_document_body(doc.page_content)
        content = body[:remaining]
        metadata = {**doc.metadata, "robot_body_normalized": True}
        if len(content) < len(body):
            metadata["content_truncated"] = True
        result.append(Document(page_content=content, metadata=metadata))
        remaining -= len(content)
    return result
