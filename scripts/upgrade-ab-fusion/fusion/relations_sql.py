"""收藏/置顶/分享. 分享链接在 A 重新生成 UUID, 不复制密钥."""

from __future__ import annotations

import uuid

from fusion.sql import fusion_batch_open_sql, sql_int, sql_str


def remap_type_detail(
    link_type: str, detail: str, maps: dict[str, dict[str, str]]
) -> str | None:
    if not detail:
        return None
    for entity in ("knowledge", "flow", "assistant", "file", "chat"):
        table = maps.get(entity) or {}
        if detail in table:
            return table[detail]
    return None


def generate_relations_sql(
    *,
    batch: str,
    user_links: list[dict],
    share_links: list[dict],
    maps: dict[str, dict[str, str]],
    a_tenant_default: str,
) -> tuple[str, list[dict]]:
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} relations B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "relations"),
    ]
    skipped = 0
    preexisting_share = dict(maps.get("share_link") or {})
    share_maps: list[dict] = []
    for ul in user_links:
        user = (maps.get("user") or {}).get(str(ul.get("user_id") or ""))
        if not user:
            skipped += 1
            continue
        detail = remap_type_detail(
            ul.get("type") or "", str(ul.get("type_detail") or ""), maps
        )
        if not detail:
            skipped += 1
            lines.append(
                f"-- skip user_link type={ul.get('type')} detail={ul.get('type_detail')} 未映射"
            )
            continue
        lines.append(
            "INSERT IGNORE INTO user_link (user_id, type, type_detail) VALUES ("
            f"{sql_int(user)}, {sql_str(ul.get('type') or '')}, {sql_str(detail)});"
        )

    for sl in share_links:
        src = str(sl.get("id") or "")
        if src in preexisting_share:
            share_maps.append({"b_id": src, "a_id": preexisting_share[src]})
            continue
        new_id = uuid.uuid4().hex
        new_token = uuid.uuid4().hex
        user = (maps.get("user") or {}).get(
            str(sl.get("create_user_id") or sl.get("user_id") or "")
        )
        res = str(sl.get("resource_id") or "")
        rtype = sl.get("resource_type") or ""
        mapped_res = None
        for entity in ("flow", "assistant", "knowledge", "file", "chat"):
            if res in (maps.get(entity) or {}):
                mapped_res = maps[entity][res]
                break
        if not mapped_res or not user:
            skipped += 1
            lines.append(f"-- skip share_link {src} 资源或用户未映射")
            continue
        mode = sl.get("share_mode") or "read_only"
        status = sl.get("status") or "active"
        tenant = (maps.get("tenant") or {}).get(
            str(sl.get("tenant_id") or "1"), a_tenant_default
        )
        lines.append(
            "INSERT INTO share_link (id, share_token, resource_id, resource_type, share_mode, "
            "status, create_user_id, tenant_id) VALUES ("
            f"{sql_str(new_id)}, {sql_str(new_token)}, {sql_str(mapped_res)}, {sql_str(rtype)}, "
            f"{sql_str(mode)}, {sql_str(status)}, {sql_str(str(user))}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'share_link', {sql_str(src)}, {sql_str(new_id)}, 'regen', "
            f"{sql_str('do not copy secret')});"
        )
        share_maps.append({"b_id": src, "a_id": new_id})
    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", share_maps
