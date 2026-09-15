"""B 独有工具分类在 A 新建. 禁止拷 api_key, 不自动建 t_gpts_tools 子工具."""

from __future__ import annotations

import json

from fusion import NAME_SUFFIX
from fusion.minio_keys import rewrite_stored_value
from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_str

SECRET_KEYS = frozenset(
    {"access_key", "api_key", "apikey", "password", "secret", "token"}
)


def unique_name(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    candidate = f"{name}{NAME_SUFFIX}"
    n = 1
    while candidate in existing:
        n += 1
        candidate = f"{name}{NAME_SUFFIX}{n}"
    return candidate


def redact_extra(raw) -> str:
    """去掉 extra JSON 里像密钥的键. 非 JSON 原样保留."""
    if raw in (None, ""):
        return "{}"
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        obj = json.loads(text) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return text
    if not isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False)
    out = {k: v for k, v in obj.items() if str(k).lower() not in SECRET_KEYS}
    return json.dumps(out, ensure_ascii=False)


def generate_tool_type_sql(
    *,
    batch: str,
    rows: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[int],
    a_names: set[str],
    next_id: int,
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, type_maps, secret_gaps). 不 INSERT t_gpts_tools."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} t_gpts_tools_type B->A (no api_key, no children)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "tool_type"),
    ]
    user_map = maps.get("user") or {}
    tenant_map = maps.get("tenant") or {}
    taken = set(a_existing_ids)
    names = set(a_names)
    nxt = next_id
    out: list[dict] = []
    gaps: list[dict] = []
    preexisting_tt = dict(maps.get("tool_type") or {})
    for row in rows:
        src = str(row.get("id") or "")
        if not src:
            continue
        if src in preexisting_tt:
            out.append({"b_id": src, "a_id": preexisting_tt[src], "extra_jobs": []})
            continue
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        owner = user_map.get(str(row.get("user_id") or "")) or None
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        name = unique_name(row.get("name") or f"tool-type-{src}", names)
        names.add(name)
        logo_new, logo_jobs = rewrite_stored_value(
            row.get("logo"), str(dst), ref=src, kind="logo"
        )
        had_key = bool(str(row.get("api_key") or "").strip())
        extra = redact_extra(row.get("extra"))
        note = "api_key_cleared" if had_key else "create"
        if had_key:
            gaps.append(
                {
                    "kind": "tool_type",
                    "b_id": src,
                    "a_id": str(dst),
                    "name": name,
                    "reason": "api_key 未拷贝, 须在 A 重配",
                }
            )
        lines.append(
            "INSERT INTO t_gpts_tools_type (id, name, logo, extra, description, server_host, "
            "auth_method, api_key, auth_type, is_preset, user_id, is_delete, is_shared, "
            "tenant_id, openapi_schema) VALUES ("
            f"{dst}, {sql_str(name)}, "
            f"{sql_str(logo_new if isinstance(logo_new, str) else (row.get('logo') or ''))}, "
            f"{sql_str(extra)}, {sql_str(row.get('description') or '')}, "
            f"{sql_str(row.get('server_host') or '')}, {sql_int(row.get('auth_method') or 0, '0')}, "
            f"'', {sql_str(row.get('auth_type') or 'basic')}, "
            f"{sql_int(row.get('is_preset') or 1, '1')}, {sql_int(owner)}, "
            f"{sql_int(row.get('is_delete') or 0, '0')}, 0, {sql_int(tenant)}, "
            f"{sql_str(row.get('openapi_schema') or '')});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'tool_type', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(note)});"
        )
        out.append(
            {
                "b_id": src,
                "a_id": str(dst),
                "name": name,
                "extra_jobs": logo_jobs,
            }
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out, gaps
