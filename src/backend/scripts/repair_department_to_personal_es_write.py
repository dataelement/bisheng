#!/usr/bin/env python3
# ruff: noqa: E402, RUF001
"""Inspect and repair department-to-personal files marked write_es_failed.

Default is a dry-run sample: count Milvus/ES chunks in the current personal
space. --apply rewrites ES from Milvus and restores status=2 only when Milvus
already has vectors. Missing personal ES indices are created with the same
metadata mapping as normal parse. Does not reparse. Does not delete MinIO.

From src/backend:

    PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py
    PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --file-id 110858 --file-id 110883
    PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --sample 20 --probe-error
    PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --sample 20 --apply
    PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --all --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus

MIGRATION_REMARK_MARK = "迁移完成，需重新解析"
WRITE_ES_MARK = "write ES:"
VECTOR_FIELD_NAMES = {"vector", "embedding", "embeddings"}
DROP_FIELD_NAMES = VECTOR_FIELD_NAMES | {"pk", "_merge_key"}
SAMPLE_DEFAULT = 20


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_issues(remark: str | None, user_metadata: Any) -> list[str]:
    metadata = _as_dict(user_metadata)
    payload = metadata.get("department_to_personal")
    if isinstance(payload, dict):
        return [str(item) for item in (payload.get("issues") or []) if item]
    return []


def is_write_es_failed(remark: str | None, user_metadata: Any) -> bool:
    if any(WRITE_ES_MARK in item for item in extract_issues(remark, user_metadata)):
        return True
    return WRITE_ES_MARK in str(remark or "")


def classify_index_state(milvus_count: int, es_count: int) -> str:
    if milvus_count > 0 and es_count <= 0:
        return "milvus_ready_es_missing"
    if milvus_count > 0 and es_count > 0 and es_count != milvus_count:
        return "milvus_ready_es_partial"
    if milvus_count > 0 and es_count > 0:
        return "both_present"
    return "milvus_missing"


def _looks_like_vector(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 32
        and isinstance(value[0], (int, float))
        and not isinstance(value[0], bool)
    )


def sanitize_es_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep ES metadata free of dense vectors and Milvus primary keys."""
    metadata = dict(row)
    text = metadata.pop("text", "")
    for name in list(metadata):
        if name in DROP_FIELD_NAMES or _looks_like_vector(metadata.get(name)):
            metadata.pop(name, None)
    return {"text": text, "metadata": metadata}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id", dest="file_ids", action="append", type=int, default=[])
    parser.add_argument("--sample", type=int, default=SAMPLE_DEFAULT, help="sample size when not using --all")
    parser.add_argument("--all", action="store_true", help="inspect or repair every write_es_failed file")
    parser.add_argument(
        "--probe-error", action="store_true", help="retry one sanitized ES doc and keep the mapper error"
    )
    parser.add_argument("--apply", action="store_true", help="rewrite ES from Milvus and restore status=2")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if any(file_id <= 0 for file_id in args.file_ids):
        parser.error("--file-id must be a positive integer")
    if args.sample <= 0 or args.sample > 500:
        parser.error("--sample must be between 1 and 500")
    if args.all and args.file_ids:
        parser.error("--all cannot be combined with --file-id")
    return args


async def load_candidates(file_ids: list[int], sample: int, all_files: bool) -> list[KnowledgeFile]:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            if file_ids:
                rows = (
                    await session.exec(
                        select(KnowledgeFile).where(
                            col(KnowledgeFile.id).in_(file_ids),
                            KnowledgeFile.file_type == FileType.FILE.value,
                        )
                    )
                ).all()
                return list(rows)
            statement = (
                select(KnowledgeFile)
                .where(
                    KnowledgeFile.file_type == FileType.FILE.value,
                    KnowledgeFile.status == KnowledgeFileStatus.FAILED.value,
                    col(KnowledgeFile.remark).contains(MIGRATION_REMARK_MARK),
                )
                .order_by(KnowledgeFile.id.asc())
            )
            rows = [
                row
                for row in (await session.exec(statement)).all()
                if is_write_es_failed(row.remark, row.user_metadata)
            ]
    return rows if all_files else rows[:sample]


def count_milvus(space: Knowledge, file_id: int) -> tuple[int, list[dict[str, Any]], str | None]:
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    try:
        store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(0, knowledge=space, embeddings=FakeEmbeddings())
        if store.col is None:
            return 0, [], "milvus collection missing"
        fields = [field.name for field in store.col.schema.fields]
        iterator = store.col.query_iterator(
            expr=f"document_id=={file_id} && knowledge_id=={space.id}",
            output_fields=fields,
            batch_size=500,
            timeout=60,
        )
        rows: list[dict[str, Any]] = []
        try:
            while batch := iterator.next():
                rows.extend(dict(row) for row in batch)
        finally:
            iterator.close()
        return len(rows), rows, None
    except Exception as exc:
        return 0, [], f"{type(exc).__name__}: {exc}"


