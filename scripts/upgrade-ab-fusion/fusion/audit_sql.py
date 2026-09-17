"""审计日志: INSERT A `auditlog`. 重写操作者/租户/组/对象 ID. 不碰 A 原空间."""

from __future__ import annotations

import json
import uuid

from fusion.json_rewrite import rewrite_tree
from fusion.sql import fusion_batch_open_sql, sql_int, sql_json, sql_str

# object_type -> maps 键. 未列出的类型保留原 object_id (看板/频道等未迁资源).
OBJECT_TYPE_MAP = {
    "knowledge": "knowledge",
    "file": "file",
    "knowledge_file": "file",
    "work_flow": "flow",
    "workflow": "flow",
    "flow": "flow",
    "assistant": "assistant",
    "user_conf": "user",
    "user": "user",
    "user_group_conf": "group",
    "group": "group",
    "role_conf": "role",
    "role": "role",
    "tool": "tool",
    "qa": "qa",
    "tag": "review_tag",
    "session": "chat",
    "message": "message",
    "report": "report",
}

# 未映射则整行跳过: 对应对象根本没迁, 写进 A 会挂错资源.
STRICT_OBJECT_TYPES = frozenset(
    {
        "knowledge",
        "file",
        "knowledge_file",
        "work_flow",
        "workflow",
        "flow",
        "assistant",
        "knowledge_space",
    }
)

SKIP_OBJECT_TYPES = frozenset({"knowledge_space"})

TARGET_TYPE_MAP = {
    "tenant": "tenant",
    "user": "user",
    "department": "dept",
    "llm_server": "llm_server",
    "llm_model": "model",
}

# metadata 里常见操作者字段; rewrite_tree 已覆盖 knowledge_id/user_id/flow_id.
AUDIT_USER_META_KEYS = (
    "responsible_user_id",
    "from_user_id",
    "to_user_id",
    "operator_id",
)


class SkipRow(Exception):
    """本行不迁入 A."""


def _parse_json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip().startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _alloc_uuid(src: str, taken: set[str]) -> str:
    """B UUID 在 A 空闲则沿用; 冲突则换新 hex."""
    if src and src not in taken:
        taken.add(src)
        return src
    while True:
        nid = uuid.uuid4().hex
        if nid not in taken:
            taken.add(nid)
            return nid


def _in_space(dst: str | None, a_space_ids: set[int]) -> bool:
    if not dst or not a_space_ids:
        return False
    try:
        return int(dst) in a_space_ids
    except ValueError:
        return False


def _remap_groups(raw, group_map: dict[str, str]) -> list:
    data = _parse_json(raw)
    if data in (None, "", []):
        return []
    if not isinstance(data, list):
        data = [data]
    out = []
    for item in data:
        mapped = group_map.get(str(item))
        if not mapped:
            continue
        out.append(int(mapped) if str(mapped).isdigit() else mapped)
    return out


def _remap_object(
    object_type: str,
    object_id: str,
    maps: dict[str, dict[str, str]],
    a_space_ids: set[int],
) -> str | None:
    """返回目标 object_id; 需要跳过则抛 SkipRow."""
    otype = (object_type or "").strip()
    oid = str(object_id or "").strip()
    if otype in SKIP_OBJECT_TYPES:
        raise SkipRow("knowledge_space")
    if not oid or otype in {"", "none"}:
        return oid or None
    kind = OBJECT_TYPE_MAP.get(otype)
    if not kind:
        return oid
    dst = (maps.get(kind) or {}).get(oid)
    if not dst:
        if otype in STRICT_OBJECT_TYPES:
            raise SkipRow(f"unmapped {otype}")
        return oid
    if kind == "knowledge" and _in_space(dst, a_space_ids):
        raise SkipRow("a_space")
    return dst


def _remap_target(
    target_type: str,
    target_id: str,
    maps: dict[str, dict[str, str]],
    a_space_ids: set[int],
) -> str | None:
    ttype = (target_type or "").strip()
    tid = str(target_id or "").strip()
    if not tid:
        return None
    if ttype == "resource":
        for kind in ("knowledge", "file", "flow", "assistant"):
            dst = (maps.get(kind) or {}).get(tid)
            if dst:
                if kind == "knowledge" and _in_space(dst, a_space_ids):
                    raise SkipRow("a_space")
                return dst
        return tid
    kind = TARGET_TYPE_MAP.get(ttype)
    if not kind:
        return tid
    return (maps.get(kind) or {}).get(tid) or tid


