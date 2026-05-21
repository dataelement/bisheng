"""RAG retrieval filter helper — exclude non-primary versions.

Pure string/dict manipulation. No DB access; callers fetch the excluded
file id list separately and pass it in.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple


def build_primary_only_filter(
    excluded_file_ids: Iterable[int],
    *,
    base_milvus_expr: Optional[str] = None,
    base_es_filter: Optional[List[dict]] = None,
) -> Tuple[Optional[str], List[dict]]:
    """Combine an existing Milvus expr / ES filter with a "not in non-primary" clause.

    Args:
        excluded_file_ids: file_ids to exclude (non-primary knowledge_file_id).
        base_milvus_expr: existing Milvus expr string; will be ANDed with the new clause.
        base_es_filter: existing ES filter list; the new clause is appended as must_not.

    Returns:
        (milvus_expr, es_filter)
        - milvus_expr: combined expr string (None if no exclusions and base is None).
        - es_filter: new list (does not mutate input).

    Behavior:
        - empty excluded_file_ids -> return base inputs unchanged
          (None or empty list as the case may be).
        - Milvus exclusion clause: "document_id not in [<ids>]"
          AND-combined with base when present (uses "and" lowercase per Milvus syntax).
        - ES exclusion clause appended:
          {"bool": {"must_not": {"terms": {"metadata.document_id": [ids]}}}}.
        - Deterministic ID ordering for stable test assertions: sort ids ascending
          before building the literal arrays.
    """
    ids: List[int] = sorted(set(excluded_file_ids))

    # Normalise base_es_filter to a list copy (never mutate caller's list)
    es_out: List[dict] = list(base_es_filter) if base_es_filter else []

    if not ids:
        # Nothing to exclude — return bases unchanged
        return base_milvus_expr, es_out

    # Build Milvus exclusion clause
    ids_literal = "[" + ", ".join(str(i) for i in ids) + "]"
    milvus_clause = f"document_id not in {ids_literal}"

    if base_milvus_expr:
        milvus_expr: Optional[str] = f"{base_milvus_expr} and {milvus_clause}"
    else:
        milvus_expr = milvus_clause

    # Build ES must_not clause and append to copy of base filter
    es_out.append(
        {"bool": {"must_not": {"terms": {"metadata.document_id": ids}}}}
    )

    return milvus_expr, es_out
