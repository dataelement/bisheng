"""B 独有工具分类和子工具在 A 新建, 并拷 api_key / extra / api_params."""

from __future__ import annotations

import json

from fusion import NAME_SUFFIX
from fusion.identity_sql import _map_row
from fusion.minio_keys import rewrite_stored_value
from fusion.propose_tool import unique_tool_key
from fusion.sql import (
    alloc_int_id,
    fusion_batch_open_sql,
    sql_int,
    sql_json,
    sql_str,
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


def extra_sql(raw) -> str:
    """原样保留 extra, 含密钥键. 空则 '{}'."""
    if raw in (None, ""):
        return sql_str("{}")
    if isinstance(raw, dict):
        return sql_str(json.dumps(raw, ensure_ascii=False))
    return sql_str(str(raw))


def generate_tool_type_sql(
    *,
    batch: str,
    rows: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[int],
    a_names: set[str],
    next_id: int,
    a_tenant_default: str,
    tools: list[dict] | None = None,
    tool_map: list[dict] | None = None,
    a_tool_ids: set[int] | None = None,
    a_tool_keys: set[str] | None = None,
    next_tool_id: int = 1,
) -> tuple[str, list[dict], dict]:
    """返回 (sql, type_maps, extra). extra 含 tool_alloc / tool_key_alloc. 拷密钥."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} t_gpts_tools_type + t_gpts_tools B->A (copy api_key/extra)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "tool_type"),
    ]
    user_map = maps.get("user") or {}
    tenant_map = maps.get("tenant") or {}
    taken = set(a_existing_ids)
    names = set(a_names)
    nxt = next_id
    out: list[dict] = []
    preexisting_tt = dict(maps.get("tool_type") or {})
    type_alloc: dict[str, str] = dict(preexisting_tt)
    for row in rows:
        src = str(row.get("id") or "")
        if not src:
            continue
        if src in preexisting_tt:
            out.append({"b_id": src, "a_id": preexisting_tt[src], "extra_jobs": []})
            continue
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        type_alloc[src] = str(dst)
        owner = user_map.get(str(row.get("user_id") or "")) or None
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        name = unique_name(row.get("name") or f"tool-type-{src}", names)
        names.add(name)
        logo_new, logo_jobs = rewrite_stored_value(row.get("logo"), str(dst), ref=src, kind="logo")
        lines.append(
            "INSERT INTO t_gpts_tools_type (id, name, logo, extra, description, server_host, "
            "auth_method, api_key, auth_type, is_preset, user_id, is_delete, is_shared, "
            "tenant_id, openapi_schema) VALUES ("
            f"{dst}, {sql_str(name)}, "
            f"{sql_str(logo_new if isinstance(logo_new, str) else (row.get('logo') or ''))}, "
            f"{extra_sql(row.get('extra'))}, {sql_str(row.get('description') or '')}, "
            f"{sql_str(row.get('server_host') or '')}, {sql_int(row.get('auth_method') or 0, '0')}, "
            f"{sql_str(row.get('api_key') or '')}, {sql_str(row.get('auth_type') or 'basic')}, "
            f"{sql_int(row.get('is_preset') or 1, '1')}, {sql_int(owner)}, "
            f"{sql_int(row.get('is_delete') or 0, '0')}, 0, {sql_int(tenant)}, "
            f"{sql_str(row.get('openapi_schema') or '')});"
        )
        lines.append(_map_row(batch, "tool_type", src, str(dst), "create", "api_key_copied"))
        out.append(
            {
                "b_id": src,
                "a_id": str(dst),
                "name": name,
                "extra_jobs": logo_jobs,
            }
        )

    tools_by_id = {str(row.get("id") or ""): row for row in (tools or [])}
    taken_tools = set(a_tool_ids or [])
    taken_keys = set(a_tool_keys or [])
    nxt_tool = next_tool_id
    tool_alloc: dict[str, str] = {}
    tool_key_alloc: dict[str, str] = {}
    minio_jobs: list[dict] = []
    preexisting_tool = dict(maps.get("tool") or {})

    for row in tool_map or []:
        src = (row.get("b_tool_id") or "").strip()
        if not src:
            continue
        action = (row.get("action") or "").strip()
        if action == "bind":
            dst = (row.get("a_tool_id") or preexisting_tool.get(src) or "").strip()
            if not dst:
                continue
            tool_alloc[src] = dst
            lines.append(_map_row(batch, "tool", src, dst, "bind", row.get("note") or ""))
            continue
        if action != "create":
            continue
        src_row = tools_by_id.get(src) or {}
        existing = (row.get("a_tool_id") or "").strip()
        if existing and existing.isdigit():
            dst = int(existing)
            taken_tools.add(dst)
            nxt_tool = max(nxt_tool, dst + 1)
        else:
            dst = alloc_int_id(nxt_tool, taken_tools)
            nxt_tool = dst + 1
        tool_alloc[src] = str(dst)
        owner = user_map.get(str(src_row.get("user_id") or "")) or None
        tenant = tenant_map.get(str(src_row.get("tenant_id") or "1"), a_tenant_default)
        b_type = str(src_row.get("type") or "0")
        if b_type in {"", "0"}:
            dst_type = 0
        else:
            mapped_type = type_alloc.get(b_type) or maps.get("tool_type", {}).get(b_type)
            dst_type = int(mapped_type) if mapped_type else 0
        proposed_key = (row.get("a_tool_key") or src_row.get("tool_key") or "").strip()
        a_key = unique_tool_key(proposed_key, taken_keys, src)
        taken_keys.add(a_key)
        b_key = (row.get("b_tool_key") or src_row.get("tool_key") or "").strip()
        if b_key and a_key != b_key:
            tool_key_alloc[b_key] = a_key
        logo_new, logo_jobs = rewrite_stored_value(src_row.get("logo"), str(dst), ref=src, kind="logo")
        name = src_row.get("name") or f"tool-{src}"
        lines.append(
            "INSERT INTO t_gpts_tools (id, name, logo, `desc`, tool_key, type, is_preset, "
            "is_delete, extra, api_params, user_id, tenant_id) VALUES ("
            f"{dst}, {sql_str(name)}, "
            f"{sql_str(logo_new if isinstance(logo_new, str) else (src_row.get('logo') or ''))}, "
            f"{sql_str(src_row.get('desc') or '')}, {sql_str(a_key)}, {sql_int(dst_type, '0')}, "
            f"{sql_int(src_row.get('is_preset') or 1, '1')}, "
            f"{sql_int(src_row.get('is_delete') or 0, '0')}, {extra_sql(src_row.get('extra'))}, "
            f"{sql_json(src_row.get('api_params'))}, {sql_int(owner)}, {sql_int(tenant)});"
        )
        lines.append(_map_row(batch, "tool", src, str(dst), "create", f"tool_key={a_key};extra_copied"))
        if logo_jobs:
            minio_jobs.extend(logo_jobs)

    lines.append("COMMIT;")
    return (
        "\n".join(lines) + "\n",
        out,
        {
            "gaps": [],
            "tool_alloc": tool_alloc,
            "tool_key_alloc": tool_key_alloc,
            "minio_jobs": minio_jobs,
        },
    )