def count_es(space: Knowledge, file_id: int) -> tuple[int, str | None]:
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    try:
        store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
        client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
        index = space.index_name or space.collection_name
        if not client.indices.exists(index=index):
            return 0, f"es index missing: {index}"
        response = client.count(index=index, body={"query": {"term": {"metadata.document_id": file_id}}})
        return int(response.get("count") or 0), None
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def probe_es_error(space: Knowledge, rows: list[dict[str, Any]]) -> str | None:
    from elasticsearch.helpers import BulkIndexError, bulk

    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    if not rows:
        return None
    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
    client = store.client.options(request_timeout=60, max_retries=0, retry_on_timeout=False)
    index = space.index_name or space.collection_name
    payload = sanitize_es_row(rows[0])
    action = {
        "_op_type": "index",
        "_index": index,
        "_id": f"repair-probe:{payload['metadata'].get('document_id')}",
        "_source": payload,
    }
    try:
        bulk(client, [action], chunk_size=1, max_retries=0, raise_on_error=True)
        client.delete(index=index, id=action["_id"], ignore=[404])
        return None
    except BulkIndexError as exc:
        errors = exc.errors or []
        return json.dumps(errors[0] if errors else str(exc), ensure_ascii=False, default=str)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def write_es_from_milvus(space: Knowledge, file_id: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    from elasticsearch.helpers import BulkIndexError

    from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    # Same mapping as knowledge create / space_init, otherwise a dynamic index
    # would later conflict with normal parse.
    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(
        knowledge=space,
        metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
    )
    client = store.client
    index = space.index_name or space.collection_name
    created_index = False
    if client.indices.exists(index=index):
        client.delete_by_query(
            index=index,
            query={"term": {"metadata.document_id": file_id}},
            refresh=True,
        )
    else:
        store._store._create_index_if_not_exists()
        created_index = True
    payloads = [sanitize_es_row(row) for row in rows]
    ids = [f"repair:{file_id}:{row.get('pk', position)}" for position, row in enumerate(rows)]
    try:
        store.add_texts(
            texts=[item["text"] for item in payloads],
            metadatas=[item["metadata"] for item in payloads],
            ids=ids,
            refresh_indices=True,
            create_index_if_not_exists=True,
            bulk_kwargs={"chunk_size": 100},
        )
        return {
            "ok": True,
            "written": len(payloads),
            "created_index": created_index,
            "index": index,
            "error": None,
        }
    except BulkIndexError as exc:
        first = (exc.errors or [str(exc)])[0]
        return {
            "ok": False,
            "written": 0,
            "created_index": created_index,
            "index": index,
            "error": json.dumps(first, ensure_ascii=False, default=str),
        }
    except Exception as exc:
        return {
            "ok": False,
            "written": 0,
            "created_index": created_index,
            "index": index,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def restore_success(file_id: int, space_id: int) -> None:
    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            record = await session.get(KnowledgeFile, file_id)
            if record is None:
                raise RuntimeError(f"file missing after repair: {file_id}")
            metadata = dict(record.user_metadata or {})
            detail = dict(metadata.get("department_to_personal") or {})
            detail["es_repaired_at"] = datetime.now(timezone.utc).isoformat()
            metadata["department_to_personal"] = detail
            record.user_metadata = metadata
            record.status = KnowledgeFileStatus.SUCCESS.value
            record.remark = ""
            session.add(record)
            await session.commit()
    await KnowledgeDao.async_update_knowledge_update_time_by_id(space_id)
    await KnowledgeSpaceContentStat.enqueue_file_stat_async([file_id])


async def inspect_file(file: KnowledgeFile, *, probe_error: bool, apply: bool) -> dict[str, Any]:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            space = await session.get(Knowledge, file.knowledge_id)
    if space is None:
        return {"file_id": file.id, "state": "space_missing", "error": f"knowledge_id={file.knowledge_id}"}
    milvus_count, rows, milvus_error = await asyncio.to_thread(count_milvus, space, int(file.id))
    es_count, es_error = await asyncio.to_thread(count_es, space, int(file.id))
    state = classify_index_state(milvus_count, es_count)
    result: dict[str, Any] = {
        "file_id": int(file.id),
        "knowledge_id": int(space.id),
        "status": int(file.status),
        "milvus_count": milvus_count,
        "es_count": es_count,
        "state": state,
        "milvus_error": milvus_error,
        "es_error": es_error,
        "probe_error": None,
        "repaired": False,
    }
    if probe_error and rows:
        result["probe_error"] = await asyncio.to_thread(probe_es_error, space, rows)
    if apply and milvus_count > 0:
        write_result = await asyncio.to_thread(write_es_from_milvus, space, int(file.id), rows)
        result["write"] = write_result
        if write_result["ok"]:
            await restore_success(int(file.id), int(space.id))
            result["repaired"] = True
            result["status"] = KnowledgeFileStatus.SUCCESS.value
        else:
            result["error"] = write_result["error"]
    return result


async def generate_report(args: argparse.Namespace) -> dict[str, Any]:
    files = await load_candidates(args.file_ids, args.sample, args.all)
    results = []
    for file in files:
        results.append(await inspect_file(file, probe_error=args.probe_error, apply=args.apply))
    states = Counter(item["state"] for item in results)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "apply": args.apply,
        "selected": len(files),
        "by_state": dict(states),
        "repairable": states.get("milvus_ready_es_missing", 0)
        + states.get("milvus_ready_es_partial", 0)
        + states.get("both_present", 0),
        "needs_reparse": states.get("milvus_missing", 0),
        "repaired": sum(1 for item in results if item.get("repaired")),
        "results": results,
    }


async def run(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context

    await initialize_app_context(config=settings)
    try:
        report = await generate_report(args)
    finally:
        await close_app_context()
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        path = args.output.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    print(text)
    print(
        f"[摘要] selected={report['selected']} repairable={report['repairable']} "
        f"needs_reparse={report['needs_reparse']} repaired={report['repaired']}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
