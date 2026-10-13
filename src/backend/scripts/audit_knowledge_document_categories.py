#!/usr/bin/env python3
"""只读审计看板文档分类、入口身份和统计投影差异。

在 src/backend 执行:
    .venv/bin/python scripts/audit_knowledge_document_categories.py --tenant-id 1 --space-id 123
    .venv/bin/python scripts/audit_knowledge_document_categories.py --tenant-id 1 --document-id 91 --output audit.json
123/91 为示例 ID, 执行时使用实际范围。不写数据库/ES、不排队刷新、不调用内容解析。
输出文件必须不存在, 防止覆盖已有报告。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

INDEX = "mid_knowledge_space_content_stat"
FIELDS = [
    "tenant_id",
    "knowledge_identity",
    "file_id",
    "space_id",
    "file_category_code",
    "file_category_name",
    "sync_run_id",
    "projection_updated_at",
    "timestamp",
]


def positive(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=positive, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--space-id", type=positive, action="append")
    scope.add_argument("--document-id", type=positive, action="append")
    parser.add_argument("--limit", type=positive, default=2000, help="最多读取的文件快照数, 上限 10000")
    parser.add_argument("--batch-size", type=positive, default=200, help="数据库批量读取大小, 上限 400")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.limit > 10000 or args.batch_size > 400 or len(args.space_id or args.document_id) > 400:
        parser.error("范围最多 400 个 ID, limit 最大 10000, batch-size 最大 400")
    if args.output and args.output.exists():
        parser.error("输出文件已存在, 不允许覆盖")
    return args


def code(value: Any) -> str:
    return str(value or "").strip().upper()


def build_report(records: list[dict], sources: dict, labels: dict, tenant_id: int) -> dict:
    groups = defaultdict(list)
    for row in records:
        if int(row.get("tenant_id", 0)) != tenant_id:
            raise ValueError("索引返回超出租户范围的记录")
        groups[row.get("knowledge_identity") or "missing_identity"].append(row)
    problems, counts = [], Counter()
    for identity, rows in sorted(groups.items()):
        issues = set()
        current = [sources["files"].get(int(row["file_id"])) for row in rows]
        if identity == "missing_identity":
            issues.add("missing_identity")
        if any(row is None for row in current):
            issues.add("database_file_missing")
        for row in current:
            if row is None:
                continue
            if row["knowledge_identity"] != identity or len(row.get("version_document_ids", [])) > 1:
                issues.add("identity_mismatch")
            if (
                identity.startswith("document:")
                and identity[9:].isdigit()
                and any(value != int(identity[9:]) for value in row.get("version_document_ids", []))
            ):
                issues.add("identity_mismatch")
            if not row["active"]:
                issues.add("inactive_entry")
        document = None
        entries = [row for row in current if row]
        authority = None
        if identity.startswith("document:") and identity[9:].isdigit():
            doc_id = int(identity[9:])
            document = sources["documents"].get(doc_id)
            entries = sources["entries"].get(doc_id, [])
            active = [row for row in entries if row["active"]]
            managers = [row for row in active if row["entry_type"] == "manager"]
            if not document or document["lifecycle_status"] != "active" or not document["primary_version_file_id"]:
                issues.add("document_missing_or_inactive")
            if len(managers) != 1:
                issues.add("missing_or_ambiguous_manager")
            else:
                authority = managers[0]
                if document and document["primary_version_file_id"] != authority["file_id"]:
                    issues.add("manager_version_mismatch")
            if len({code(row["file_category_code"]) for row in active}) > 1:
                issues.add("database_category_conflict")
        elif identity.startswith("file:") and len(current) == 1 and current[0]:
            authority = current[0]
        else:
            issues.add("identity_mismatch")
        source_rows = [*entries, *[row for row in current if row], *([document] if document else [])]
        if any(row.get("tenant_id") != tenant_id for row in source_rows):
            raise ValueError("数据库返回超出租户范围的来源")
        latest = {row["file_id"]: row for row in entries}
        for row in current:
            if (
                row
                and row["file_id"] in latest
                and any(
                    row.get(field) != latest[row["file_id"]].get(field)
                    for field in (
                        "knowledge_identity",
                        "file_category_code",
                        "entry_type",
                        "entry_status",
                        "active",
                        "desired_content_generation",
                        "desired_entry_generation",
                    )
                )
            ):
                issues.add("source_changed_during_audit")
        categories = {code(row.get("file_category_code")) for row in rows}
        if len(categories) > 1:
            issues.add("es_category_conflict")
            if "" in categories:
                issues.add("empty_and_nonempty_category")
        refresh = []
        for observed, source in zip(rows, current, strict=True):
            if not source:
                continue
            expected_code = code(source["file_category_code"])
            expected_name = labels.get(expected_code, expected_code) if expected_code else ""
            if (observed.get("file_category_code") or "") != expected_code or (
                observed.get("file_category_name") or ""
            ) != expected_name:
                issues.add("es_projection_drift")
                refresh.append(int(observed["file_id"]))
        if not issues:
            continue
        relevant_codes = {code(row.get("file_category_code")) for row in [*entries, *rows]}
        basis = {
            "document": document,
            "entries": entries,
            "current_files": current,
            "labels": {key: labels[key] for key in relevant_codes if key in labels},
        }
        unsafe = issues - {"es_category_conflict", "empty_and_nonempty_category", "es_projection_drift"}
        resolved = authority is not None and not unsafe
        problems.append(
            {
                "knowledge_identity": identity,
                "issues": sorted(issues),
                "es_records": rows,
                "source": basis,
                "source_resolved": resolved,
                "expected_category_code": code(authority["file_category_code"]) if resolved else None,
                "proposed_refresh_file_ids": sorted(set(refresh)) if resolved else [],
                "source_fingerprint": hashlib.sha256(
                    json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
        )
        counts.update(issues)
    return {
        "tenant_id": tenant_id,
        "read_only": True,
        "scanned_files": len(records),
        "scanned_documents": len(groups),
        "problem_documents": len(problems),
        "issue_counts": dict(counts),
        "problems": problems,
    }


async def read_projection_rows(client: Any, filters: list[dict], limit: int) -> tuple[list[dict], bool]:
    from bisheng.telemetry_search.domain.services.knowledge_document_reader import DocumentReader

    query = {"bool": {"filter": [*filters, {"term": {"record_type": "file"}}, {"term": {"file_type": 1}}]}}
    rows = []
    async for page in DocumentReader(client, INDEX).buckets(
        query,
        "file_id",
        {"record": {"top_hits": {"size": 2, "_source": FIELDS}}},
    ):
        for bucket in page:
            hits = bucket["record"]["hits"]["hits"]
            if bucket["doc_count"] != 1 or len(hits) != 1:
                raise ValueError("同一文件存在重复统计投影, 请先核对索引别名")
            if len(rows) == limit:
                return rows, True
            source = {field: hits[0]["_source"].get(field) for field in FIELDS}
            source.update(es_id=hits[0].get("_id"), es_index=hits[0].get("_index", INDEX))
            rows.append(source)
    return rows, False


async def run_audit(args: argparse.Namespace) -> dict:
    from bisheng.core.context.tenant import (
        current_tenant_id,
        get_current_tenant_id,
        set_current_tenant_id,
        strict_tenant_filter,
    )
    from bisheng.core.search.elasticsearch.manager import get_es_connection
    from bisheng.knowledge.domain.services.file_classification_label_service import FileClassificationLabelService
    from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
        KnowledgeStatisticsRepositoryImpl,
    )

    token = set_current_tenant_id(args.tenant_id)
    try:
        if get_current_tenant_id() != args.tenant_id:
            raise ValueError("当前管理范围与审计租户不一致")
        with strict_tenant_filter():
            filters = [{"term": {"tenant_id": args.tenant_id}}]
            if args.space_id:
                filters.append({"terms": {"space_id": args.space_id}})
            else:
                filters.append({"terms": {"knowledge_identity": [f"document:{value}" for value in args.document_id]}})
            records, truncated = await read_projection_rows(await get_es_connection(), filters, args.limit)
            for row in records:
                if row.get("tenant_id") != args.tenant_id:
                    raise ValueError("索引返回超出租户范围的记录")
                if args.space_id and int(row["space_id"]) not in args.space_id:
                    raise ValueError("索引返回超出知识库范围的记录")
                if args.document_id and row["knowledge_identity"] not in {f"document:{i}" for i in args.document_id}:
                    raise ValueError("索引返回超出文档范围的记录")
            sources = {"files": {}, "documents": {}, "entries": {}}
            for offset in range(0, len(records), args.batch_size):
                batch = records[offset : offset + args.batch_size]
                documents = sorted(
                    {
                        int(row["knowledge_identity"][9:])
                        for row in batch
                        if str(row.get("knowledge_identity") or "").startswith("document:")
                        and row["knowledge_identity"][9:].isdigit()
                    }
                )
                loaded = await asyncio.to_thread(
                    KnowledgeStatisticsRepositoryImpl.category_audit_sources,
                    [int(row["file_id"]) for row in batch],
                    documents,
                )
                for kind in sources:
                    sources[kind].update(loaded[kind])
            labels, _ = await asyncio.to_thread(
                FileClassificationLabelService.get_label_lookup_for_tenant, args.tenant_id
            )
            report = build_report(records, sources, labels, args.tenant_id)
            report.update(truncated=truncated, scope={"space_ids": args.space_id, "document_ids": args.document_id})
            return report
    finally:
        current_tenant_id.reset(token)


async def execute(args: argparse.Namespace) -> dict:
    from bisheng.core.context.manager import close_app_context

    try:
        return await run_audit(args)
    finally:
        await close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = asyncio.run(execute(args))
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload + "\n")
            print(
                json.dumps(
                    {"report": str(args.output), "problem_documents": report["problem_documents"]}, ensure_ascii=False
                )
            )
        else:
            print(payload)
        return 0
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "只读审计失败, 未生成修复结果"
        print(json.dumps({"error_type": type(error).__name__, "message": message}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
