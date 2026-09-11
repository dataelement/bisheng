#!/usr/bin/env python3
# ruff: noqa: E402, RUF001, RUF002
"""Read-only diagnosis of portal file-count drop and department-to-personal marks.

Collects MySQL inventory, homepage ES snapshots, and files marked
``迁移完成，需重新解析`` by ``move_department_files_to_personal.py``.
Classifies copy/cleanup reasons. Does not write business data.

From src/backend:

    PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_to_personal_impact.py
    PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_to_personal_impact.py --output /tmp/diagnose.json
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

from sqlalchemy import exists, func, or_
from sqlmodel import col, select

from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

MIGRATION_REMARK_MARK = "迁移完成，需重新解析"
MIGRATION_METADATA_KEYS = ("department_to_personal", "personal_space_merge")
SAMPLE_LIMIT_DEFAULT = 20

# First matching pattern wins for a single issue string.
# Longer / more specific needles must come before "indexes:".
ISSUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("embedding model changed", "embedding_model_changed"),
    ("no readable index chunks", "no_readable_index_chunks"),
    ("ES chunks contain no vectors", "es_no_vectors"),
    ("read Milvus", "read_milvus_failed"),
    ("read ES", "read_es_failed"),
    ("write Milvus", "write_milvus_failed"),
    ("write ES", "write_es_failed"),
    ("source parse status", "source_not_success"),
    ("overwrite indexes", "overwrite_index_cleanup"),
    ("overwrite permissions", "overwrite_permission_cleanup"),
    ("overwrite tags", "overwrite_tag_cleanup"),
    ("file projections", "projection_refresh"),
    ("content statistics", "projection_refresh"),
    ("cleanup Milvus", "cleanup_source_milvus"),
    ("cleanup ES", "cleanup_source_es"),
    ("source indexes", "cleanup_source_index"),
    ("indexes:", "index_transfer_exception"),
)

# Prefer copy/model failures over cleanup when a file has several issues.
PRIMARY_REASON_ORDER: tuple[str, ...] = (
    "embedding_model_changed",
    "no_readable_index_chunks",
    "es_no_vectors",
    "read_milvus_failed",
    "read_es_failed",
    "write_milvus_failed",
    "write_es_failed",
    "index_transfer_exception",
    "source_not_success",
    "cleanup_source_milvus",
    "cleanup_source_es",
    "cleanup_source_index",
    "overwrite_index_cleanup",
    "overwrite_permission_cleanup",
    "overwrite_tag_cleanup",
    "projection_refresh",
    "other",
)


def classify_issue(text: str) -> str:
    """Map one issue string from the migration script to a stable reason code."""
    normalized = str(text or "")
    for needle, reason in ISSUE_PATTERNS:
        if needle in normalized:
            return reason
    return "other"


def pick_primary_reason(reasons: list[str]) -> str:
    ranked = {reason: index for index, reason in enumerate(PRIMARY_REASON_ORDER)}
    return min(reasons, key=lambda reason: ranked.get(reason, len(PRIMARY_REASON_ORDER)))


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


def extract_migration_payload(remark: str | None, user_metadata: Any) -> dict[str, Any] | None:
    """Return migration audit payload if this file was marked by a merge/move script."""
    metadata = _as_dict(user_metadata)
    for key in MIGRATION_METADATA_KEYS:
        payload = metadata.get(key)
        if isinstance(payload, dict):
            issues = payload.get("issues") or []
            return {
                "source": key,
                "via": payload.get("via"),
                "source_space_id": payload.get("source_space_id"),
                "issues": [str(item) for item in issues if item],
            }
    remark_text = str(remark or "")
    if MIGRATION_REMARK_MARK in remark_text:
        remark_data = _as_dict(remark).get("data") or {}
        exception = str(remark_data.get("exception") or remark_text)
        suffix = exception.split(MIGRATION_REMARK_MARK, 1)[-1].strip(" :")
        issues = [part.strip() for part in suffix.split(";") if part.strip()]
        return {"source": "remark", "via": None, "source_space_id": None, "issues": issues or [exception]}
    return None


def classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    reasons = [classify_issue(item) for item in payload.get("issues") or []]
    if not reasons:
        reasons = ["other"]
    unique = list(dict.fromkeys(reasons))
    return {"primary_reason": pick_primary_reason(unique), "reasons": unique}


def build_conclusion(
    *,
    mysql_homepage_like: int,
    es_homepage: int | None,
    es_unknown: int,
    migration_status3: int,
    primary_counts: dict[str, int],
) -> dict[str, Any]:
    """Turn the collected numbers into an operator-facing verdict."""
    gap = None if es_homepage is None else mysql_homepage_like - es_homepage
    likely: list[str] = []
    if migration_status3:
        top = sorted(primary_counts.items(), key=lambda item: (-item[1], item[0]))
        top_label = ", ".join(f"{name}={count}" for name, count in top[:3])
        likely.append(
            f"部门转个人脚本把 {migration_status3} 个文件标成了解析失败（{top_label}）。这些文件不再进入首页文档数。"
        )
        if gap is not None and gap > 0:
            explained = min(migration_status3, gap)
            likely.append(f"MySQL 可计入与 ES 首页相差 {gap}，其中最多 {explained} 可用迁移失败解释。")
    elif gap is not None and gap > 0:
        likely.append(
            f"MySQL 可计入 {mysql_homepage_like}，ES 首页 {es_homepage}，差 {gap}。"
            "没有迁后解析失败痕迹，更像统计快照未跟上。"
        )
    if es_unknown:
        likely.append(f"ES 里有 {es_unknown} 条 file 快照的 space_level=unknown，首页查询会排除它们。")
    if es_homepage is None:
        likely.append("统计 ES 不可用，只能看 MySQL 侧。")
    if not likely:
        likely.append("未发现部门转个人导致的解析失败，MySQL 与 ES 首页口径也接近。")
    return {
        "mysql_homepage_like": mysql_homepage_like,
        "es_homepage": es_homepage,
        "gap": gap,
        "migration_status3": migration_status3,
        "likely_causes": likely,
    }


def _primary_version_predicate():
    any_version = select(KnowledgeDocumentVersion.id).where(
        KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
    )
    primary_version = any_version.where(KnowledgeDocumentVersion.is_primary == True)  # noqa: E712
    return or_(~exists(any_version), exists(primary_version))


def _homepage_mysql_filters():
    return (
        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        Knowledge.is_favorite == False,  # noqa: E712
        KnowledgeFile.file_type == FileType.FILE.value,
        KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
        col(KnowledgeFile.deleted_at).is_(None),
        _primary_version_predicate(),
    )


def _tenant_file_filter(tenant_id: int | None):
    if tenant_id is None:
        return True
    return KnowledgeFile.tenant_id == tenant_id


async def collect_mysql_inventory(session: Any, tenant_id: int | None) -> dict[str, Any]:
    tenant_filter = _tenant_file_filter(tenant_id)
    status_rows = (
        await session.exec(
            select(KnowledgeFile.status, KnowledgeFile.file_type, func.count())
            .where(tenant_filter)
            .group_by(KnowledgeFile.status, KnowledgeFile.file_type)
        )
    ).all()
    status_breakdown = [
        {"status": int(status), "file_type": int(file_type), "count": int(count)}
        for status, file_type, count in status_rows
    ]
    success_all = sum(item["count"] for item in status_breakdown if item["status"] == 2)
    success_files = sum(item["count"] for item in status_breakdown if item["status"] == 2 and item["file_type"] == 1)
    homepage_like = int(
        (
            await session.exec(
                select(func.count(KnowledgeFile.id))
                .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
                .where(*_homepage_mysql_filters(), tenant_filter)
            )
        ).one()
        or 0
    )
    level_rows = (
        await session.exec(
            select(func.coalesce(KnowledgeSpaceScope.level, "none"), func.count())
            .select_from(KnowledgeFile)
            .join(Knowledge, KnowledgeFile.knowledge_id == Knowledge.id)
            .outerjoin(KnowledgeSpaceScope, KnowledgeSpaceScope.space_id == Knowledge.id)
            .where(*_homepage_mysql_filters(), tenant_filter)
            .group_by(func.coalesce(KnowledgeSpaceScope.level, "none"))
        )
    ).all()
    by_space_level = {str(level): int(count) for level, count in level_rows}
    countable_levels = set(KNOWLEDGE_SPACE_DASHBOARD_FILE_LEVELS)
    homepage_like_with_level = sum(count for level, count in by_space_level.items() if level in countable_levels)
    return {
        "status_breakdown": status_breakdown,
        "success_all_rows": success_all,
        "success_file_rows": success_files,
        "homepage_like": homepage_like,
        "homepage_like_with_level": homepage_like_with_level,
        "homepage_like_by_space_level": by_space_level,
    }


async def collect_migration_marks(session: Any, tenant_id: int | None, sample_limit: int) -> dict[str, Any]:
    statement = (
        select(
            KnowledgeFile.id,
            KnowledgeFile.knowledge_id,
            KnowledgeFile.status,
            KnowledgeFile.remark,
            KnowledgeFile.user_metadata,
        )
        .where(
            _tenant_file_filter(tenant_id),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.remark).contains(MIGRATION_REMARK_MARK),
        )
        .order_by(KnowledgeFile.id.asc())
    )
    rows = (await session.exec(statement)).all()
    status_counts: Counter[int] = Counter()
    source_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    samples: dict[str, list[int]] = {}
    classified: list[dict[str, Any]] = []
    for file_id, knowledge_id, status, remark, user_metadata in rows:
        payload = extract_migration_payload(remark, user_metadata) or {
            "source": "remark",
            "via": None,
            "source_space_id": None,
            "issues": [],
        }
        classified_payload = classify_payload(payload)
        status_counts[int(status)] += 1
        source_counts[str(payload["source"])] += 1
        primary_counts[classified_payload["primary_reason"]] += 1
        for reason in classified_payload["reasons"]:
            reason_counts[reason] += 1
            samples.setdefault(reason, [])
            if len(samples[reason]) < sample_limit:
                samples[reason].append(int(file_id))
        classified.append(
            {
                "file_id": int(file_id),
                "knowledge_id": int(knowledge_id),
                "status": int(status),
                **payload,
                **classified_payload,
            }
        )
    return {
        "total": len(classified),
        "by_status": {str(key): value for key, value in sorted(status_counts.items())},
        "by_source": dict(source_counts),
        "by_primary_reason": dict(sorted(primary_counts.items(), key=lambda item: (-item[1], item[0]))),
        "by_reason": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sample_file_ids": samples,
        "files": classified if len(classified) <= sample_limit else classified[:sample_limit],
        "files_truncated": len(classified) > sample_limit,
    }


async def collect_es_stats() -> dict[str, Any]:
    from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService
    from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

    homepage = await PortalTelemetryEventService.count_dashboard_files()
    es_client = await get_statistics_es_connection()
    response = await es_client.search(
        index=KnowledgeSpaceContentStat.INDEX_NAME,
        body={
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"record_type": "file"}},
                        {"term": {"file_type": 1}},
                    ]
                }
            },
            "aggs": {
                "by_space_level": {"terms": {"field": "space_level", "size": 20}},
            },
        },
    )
    buckets = response.get("aggregations", {}).get("by_space_level", {}).get("buckets", [])
    by_space_level = {str(bucket.get("key")): int(bucket.get("doc_count") or 0) for bucket in buckets}
    return {
        "available": True,
        "homepage": int(homepage),
        "file_snapshots": sum(by_space_level.values()),
        "by_space_level": by_space_level,
        "unknown": int(by_space_level.get("unknown") or 0),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, help="只统计该租户；默认跨全部租户")
    parser.add_argument("--sample-limit", type=int, default=SAMPLE_LIMIT_DEFAULT)
    parser.add_argument("--output", type=Path, help="把完整 JSON 写到该文件")
    parser.add_argument("--skip-es", action="store_true", help="只查 MySQL，不连统计 ES")
    args = parser.parse_args(argv)
    if args.sample_limit <= 0 or args.sample_limit > 200:
        parser.error("--sample-limit must be between 1 and 200")
    if args.tenant_id is not None and args.tenant_id <= 0:
        parser.error("--tenant-id must be a positive integer")
    return args


async def generate_report(args: argparse.Namespace) -> dict[str, Any]:
    async with get_async_db_session() as session:
        with bypass_tenant_filter():
            mysql = await collect_mysql_inventory(session, args.tenant_id)
            migration = await collect_migration_marks(session, args.tenant_id, args.sample_limit)
    es: dict[str, Any]
    if args.skip_es:
        es = {"available": False, "skipped": True, "homepage": None, "unknown": 0}
    else:
        try:
            es = await collect_es_stats()
        except Exception as exc:
            es = {
                "available": False,
                "skipped": False,
                "homepage": None,
                "unknown": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
    conclusion = build_conclusion(
        mysql_homepage_like=int(mysql["homepage_like_with_level"]),
        es_homepage=es.get("homepage"),
        es_unknown=int(es.get("unknown") or 0),
        migration_status3=int((migration.get("by_status") or {}).get("3") or 0),
        primary_counts=migration.get("by_primary_reason") or {},
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": args.tenant_id,
        "conclusion": conclusion,
        "mysql": mysql,
        "elasticsearch": es,
        "migration_marks": migration,
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
    for line in report["conclusion"]["likely_causes"]:
        print(f"[结论] {line}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
