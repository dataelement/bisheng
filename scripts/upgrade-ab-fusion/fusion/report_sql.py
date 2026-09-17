"""工作流报表模板: 重写 flow_id; version_key 冲突换新; 不拷密钥."""

from __future__ import annotations

import uuid

from fusion.minio_keys import rewrite_stored_value
from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_str


def _unique_key(src: str | None, taken: set[str]) -> str:
    text = (src or "").strip()
    if text and text not in taken:
        taken.add(text)
        return text
    while True:
        cand = uuid.uuid4().hex
        if cand not in taken:
            taken.add(cand)
            return cand


def allocate_report_version_keys(
    reports: list[dict],
    a_version_keys: set[str],
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    """B version_key -> A. 不冲突则保留, 冲突换新. 供工作流 JSON 与 t_report 共用."""
    taken = set(a_version_keys)
    out = dict(existing or {})
    for dst in out.values():
        if dst:
            taken.add(dst)
    for row in reports:
        src = str(row.get("version_key") or "").strip()
        if not src or src in out:
            continue
        out[src] = _unique_key(src, taken)
    return out


def generate_report_sql(
    *,
    batch: str,
    reports: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[int],
    a_version_keys: set[str],
    next_id: int,
    a_tenant_default: str,
    version_key_map: dict[str, str] | None = None,
) -> tuple[str, list[dict]]:
    """返回 (sql, report_maps). flow 未映射则跳过."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} t_report B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "report"),
    ]
    flow_map = maps.get("flow") or {}
    tenant_map = maps.get("tenant") or {}
    taken = set(a_existing_ids)
    keys = set(a_version_keys)
    nxt = next_id
    out: list[dict] = []
    skipped = 0
    preexisting_report = dict(maps.get("report") or {})
    vk_map = dict(version_key_map or {})
    for row in reports:
        src = str(row.get("id") or "")
        if src in preexisting_report:
            out.append({"b_id": src, "a_id": preexisting_report[src], "extra_jobs": []})
            continue
        flow_dst = flow_map.get(str(row.get("flow_id") or ""))
        if not flow_dst:
            skipped += 1
            continue
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        src_vk = str(row.get("version_key") or "").strip()
        if src_vk and src_vk in vk_map:
            version_key = vk_map[src_vk]
            keys.add(version_key)
        else:
            version_key = _unique_key(row.get("version_key"), keys)
            if src_vk:
                vk_map[src_vk] = version_key
        newversion_key = row.get("newversion_key") or None
        if newversion_key:
            newversion_key = _unique_key(str(newversion_key), keys)
        obj_new, obj_jobs = rewrite_stored_value(
            row.get("object_name"), str(dst), ref=src, kind="object_name"
        )
        tpl_new, tpl_jobs = rewrite_stored_value(
            row.get("template_name"), str(dst), ref=src, kind="template_name"
        )
        extra_jobs = obj_jobs + tpl_jobs
        lines.append(
            "INSERT INTO t_report (id, flow_id, file_name, template_name, version_key, "
            "newversion_key, object_name, del_yn, tenant_id) VALUES ("
            f"{dst}, {sql_str(flow_dst)}, {sql_str(row.get('file_name') or None)}, "
            f"{sql_str(tpl_new if isinstance(tpl_new, str) else None)}, {sql_str(version_key)}, "
            f"{sql_str(newversion_key)}, "
            f"{sql_str(obj_new if isinstance(obj_new, str) else None)}, "
            f"{sql_int(row.get('del_yn') or 0, '0')}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'report', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(version_key)});"
        )
        out.append(
            {
                "b_id": src,
                "a_id": str(dst),
                "version_key": version_key,
                "b_version_key": src_vk,
                "extra_jobs": extra_jobs,
            }
        )
    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out
