"""系统字典: (tenant, type, dict_key) 已在 A 则 bind, 否则新建. 不改 A 已有值."""

from __future__ import annotations

from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_bool, sql_int, sql_str


def _norm_key(tenant: str, typ: str, key: str) -> tuple[str, str, str]:
    return (str(tenant), str(typ or ""), str(key or ""))


def generate_dictionary_sql(
    *,
    batch: str,
    b_rows: list[dict],
    a_rows: list[dict],
    tenant_map: dict[str, str],
    a_existing_ids: set[int],
    next_id: int,
    a_tenant_default: str,
    existing_dictionary: dict[str, str] | None = None,
) -> tuple[str, list[dict]]:
    """返回 (sql, dict_maps). maps 含 bind 与 create."""
    a_index: dict[tuple[str, str, str], str] = {}
    for row in a_rows:
        tenant = str(row.get("tenant_id") or a_tenant_default)
        key = _norm_key(tenant, row.get("type") or "", row.get("dict_key") or "")
        if key[1] and key[2]:
            a_index[key] = str(row.get("id") or "")
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} system_dictionary B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "dictionary"),
    ]
    taken = set(a_existing_ids)
    nxt = next_id
    out: list[dict] = []
    existing_dictionary = dict(existing_dictionary or {})
    for row in b_rows:
        src = str(row.get("id") or "")
        if src in existing_dictionary:
            out.append(
                {
                    "b_id": src,
                    "a_id": existing_dictionary[src],
                    "action": "create",
                }
            )
            continue
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        typ = str(row.get("type") or "")
        dkey = str(row.get("dict_key") or "")
        if not typ or not dkey:
            continue
        hit = a_index.get(_norm_key(tenant, typ, dkey))
        if hit:
            lines.append(
                "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
                f"{sql_str(batch)}, 'dictionary', {sql_str(src)}, {sql_str(hit)}, 'bind', "
                f"{sql_str(f'{typ}/{dkey}')});"
            )
            out.append({"b_id": src, "a_id": hit, "action": "bind"})
            continue
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        lines.append(
            "INSERT INTO system_dictionary (id, type, dict_key, dict_value, sort_order, "
            "is_enabled, tenant_id) VALUES ("
            f"{dst}, {sql_str(typ)}, {sql_str(dkey)}, {sql_str(row.get('dict_value') or '')}, "
            f"{sql_int(row.get('sort_order') or 0, '0')}, {sql_bool(row.get('is_enabled') if row.get('is_enabled') is not None else 1)}, "
            f"{sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'dictionary', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(f'{typ}/{dkey}')});"
        )
        out.append({"b_id": src, "a_id": str(dst), "action": "create"})
        a_index[_norm_key(tenant, typ, dkey)] = str(dst)
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out
