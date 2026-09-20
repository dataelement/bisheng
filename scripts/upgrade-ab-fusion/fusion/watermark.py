"""表级水位: 全量开始 / 冻结 / 当前. 前开后闭, 冻结后 B 再写则作废."""

from __future__ import annotations

from pathlib import Path

from fusion.sql import load_table, write_csv

# entity 与 fusion_map / 映射 csv 对齐
WATERMARK_TABLES = (
    ("knowledge", "knowledge"),
    ("knowledgefile", "file"),
    ("qaknowledge", "qa"),
    ("flow", "flow"),
    ("flowversion", "flowversion"),
    ("assistant", "assistant"),
    ("message_session", "chat"),
    ("chatmessage", "message"),
    ("review_tag", "review_tag"),
    ("review_tag_link", "review_tag_link"),
    ("groupresource", "group_resource"),
    ("t_report", "report"),
    ("roleaccess", "role_access"),
    ("auditlog", "audit"),
)

PK_COLUMN = {
    "message_session": "chat_id",
}
WHERE_SQL = {
    "knowledge": "type IN (0,1)",
}
TS_EXPR = "UNIX_TIMESTAMP(COALESCE(update_time, create_time, FROM_UNIXTIME(0)))"

SUMMARY_FIELDS = ["table", "entity", "count", "max_id", "max_update_ts"]
ID_FIELDS = ["id", "update_ts"]
DIFF_FIELDS = ["entity", "src_id", "change"]


def load_id_snapshot(path: Path) -> dict[str, int]:
    """id -> update_ts (unix 秒, 无则 0)."""
    out: dict[str, int] = {}
    if not path.exists():
        return out
    for row in load_table(path):
        src = (row.get("id") or "").strip()
        if not src:
            continue
        try:
            out[src] = int(row.get("update_ts") or 0)
        except ValueError:
            out[src] = 0
    return out


def load_summary(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for row in load_table(path):
        name = (row.get("table") or "").strip()
        if name:
            out[name] = row
    return out


def diff_snapshot(
    start_ids: dict[str, int], freeze_ids: dict[str, int]
) -> dict[str, list[str]]:
    """created / deleted / updated. updated = 仍在且 update_ts 变大 (前开后闭)."""
    start_keys = set(start_ids)
    freeze_keys = set(freeze_ids)
    created = sorted(freeze_keys - start_keys)
    deleted = sorted(start_keys - freeze_keys)
    updated = sorted(
        src
        for src in (start_keys & freeze_keys)
        if freeze_ids.get(src, 0) > start_ids.get(src, 0)
    )
    return {"created": created, "deleted": deleted, "updated": updated}


def table_pk(table: str) -> str:
    return PK_COLUMN.get(table, "id")


def id_select_sql(table: str) -> str:
    pk = table_pk(table)
    where = WHERE_SQL.get(table)
    clause = f" WHERE {where}" if where else ""
    return f"SELECT {pk} AS id, {TS_EXPR} AS update_ts FROM `{table}`{clause}"


def summary_select_sql(table: str, entity: str) -> str:
    pk = table_pk(table)
    where = WHERE_SQL.get(table)
    clause = f" WHERE {where}" if where else ""
    max_ts = "UNIX_TIMESTAMP(MAX(COALESCE(update_time, create_time, FROM_UNIXTIME(0))))"
    return (
        f"SELECT '{table}' AS `table`, '{entity}' AS entity, COUNT(*) AS count, "
        f"CAST(MAX({pk}) AS CHAR) AS max_id, {max_ts} AS max_update_ts "
        f"FROM `{table}`{clause}"
    )


def freeze_drift(
    freeze_summary: dict[str, dict], current_summary: dict[str, dict]
) -> list[str]:
    """冻结后 B 再写 (含删行) 则水位作废."""
    errors = []
    tables = set(freeze_summary) | set(current_summary)
    for table in sorted(tables):
        freeze = freeze_summary.get(table) or {}
        now = current_summary.get(table) or {}
        for key in ("count", "max_id", "max_update_ts"):
            a = str(freeze.get(key) or "")
            b = str(now.get(key) or "")
            if a != b:
                errors.append(f"{table}.{key} 冻结后 {a or '0'} -> {b or '0'}")
    return errors


def freeze_id_drift(
    freeze_ids: dict[str, int], current_ids: dict[str, int]
) -> list[str]:
    diff = diff_snapshot(freeze_ids, current_ids)
    errors = []
    for change, ids in diff.items():
        if ids:
            errors.append(f"{change} x{len(ids)}")
    return errors


def flatten_diff(entity: str, diff: dict[str, list[str]]) -> list[dict]:
    rows = []
    for change, ids in diff.items():
        for src in ids:
            rows.append({"entity": entity, "src_id": src, "change": change})
    return rows


def write_diff_tsv(path: Path, rows: list[dict]) -> None:
    write_csv(path, DIFF_FIELDS, rows, delimiter="\t")


def write_summary_tsv(path: Path, rows: list[dict]) -> None:
    write_csv(path, SUMMARY_FIELDS, rows, delimiter="\t")


def write_id_tsv(path: Path, rows: list[dict]) -> None:
    write_csv(path, ID_FIELDS, rows, delimiter="\t")
