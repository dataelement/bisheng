"""补齐看板当前文件快照缺失的原始上传库及四级组织, 不修改数据库或历史事件。

在后端根目录执行, 默认只读:
  python scripts/backfill_dashboard_original_organizations.py --tenant-id 1 --output /tmp/origin-plan.json
审核计划后写入:
  python scripts/backfill_dashboard_original_organizations.py --plan /tmp/origin-plan.json --apply --output /tmp/origin-write.jsonl
回退前先预览, 确认后加 --apply:
  python scripts/backfill_dashboard_original_organizations.py --rollback /tmp/origin-write.jsonl --output /tmp/origin-rollback.jsonl
所有输出必须是新文件; 写入日志逐条 fsync, 发生冲突立即停止, 可用已生成日志回退。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

FIELDS = (
    "original_space_name",
    "original_upload_company_name",
    "original_upload_department_name",
    "original_upload_office_name",
    "original_upload_squad_name",
)
ANCHORS = ("record_type", "tenant_id", "file_id", "space_id", "knowledge_identity")
SCHEMA = "dashboard-original-v1"


def secure_open(path: Path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8")


def dump_line(stream, value: dict) -> None:
    stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    stream.flush()
    if hasattr(stream, "fileno"):
        try:
            descriptor = stream.fileno()
        except OSError:
            return
        os.fsync(descriptor)


def signature(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def candidate(hit: dict, desired: dict | None, tenant: int, spaces: list[int]) -> tuple[dict | None, str]:
    old = hit["_source"]
    if old.get("record_type") != "file" or old.get("tenant_id") != tenant:
        return None, "scope_mismatch"
    if spaces and old.get("space_id") not in spaces:
        return None, "scope_mismatch"
    if desired is None:
        return None, "source_missing"
    if any(old.get(key) != desired.get(key) for key in ANCHORS) or str(old.get("file_id")) != hit["_id"]:
        return None, "identity_mismatch"
    if blank(desired.get("original_space_name")):
        return None, "unresolved"
    if any(not blank(old.get(key)) and old.get(key) != desired.get(key) for key in FIELDS):
        return None, "existing_conflict"
    patch = {key: desired[key] for key in FIELDS if blank(old.get(key)) and not blank(desired.get(key))}
    if not patch:
        return None, "unresolved" if all(blank(desired.get(key)) for key in FIELDS) else "unchanged"
    return {
        "id": hit["_id"],
        "anchors": {key: old.get(key) for key in ANCHORS},
        "before": {key: {"present": key in old, "value": old.get(key)} for key in FIELDS},
        "patch": patch,
        "origin_id": desired["_origin_id"],
        "fallback": desired["_fallback"],
    }, "candidate"


def checked_hit(es, index: str, key: str) -> dict:
    result = dict(es.get(index=index, id=key))
    if not isinstance(result.get("_source"), dict) or any(k not in result for k in ("_seq_no", "_primary_term")):
        raise RuntimeError(f"incomplete ES read id={key}")
    return result


def validate_entry(entry: dict) -> None:
    if (
        not entry["patch"]
        or not set(entry["patch"]).issubset(FIELDS)
        or set(entry["before"]) != set(FIELDS)
        or set(entry["anchors"]) != set(ANCHORS)
        or entry["anchors"].get("record_type") != "file"
        or str(entry["anchors"].get("file_id")) != entry["id"]
    ):
        raise RuntimeError("invalid candidate fields or identity")


def apply_one(es, index: str, entry: dict, desired: dict, tenant: int, spaces: list[int], journal) -> None:
    validate_entry(entry)
    current = checked_hit(es, index, entry["id"])
    fresh, _ = candidate(current, desired, tenant, spaces)
    if fresh != entry:
        raise RuntimeError(f"source or ES drift id={entry['id']}")
    dump_line(journal, {"kind": "intent", "entry": entry})
    es.update(
        index=index,
        id=entry["id"],
        doc=entry["patch"],
        if_seq_no=current["_seq_no"],
        if_primary_term=current["_primary_term"],
        refresh=False,
    )
    actual = checked_hit(es, index, entry["id"])["_source"]
    if any(actual.get(k) != v for k, v in {**entry["anchors"], **entry["patch"]}.items()):
        raise RuntimeError(f"readback mismatch id={entry['id']}")
    dump_line(journal, {"kind": "verified", "id": entry["id"]})


def rollback_one(es, index: str, entry: dict, tenant: int, journal, *, apply: bool) -> str:
    validate_entry(entry)
    current = checked_hit(es, index, entry["id"])
    old = current["_source"]
    if entry["anchors"].get("tenant_id") != tenant or any(old.get(k) != v for k, v in entry["anchors"].items()):
        raise RuntimeError(f"rollback identity mismatch id={entry['id']}")
    before = {key: entry["before"][key] for key in entry["patch"]}
    restored = all((key in old) == v["present"] and old.get(key) == v["value"] for key, v in before.items())
    if restored:
        return "already_restored"
    if any(old.get(k) != v for k, v in entry["patch"].items()):
        raise RuntimeError(f"rollback drift id={entry['id']}")
    dump_line(journal, {"kind": "rollback_intent", "entry": entry})
    if not apply:
        return "would_restore"
    es.update(
        index=index,
        id=entry["id"],
        if_seq_no=current["_seq_no"],
        if_primary_term=current["_primary_term"],
        refresh=False,
        script={
            "lang": "painless",
            "params": {"before": before},
            "source": "for (def e : params.before.entrySet()) { if (e.getValue().present) { "
            "ctx._source[e.getKey()] = e.getValue().value; } else { ctx._source.remove(e.getKey()); } }",
        },
    )
    actual = checked_hit(es, index, entry["id"])["_source"]
    if not all((k in actual) == v["present"] and actual.get(k) == v["value"] for k, v in before.items()):
        raise RuntimeError(f"rollback readback mismatch id={entry['id']}")
    dump_line(journal, {"kind": "rollback_verified", "id": entry["id"]})
    return "restored"


def load_journal(path: Path) -> list[dict]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [row["entry"] for row in lines if row.get("kind") == "intent"]


def sources(file_ids: list[int], tenant: int) -> dict[int, dict]:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.worker.telemetry.mid_table import (
        _build_knowledge_space_content_records,
        _get_knowledge_space_content_rows_by_file_ids,
        _is_file_content_stat_visible,
    )

    with bypass_tenant_filter():
        rows = _get_knowledge_space_content_rows_by_file_ids(file_ids)
        rows = [
            (f, s)
            for f, s in rows
            if f.tenant_id == tenant and s.tenant_id == tenant and _is_file_content_stat_visible(f, s)
        ]
        records, _ = _build_knowledge_space_content_records(rows, {})
    origins = {int(f.id): (int(f.original_knowledge_id or s.id), not bool(f.original_knowledge_id)) for f, s in rows}
    return {
        int(r.file_id): {**r.model_dump(), "_origin_id": origins[r.file_id][0], "_fallback": origins[r.file_id][1]}
        for r in records
    }


def validate_page(response: dict) -> None:
    if response.get("timed_out") or response.get("terminated_early") or response.get("_shards", {}).get("failed", 0):
        raise RuntimeError("incomplete ES scan")
    if "hits" not in response or "hits" not in response["hits"]:
        raise RuntimeError("missing ES scan hits")


def scan(es, index: str, tenant: int, spaces: list[int], batch: int):
    filters = [{"term": {"record_type": "file"}}, {"term": {"tenant_id": tenant}}]
    if spaces:
        filters.append({"terms": {"space_id": spaces}})
    cursor = None
    try:
        page = es.search(
            index=index,
            query={"bool": {"filter": filters}},
            size=batch,
            scroll="5m",
            sort=["_doc"],
            source=list(ANCHORS + FIELDS),
        )
        while True:
            cursor = page.get("_scroll_id", cursor)
            validate_page(page)
            rows = page["hits"]["hits"]
            if not rows:
                break
            if not cursor:
                raise RuntimeError("missing scroll cursor")
            yield rows
            page = es.scroll(scroll_id=cursor, scroll="5m")
    finally:
        if cursor:
            es.clear_scroll(scroll_id=cursor)


def binding(es, index: str) -> dict:
    settings = dict(es.indices.get_settings(index=index))
    if set(settings) != {index}:
        raise RuntimeError("target must be one concrete statistics index")
    mappings = es.indices.get_mapping(index=index)[index]["mappings"]["properties"]
    if any(mappings.get(key, {}).get("type") != "keyword" for key in FIELDS):
        raise RuntimeError("required keyword mappings absent; deploy original dimensions first")
    return {"index": index, "uuid": settings[index]["settings"]["index"]["uuid"]}


def positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", type=Path)
    mode.add_argument("--rollback", type=Path)
    parser.add_argument("--tenant-id", type=positive)
    parser.add_argument("--space-id", type=positive, action="append", default=[])
    parser.add_argument("--batch-size", type=positive, default=200)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.batch_size > 400:
        parser.error("输出文件必须不存在, batch-size 上限400")
    if (args.plan or args.rollback) and (args.tenant_id or args.space_id):
        parser.error("执行及回退从原计划读取范围, 不允许改范围")
    if not (args.plan or args.rollback) and (not args.tenant_id or args.apply):
        parser.error("预览必须指定 --tenant-id; 写入必须使用 --plan --apply")
    if args.plan and not args.apply:
        parser.error("执行计划需要 --apply")

    from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
    from bisheng.core.search.elasticsearch.manager import get_es_connection_sync

    es = get_es_connection_sync()
    target = binding(es, KNOWLEDGE_SPACE_CONTENT_STAT_INDEX)
    index = target["index"]
    if not (args.plan or args.rollback):
        counts, candidates, samples = Counter(), [], []
        for hits in scan(es, index, args.tenant_id, args.space_id, args.batch_size):
            desired = sources([int(h["_source"]["file_id"]) for h in hits], args.tenant_id)
            counts["scanned"] += len(hits)
            counts["legacy_fallback"] += sum(int(row["_fallback"]) for row in desired.values())
            for hit in hits:
                entry, reason = candidate(
                    hit, desired.get(int(hit["_source"]["file_id"])), args.tenant_id, args.space_id
                )
                counts[reason] += 1
                if entry:
                    candidates.append(entry)
                    counts["fallback_candidates"] += int(entry["fallback"])
                    for field in entry["patch"]:
                        counts[field] += 1
                elif reason != "unchanged" and len(samples) < 30:
                    samples.append({"id": hit["_id"], "reason": reason})
        report = {
            "schema": SCHEMA,
            "target": target,
            "tenant": args.tenant_id,
            "spaces": args.space_id,
            "counts": dict(counts),
            "skipped_samples": samples,
            "candidates": candidates,
        }
        report["digest"] = signature(report)
        with secure_open(args.output) as stream:
            dump_line(stream, report)
        print(json.dumps({k: v for k, v in report.items() if k != "candidates"}, ensure_ascii=False))
        return 0

    if args.plan:
        plan = json.loads(args.plan.read_text())
        digest = plan.pop("digest")
        if signature(plan) != digest or plan["schema"] != SCHEMA or plan["target"] != target:
            raise RuntimeError("plan digest/schema/index drift")
        entries, tenant, spaces = plan["candidates"], plan["tenant"], plan["spaces"]
    else:
        header = json.loads(args.rollback.read_text().splitlines()[0])
        if header.get("kind") != "header" or header.get("schema") != SCHEMA or header.get("target") != target:
            raise RuntimeError("journal schema/index drift")
        entries, tenant, spaces = load_journal(args.rollback), header["tenant"], header["spaces"]
    counts = Counter()
    with secure_open(args.output) as journal:
        dump_line(journal, {"kind": "header", "schema": SCHEMA, "target": target, "tenant": tenant, "spaces": spaces})
        for offset in range(0, len(entries), args.batch_size):
            batch = entries[offset : offset + args.batch_size]
            desired = sources([int(e["id"]) for e in batch], tenant) if args.plan else {}
            for entry in batch:
                if args.plan:
                    apply_one(es, index, entry, desired.get(int(entry["id"])), tenant, spaces, journal)
                    counts["updated_verified"] += 1
                else:
                    counts[rollback_one(es, index, entry, tenant, journal, apply=args.apply)] += 1
        dump_line(journal, {"kind": "complete", "counts": dict(counts)})
    print(json.dumps({"counts": dict(counts), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