def _rewrite_metadata(raw, maps: dict[str, dict[str, str]], a_space_ids: set[int]):
    data = _parse_json(raw)
    if not isinstance(data, (dict, list)):
        return data
    rewritten, report = rewrite_tree(data, maps)
    kmap = maps.get("knowledge") or {}
    for kind, src in report.used:
        if kind == "knowledge" and _in_space(kmap.get(src), a_space_ids):
            raise SkipRow("a_space_meta")
    umap = maps.get("user") or {}
    if isinstance(rewritten, dict):
        for key in AUDIT_USER_META_KEYS:
            if key not in rewritten or rewritten[key] in (None, ""):
                continue
            mapped = umap.get(str(rewritten[key]))
            if mapped:
                rewritten[key] = int(mapped) if str(mapped).isdigit() else mapped
    return rewritten


def generate_audit_sql(
    *,
    batch: str,
    rows: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[str],
    a_tenant_default: str,
    a_space_ids: set[int],
    existing_audit: dict[str, str] | None = None,
) -> tuple[str, list[dict]]:
    """返回 (sql, audit_maps). 操作者未映射 / 指向未迁空间则跳过."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} auditlog B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "audit"),
    ]
    user_map = maps.get("user") or {}
    tenant_map = maps.get("tenant") or {}
    group_map = maps.get("group") or {}
    taken = {str(x) for x in a_existing_ids}
    preexisting = dict(existing_audit or {})
    for dst in preexisting.values():
        if dst:
            taken.add(str(dst))
    out_maps: list[dict] = []
    skipped = {
        "operator": 0,
        "object": 0,
        "space": 0,
        "other": 0,
    }

    for row in rows:
        src = str(row.get("id") or "").strip()
        if not src:
            skipped["other"] += 1
            continue
        if src in preexisting:
            out_maps.append({"b_id": src, "a_id": preexisting[src]})
            continue
        op_src = str(
            row.get("operator_id") if row.get("operator_id") is not None else ""
        )
        if op_src in {"0"}:
            op_dst = "0"
        else:
            op_dst = user_map.get(op_src)
            if not op_dst:
                skipped["operator"] += 1
                continue
        try:
            object_id = _remap_object(
                str(row.get("object_type") or ""),
                str(row.get("object_id") or ""),
                maps,
                a_space_ids,
            )
            target_id = _remap_target(
                str(row.get("target_type") or ""),
                str(row.get("target_id") or ""),
                maps,
                a_space_ids,
            )
            metadata = _rewrite_metadata(row.get("metadata"), maps, a_space_ids)
        except SkipRow as exc:
            reason = str(exc)
            if reason == "knowledge_space" or reason.startswith("unmapped"):
                skipped["object"] += 1
            elif "space" in reason:
                skipped["space"] += 1
            else:
                skipped["other"] += 1
            continue

        tenant_raw = row.get("tenant_id")
        if tenant_raw in (None, ""):
            tenant_sql = "NULL"
        else:
            tenant_sql = sql_int(tenant_map.get(str(tenant_raw), a_tenant_default))
        op_tenant_raw = row.get("operator_tenant_id")
        if op_tenant_raw in (None, ""):
            op_tenant_sql = "NULL"
        else:
            op_tenant_sql = sql_int(
                tenant_map.get(str(op_tenant_raw), a_tenant_default)
            )

        dst = _alloc_uuid(src, taken)
        groups = _remap_groups(row.get("group_ids"), group_map)
        lines.append(
            "INSERT INTO auditlog (id, operator_id, operator_name, group_ids, system_id, "
            "event_type, object_type, object_id, object_name, note, ip_address, "
            "tenant_id, operator_tenant_id, action, target_type, target_id, reason, "
            "`metadata`, create_time, update_time) VALUES ("
            f"{sql_str(dst)}, {sql_int(op_dst)}, {sql_str(row.get('operator_name') or None)}, "
            f"{sql_json(groups)}, {sql_str(row.get('system_id') or None)}, "
            f"{sql_str(row.get('event_type') or None)}, {sql_str(row.get('object_type') or None)}, "
            f"{sql_str(object_id)}, {sql_str(row.get('object_name') or None)}, "
            f"{sql_str(row.get('note') or None)}, {sql_str(row.get('ip_address') or None)}, "
            f"{tenant_sql}, {op_tenant_sql}, {sql_str(row.get('action') or None)}, "
            f"{sql_str(row.get('target_type') or None)}, {sql_str(target_id)}, "
            f"{sql_str(row.get('reason') or None)}, {sql_json(metadata)}, "
            f"{sql_str(row.get('create_time') or None)}, {sql_str(row.get('update_time') or None)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'audit', {sql_str(src)}, {sql_str(dst)}, 'create', "
            f"{sql_str(str(row.get('event_type') or row.get('action') or ''))});"
        )
        out_maps.append({"b_id": src, "a_id": dst})

    lines.append(
        "-- skipped operator={operator} object={object} space={space} other={other}".format(
            **skipped
        )
    )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out_maps
