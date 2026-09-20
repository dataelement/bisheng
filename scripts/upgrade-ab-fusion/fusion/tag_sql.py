"""传统库标签: 只为已映射资源新建 review_tag / review_tag_link, 不按同名合并到 A."""

from __future__ import annotations

from fusion.sql import (
    alloc_int_id,
    fusion_batch_open_sql,
    is_truthy,
    sql_int,
    sql_str,
)

# group_resource.ResourceTypeEnum
RES_KNOWLEDGE = 1
RES_ASSISTANT = 3
RES_TOOL = 4
RES_WORKFLOW = 5
RES_SPACE_FILE = 8
RES_KNOWLEDGE_FILE = 9

SKIP_RESOURCE_TYPES = frozenset({RES_SPACE_FILE, RES_TOOL})
SKIP_BUSINESS_TYPES = frozenset({"knowledge_space", "tag_library"})


def _resource_dst(
    resource_type: int, resource_id: str, maps: dict[str, dict[str, str]]
) -> str | None:
    table = {
        RES_KNOWLEDGE: "knowledge",
        RES_ASSISTANT: "assistant",
        RES_WORKFLOW: "flow",
        RES_KNOWLEDGE_FILE: "file",
    }.get(resource_type)
    if not table:
        return None
    return (maps.get(table) or {}).get(resource_id)


def _remap_business_id(
    business_type: str, business_id: str, maps: dict[str, dict[str, str]]
) -> str | None:
    if not business_id:
        return ""
    if business_type == "knowledge":
        return (maps.get("knowledge") or {}).get(business_id)
    if business_type == "application":
        return (maps.get("flow") or {}).get(business_id) or (
            maps.get("assistant") or {}
        ).get(business_id)
    return None


def generate_tag_sql(
    *,
    batch: str,
    tags: list[dict],
    links: list[dict],
    maps: dict[str, dict[str, str]],
    a_tag_ids: set[int],
    a_link_ids: set[int],
    next_tag_id: int,
    next_link_id: int,
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, tag_maps, link_maps). 空间/标签库/工具链接触发跳过."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} review_tag B->A (create only, no name-bind)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "tags"),
    ]
    user_map = maps.get("user") or {}
    tenant_map = maps.get("tenant") or {}

    keep_links: list[dict] = []
    needed_tags: set[str] = set()
    for link in links:
        if is_truthy(link.get("is_deleted")):
            continue
        rtype = int(link.get("resource_type") or 0)
        if rtype in SKIP_RESOURCE_TYPES:
            continue
        rid = str(link.get("resource_id") or "")
        if not _resource_dst(rtype, rid, maps):
            continue
        tid = str(link.get("tag_id") or "")
        if not tid:
            continue
        keep_links.append(link)
        needed_tags.add(tid)

    tag_by_id = {str(t.get("id") or ""): t for t in tags}
    tag_taken = set(a_tag_ids)
    tag_nxt = next_tag_id
    tag_alloc: dict[str, str] = dict(maps.get("review_tag") or {})
    preexisting_tag = dict(tag_alloc)
    preexisting_link = dict(maps.get("review_tag_link") or {})
    tag_maps: list[dict] = []

    for src in sorted(needed_tags, key=lambda x: int(x) if x.isdigit() else 0):
        if src in preexisting_tag:
            tag_maps.append({"b_id": src, "a_id": preexisting_tag[src]})
            continue
        row = tag_by_id.get(src)
        if not row or is_truthy(row.get("is_deleted")):
            continue
        btype = str(row.get("business_type") or "")
        if btype in SKIP_BUSINESS_TYPES:
            continue
        biz = str(row.get("business_id") or "")
        new_biz = _remap_business_id(btype, biz, maps)
        if biz and new_biz is None:
            continue
        uid = str(row.get("user_id") or "0")
        owner = user_map.get(uid) if uid not in {"", "0"} else uid or "0"
        if uid not in {"", "0"} and not owner:
            continue
        reviewer_src = str(row.get("reviewer_id") or "")
        reviewer = user_map.get(reviewer_src) if reviewer_src not in {"", "0"} else None
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(tag_nxt, tag_taken)
        tag_nxt = dst + 1
        tag_alloc[src] = str(dst)
        lines.append(
            "INSERT INTO review_tag (id, name, business_type, business_id, user_id, tenant_id, "
            "resource_type, is_deleted, review_status, reject_reason, reviewer_id, remark) VALUES ("
            f"{dst}, {sql_str(row.get('name') or '')}, {sql_str(btype or 'knowledge')}, "
            f"{sql_str(new_biz or None)}, {sql_int(owner or 0, '0')}, {sql_int(tenant)}, "
            f"{sql_str(row.get('resource_type') or 'manual_tag')}, 0, "
            f"{sql_int(row.get('review_status') or 0, '0')}, {sql_str(row.get('reject_reason') or None)}, "
            f"{sql_int(reviewer)}, {sql_str(row.get('remark') or None)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'review_tag', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(row.get('name') or '')});"
        )
        tag_maps.append({"b_id": src, "a_id": str(dst)})

    link_taken = set(a_link_ids)
    link_nxt = next_link_id
    link_maps: list[dict] = []
    skipped = 0
    for link in keep_links:
        src = str(link.get("id") or "")
        if src in preexisting_link:
            link_maps.append({"b_id": src, "a_id": preexisting_link[src]})
            continue
        src_tag = str(link.get("tag_id") or "")
        dst_tag = tag_alloc.get(src_tag)
        rtype = int(link.get("resource_type") or 0)
        dst_res = _resource_dst(rtype, str(link.get("resource_id") or ""), maps)
        if not dst_tag or not dst_res:
            skipped += 1
            continue
        uid = str(link.get("user_id") or "0")
        owner = user_map.get(uid) if uid not in {"", "0"} else uid or "0"
        if uid not in {"", "0"} and not owner:
            skipped += 1
            continue
        tenant = tenant_map.get(str(link.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(link_nxt, link_taken)
        link_nxt = dst + 1
        lines.append(
            "INSERT INTO review_tag_link (id, tag_id, resource_id, resource_type, user_id, "
            "tenant_id, is_deleted, remark) VALUES ("
            f"{dst}, {sql_int(dst_tag)}, {sql_str(dst_res)}, {rtype}, "
            f"{sql_int(owner or 0, '0')}, {sql_int(tenant)}, 0, "
            f"{sql_str(link.get('remark') or None)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'review_tag_link', {sql_str(src or str(dst))}, {sql_str(str(dst))}, "
            f"'create', {sql_str(f'tag {src_tag}->{dst_tag}')});"
        )
        link_maps.append({"b_id": src, "a_id": str(dst)})

    lines.append(f"-- skipped_links={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", tag_maps, link_maps
