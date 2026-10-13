#!/usr/bin/env python3
"""根据真实收藏引用的创建记录补齐历史收藏日统计。

在 src/backend 执行:
  .venv/bin/python scripts/backfill_portal_favorite_statistics.py \
    --tenant-id 1 --created-before 2026-09-01 --reference-id 103442

默认只读预览; 确认报告并进入受控维护窗口后, 增加 --apply 才写入。
仅创建稳定引用 ID 对应的新统计, 不覆盖旧统计、不重建索引。已删除的
历史引用不能从重复成功事件推断, 来源快照缺失或同文件同日已有统计时跳过。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from bisheng.common.constants.telemetry import (  # noqa: E402
    KNOWLEDGE_SPACE_CONTENT_STAT_INDEX,
    KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS,
)

INDEX = KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
CHINA = timezone(timedelta(hours=8))
BATCH_SIZE = 500
IDENTITY_FIELDS = (
    "record_type",
    "favorite_count",
    "tenant_id",
    "file_id",
    "space_id",
    "local_date",
    "timestamp",
    "backfill_reference_id",
    "backfill_user_id",
    "backfill_source",
)


def local_time(value: datetime | str) -> datetime:
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    return value.replace(tzinfo=CHINA) if value.tzinfo is None else value.astimezone(CHINA)


def read_documents(es: Any, ids: list[str]) -> dict[str, dict | None]:
    response = es.mget(index=INDEX, ids=ids)
    result = {}
    for item in response.get("docs", []):
        key = item.get("_id")
        if key not in ids or key in result or item.get("error"):
            raise RuntimeError("ES snapshot read failed or returned an unexpected identity")
        if item.get("found") is True and isinstance(item.get("_source"), dict):
            result[key] = item["_source"]
        elif item.get("found") is False:
            result[key] = None
        else:
            raise RuntimeError("ES snapshot read is incomplete")
    if set(result) != set(ids):
        raise RuntimeError("ES snapshot read is incomplete")
    return result


def verify_identity(expected: dict, actual: dict | None) -> None:
    if actual is None or any(expected.get(field) != actual.get(field) for field in IDENTITY_FIELDS):
        raise RuntimeError("Backfill identity conflict; existing statistics were not overwritten")


def existing_daily(es: Any, file_id: int, local_date: str) -> bool:
    response = es.search(
        index=INDEX,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"record_type": "favorite_daily"}},
                        {"term": {"file_id": file_id}},
                        {"term": {"local_date": local_date}},
                    ]
                }
            },
        },
    )
    if response.get("timed_out") or response.get("_shards", {}).get("failed", 0):
        raise RuntimeError("ES daily statistics read failed")
    total = response.get("hits", {}).get("total")
    if not isinstance(total, dict) or total.get("relation") != "eq" or "value" not in total:
        raise RuntimeError("ES daily statistics read is incomplete")
    return int(total["value"]) > 0


def plan_backfill(
    references: list[dict],
    es: Any,
    *,
    tenant_id: int,
    created_before: datetime,
) -> dict:
    report = {"candidates": [], "skipped": []}
    cutoff = local_time(created_before)
    for ref in references:
        ref_id = int(ref["id"])

        def skip(reason: str, reference_id: int = ref_id) -> None:
            report["skipped"].append({"reference_id": reference_id, "reason": reason})

        if ref.get("tenant_id") != tenant_id:
            skip("other_tenant")
            continue
        if not ref.get("create_time"):
            skip("creation_time_missing")
            continue
        created = local_time(ref["create_time"])
        if created >= cutoff:
            skip("outside_historical_scope")
            continue
        meta = ref.get("user_metadata") or {}
        meta = json.loads(meta) if isinstance(meta, str) else meta
        origin = meta.get("favorite_reference") or {}
        file_id = int(origin.get("source_file_id") or 0)
        space_id = int(origin.get("source_space_id") or 0)
        if file_id <= 0 or space_id <= 0 or not ref.get("user_id"):
            skip("origin_identity_missing")
            continue
        key = f"favorite_backfill:{tenant_id}:{ref_id}"
        day = created.date().isoformat()
        proof = {
            "record_type": "favorite_daily",
            "favorite_count": 1,
            "tenant_id": tenant_id,
            "file_id": file_id,
            "space_id": space_id,
            "local_date": day,
            "timestamp": int(datetime.combine(created.date(), time.min, tzinfo=CHINA).timestamp()),
            "backfill_reference_id": ref_id,
            "backfill_user_id": int(ref["user_id"]),
            "backfill_source": "favorite_reference",
        }
        docs = read_documents(es, [str(file_id), key])
        if docs[key] is not None:
            verify_identity(proof, docs[key])
            skip("already_backfilled")
            continue
        snapshot = docs[str(file_id)]
        if snapshot is None:
            skip("source_snapshot_missing")
            continue
        if (
            snapshot.get("record_type") != "file"
            or int(snapshot.get("file_id") or 0) != file_id
            or int(snapshot.get("space_id") or 0) != space_id
            or int(snapshot.get("tenant_id") or 0) != tenant_id
            or snapshot.get("file_type") != 1
            or not snapshot.get("knowledge_identity")
            or snapshot.get("space_level") not in KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS
        ):
            skip("source_snapshot_invalid_or_changed")
            continue
        if existing_daily(es, file_id, day):
            skip("existing_daily_statistics")
            continue
        dimensions = {
            field: value
            for field, value in snapshot.items()
            if field not in {"record_type", "timestamp", "sync_run_id", "projection_updated_at"}
        }
        report["candidates"].append(
            {
                "id": key,
                "reference_id": ref_id,
                "document": {**dimensions, "knowledge_identity": snapshot["knowledge_identity"], **proof},
            }
        )
    return report


def apply_plan(es: Any, entries: list[dict]) -> dict:
    result = {"created": 0, "already_exists": 0, "verified": 0}
    for start in range(0, len(entries), BATCH_SIZE):
        batch = entries[start : start + BATCH_SIZE]
        operations = []
        for entry in batch:
            operations.extend([{"create": {"_index": INDEX, "_id": entry["id"]}}, entry["document"]])
        response = es.bulk(operations=operations, refresh="wait_for")
        items = response.get("items", [])
        if len(items) != len(batch):
            raise RuntimeError("Backfill write failed: incomplete bulk response")
        for entry, item in zip(batch, items, strict=True):
            status = item.get("create", {})
            if status.get("_id") != entry["id"] or status.get("status") not in (201, 409):
                raise RuntimeError(f"Backfill write failed for {entry['id']}; rerun preview before continuing")
            result["created" if status["status"] == 201 else "already_exists"] += 1
        stored = read_documents(es, [entry["id"] for entry in batch])
        for entry in batch:
            verify_identity(entry["document"], stored[entry["id"]])
            result["verified"] += 1
    return result


def load_references(created_before: datetime, reference_ids: list[int]) -> list[dict]:
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_sync_db_session
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    result, cursor = [], 0
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            while True:
                statement = select(KnowledgeFile).where(
                    KnowledgeFile.file_source == "favorite_reference",
                    KnowledgeFile.id > cursor,
                    KnowledgeFile.create_time < local_time(created_before).replace(tzinfo=None),
                )
                if reference_ids:
                    statement = statement.where(KnowledgeFile.id.in_(reference_ids))
                rows = session.exec(statement.order_by(KnowledgeFile.id).limit(BATCH_SIZE)).all()
                if not rows:
                    break
                result.extend(row.model_dump() for row in rows)
                cursor = int(rows[-1].id)
            session.rollback()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--created-before", type=datetime.fromisoformat, required=True)
    parser.add_argument("--reference-id", type=int, action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.tenant_id <= 0 or any(value <= 0 for value in args.reference_id):
        parser.error("租户和引用 ID 必须为正整数")
    if args.apply and not args.reference_id:
        parser.error("--apply 必须显式指定已核对的 --reference-id")

    from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync

    es = get_statistics_es_connection_sync()
    try:
        if not es.indices.exists(index=INDEX):
            raise RuntimeError("统计索引不存在, 不能将读取失败当成缺失")
        references = load_references(args.created_before, args.reference_id)
        if args.reference_id and set(args.reference_id) != {int(row["id"]) for row in references}:
            raise RuntimeError("指定引用不在历史范围内或已不存在, 未写入")
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "index": INDEX,
            "tenant_id": args.tenant_id,
            "created_before": local_time(args.created_before).isoformat(),
            **plan_backfill(references, es, tenant_id=args.tenant_id, created_before=args.created_before),
        }
        report["expected_count_delta"] = len(report["candidates"])
        if args.apply:
            report["result"] = apply_plan(es, report["candidates"])
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report:
            args.report.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    finally:
        es.close()


if __name__ == "__main__":
    sys.exit(main())
