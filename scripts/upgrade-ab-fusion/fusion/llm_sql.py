"""B 独有 llm_server / llm_model 在 A 新建, 并拷 config 里的密钥."""

from __future__ import annotations

from fusion.identity_sql import _map_row
from fusion.sql import (
    alloc_int_id,
    fusion_batch_open_sql,
    sql_bool,
    sql_int,
    sql_json,
    sql_str,
)
from fusion.tool_type_sql import unique_name


def generate_llm_sql(
    *,
    batch: str,
    servers: list[dict],
    models: list[dict],
    server_map: list[dict],
    model_map: list[dict],
    user_map: dict[str, str],
    tenant_map: dict[str, str],
    a_server_ids: set[int],
    a_model_ids: set[int],
    a_server_names: set[str],
    a_server_models: list[dict],
    next_server_id: int,
    next_model_id: int,
    a_tenant_default: str,
) -> tuple[str, dict]:
    """返回 (sql, extra). extra 含 server_alloc / model_alloc 供后序域重写引用."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} llm_server/llm_model B->A (copy config secrets)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "llm"),
    ]
    servers_by_id = {str(row.get("id") or ""): row for row in servers}
    models_by_id = {str(row.get("id") or ""): row for row in models}
    existing_pair: dict[tuple[str, str], str] = {}
    for row in a_server_models:
        sid = str(row.get("server_id") or "")
        name = (row.get("model_name") or "").strip()
        mid = str(row.get("id") or "")
        if sid and name and mid:
            existing_pair.setdefault((sid, name), mid)

    taken_servers = set(a_server_ids)
    taken_models = set(a_model_ids)
    names = set(a_server_names)
    nxt_s = next_server_id
    nxt_m = next_model_id
    server_alloc: dict[str, str] = {}
    model_alloc: dict[str, str] = {}

    for row in server_map:
        src = (row.get("b_server_id") or "").strip()
        if not src:
            continue
        action = (row.get("action") or "").strip()
        if action == "bind":
            dst = (row.get("a_server_id") or "").strip()
            if not dst:
                continue
            server_alloc[src] = dst
            lines.append(_map_row(batch, "llm_server", src, dst, "bind", row.get("note") or ""))
            continue
        if action != "create":
            continue
        src_row = servers_by_id.get(src) or {}
        existing = (row.get("a_server_id") or "").strip()
        if existing and existing.isdigit():
            dst = existing
            taken_servers.add(int(dst))
            nxt_s = max(nxt_s, int(dst) + 1)
        else:
            dst = str(alloc_int_id(nxt_s, taken_servers))
            nxt_s = int(dst) + 1
        server_alloc[src] = dst
        name = unique_name(src_row.get("name") or f"llm-server-{src}", names)
        names.add(name)
        owner = user_map.get(str(src_row.get("user_id") or "")) or "0"
        tenant = tenant_map.get(str(src_row.get("tenant_id") or "1"), a_tenant_default)
        lines.append(
            "INSERT INTO llm_server (id, name, description, type, limit_flag, `limit`, "
            "config, user_id, tenant_id) VALUES ("
            f"{sql_int(dst)}, {sql_str(name)}, {sql_str(src_row.get('description') or '')}, "
            f"{sql_str(src_row.get('type') or '')}, "
            f"{sql_bool(src_row.get('limit_flag'))}, {sql_int(src_row.get('limit') or 0, '0')}, "
            f"{sql_json(src_row.get('config'))}, {sql_int(owner, '0')}, {sql_int(tenant)});"
        )
        lines.append(_map_row(batch, "llm_server", src, dst, "create", f"name={name};config_copied"))

    for row in model_map:
        src = (row.get("b_model_id") or "").strip()
        if not src:
            continue
        action = (row.get("action") or "").strip()
        if action == "bind":
            dst = (row.get("a_model_id") or "").strip()
            if not dst:
                continue
            model_alloc[src] = dst
            lines.append(_map_row(batch, "llm_model", src, dst, "bind", row.get("note") or ""))
            continue
        if action != "create":
            continue
        src_row = models_by_id.get(src) or {}
        b_server = str(src_row.get("server_id") or "")
        dst_server = server_alloc.get(b_server) or ""
        if not dst_server:
            raise ValueError(f"llm_model {src} 所属 server {b_server} 未映射")
        model_name = (src_row.get("model_name") or src_row.get("name") or f"model-{src}").strip()
        existed = existing_pair.get((dst_server, model_name))
        if existed:
            model_alloc[src] = existed
            lines.append(
                _map_row(
                    batch,
                    "llm_model",
                    src,
                    existed,
                    "bind",
                    f"server_id+model_name 已在 A, 复用 {existed}",
                )
            )
            continue
        existing = (row.get("a_model_id") or "").strip()
        if existing and existing.isdigit():
            dst = existing
            taken_models.add(int(dst))
            nxt_m = max(nxt_m, int(dst) + 1)
        else:
            dst = str(alloc_int_id(nxt_m, taken_models))
            nxt_m = int(dst) + 1
        model_alloc[src] = dst
        existing_pair[(dst_server, model_name)] = dst
        owner = user_map.get(str(src_row.get("user_id") or "")) or "0"
        tenant = tenant_map.get(str(src_row.get("tenant_id") or "1"), a_tenant_default)
        display = src_row.get("name") or model_name
        lines.append(
            "INSERT INTO llm_model (id, server_id, name, description, model_name, model_type, "
            "config, status, remark, online, user_id, tenant_id) VALUES ("
            f"{sql_int(dst)}, {sql_int(dst_server)}, {sql_str(display)}, "
            f"{sql_str(src_row.get('description') or '')}, {sql_str(model_name)}, "
            f"{sql_str(src_row.get('model_type') or '')}, {sql_json(src_row.get('config'))}, "
            f"{sql_int(src_row.get('status') or 2, '2')}, {sql_str(src_row.get('remark') or '')}, "
            f"{sql_bool(src_row.get('online') if src_row.get('online') is not None else True)}, "
            f"{sql_int(owner, '0')}, {sql_int(tenant)});"
        )
        lines.append(_map_row(batch, "llm_model", src, dst, "create", "config_copied"))

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", {
        "server_alloc": server_alloc,
        "model_alloc": model_alloc,
    }
