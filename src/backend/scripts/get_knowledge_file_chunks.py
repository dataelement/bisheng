#!/usr/bin/env python3
"""Print every Elasticsearch chunk for one knowledge file as JSON.

Run this command from ``src/backend``:

    PYTHONPATH=./ .venv/bin/python scripts/get_knowledge_file_chunks.py \
        --knowledge-file-id 123

The script is read-only. It resolves the knowledge base from the knowledge
file record, then retrieves every matching Elasticsearch document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao  # noqa: E402


class ScriptError(Exception):
    """Known script failure with a distinct process exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def positive_int(value: str) -> int:
    """Parse a strictly positive integer command-line value."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _normalize_chunk(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source") or {}
    metadata = source.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": hit.get("_id"),
        "text": source.get("text", ""),
        "metadata": metadata,
    }


def _chunk_sort_key(chunk: dict[str, Any]) -> tuple[int, int | str, str]:
    chunk_index = chunk["metadata"].get("chunk_index")
    try:
        return 0, int(chunk_index), str(chunk["id"] or "")
    except (TypeError, ValueError):
        return 1, str(chunk_index or ""), str(chunk["id"] or "")


def fetch_all_chunks(*, knowledge_file_id: int) -> dict[str, Any]:
    """Resolve a file and return every corresponding Elasticsearch chunk."""
    with bypass_tenant_filter():
        knowledge_file = KnowledgeFileDao.query_by_id_sync(knowledge_file_id)
        if knowledge_file is None:
            raise ScriptError(f"knowledge_file_id={knowledge_file_id} does not exist", 3)

        knowledge = KnowledgeDao.query_by_id(knowledge_file.knowledge_id)
    if knowledge is None:
        raise ScriptError(
            f"knowledge_id={knowledge_file.knowledge_id} for knowledge_file_id={knowledge_file_id} does not exist",
            4,
        )
    if not knowledge.index_name:
        raise ScriptError(
            f"knowledge_id={knowledge.id} has no Elasticsearch index_name",
            4,
        )

    try:
        es_store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge)
        result = es_store.client.search(
            index=knowledge.index_name,
            query={"term": {"metadata.document_id": knowledge_file_id}},
            size=1000,
            scroll="1m",
            source=True,
        )
    except Exception as exc:  # Convert external-service failures to a stable CLI result.
        raise ScriptError(f"Elasticsearch query failed: {exc}", 5) from exc

    chunks: list[dict[str, Any]] = []
    scroll_id = result.get("_scroll_id")
    try:
        while True:
            hits = result.get("hits", {}).get("hits", [])
            if not hits:
                break
            chunks.extend(_normalize_chunk(hit) for hit in hits)
            if not scroll_id:
                break
            result = es_store.client.scroll(scroll_id=scroll_id, scroll="1m")
            scroll_id = result.get("_scroll_id", scroll_id)
    except Exception as exc:  # Convert external-service failures to a stable CLI result.
        raise ScriptError(f"Elasticsearch scroll failed: {exc}", 5) from exc
    finally:
        if scroll_id:
            try:
                es_store.client.clear_scroll(scroll_id=scroll_id)
            except Exception:  # Cleanup must not hide a successful read result.
                pass

    chunks.sort(key=_chunk_sort_key)
    return {
        "knowledge_file_id": knowledge_file_id,
        "knowledge_id": knowledge.id,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print every Elasticsearch chunk for one knowledge file as JSON.",
    )
    parser.add_argument(
        "--knowledge-file-id",
        required=True,
        type=positive_int,
        help="KnowledgeFile ID to query.",
    )
    args = parser.parse_args()

    try:
        payload = fetch_all_chunks(knowledge_file_id=args.knowledge_file_id)
    except ScriptError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # Keep database and configuration failures actionable for operators.
        print(f"error: unexpected failure: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
