"""用户组可见性: 只为 B 新增资源写 groupresource, 不给 A 原工具/空间扩权."""

from __future__ import annotations

from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_str

RES_KNOWLEDGE = 1
RES_ASSISTANT = 3
RES_TOOL = 4
RES_WORKFLOW = 5
RES_DASHBOARD = 6
RES_WORKSTATION = 7
RES_SPACE_FILE = 8
RES_KNOWLEDGE_FILE = 9

# 工具/看板/工作台/空间文件都可能指向 A 原对象, 禁止扩权
SKIP_TYPES = frozenset({RES_TOOL, RES_DASHBOARD, RES_WORKSTATION, RES_SPACE_FILE})

FGA_OBJECT_TYPE = {
    RES_KNOWLEDGE: "knowledge_library",
    RES_ASSISTANT: "assistant",
    RES_WORKFLOW: "workflow",
    RES_KNOWLEDGE_FILE: "knowledge_file",
}


def _third_dst(
    rtype: int, third_id: str, maps: dict[str, dict[str, str]]
) -> str | None:
    table = {
        RES_KNOWLEDGE: "knowledge",
        RES_ASSISTANT: "assistant",
        RES_WORKFLOW: "flow",
        RES_KNOWLEDGE_FILE: "file",
    }.get(rtype)
    if not table:
        return None
    return (maps.get(table) or {}).get(third_id)


def generate_group_resource_sql(
    *,
    batch: str,
    rows: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[int],
    next_id: int,
    a_tenant_default: str,
    a_space_ids: set[int],
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, gr_maps, fga_tuples). 只处理已映射的新增资源."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} groupresource B->A (created resources only)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "group_resource"),
    ]
    group_map = maps.get("group") or {}
    tenant_map = maps.get("tenant") or {}
    taken = set(a_existing_ids)
    nxt = next_id
    out: list[dict] = []
    tuples: list[dict] = []
    skipped = 0
    preexisting_gr = dict(maps.get("group_resource") or {})
    for row in rows:
        src = str(row.get("id") or "")
        if src in preexisting_gr:
            out.append({"b_id": src, "a_id": preexisting_gr[src]})
            continue
        rtype = int(row.get("type") or 0)
        if rtype in SKIP_TYPES:
            skipped += 1
            continue
        src_group = str(row.get("group_id") or "")
        dst_group = group_map.get(src_group)
        third = str(row.get("third_id") or "")
        dst_third = _third_dst(rtype, third, maps)
        if not dst_group or not dst_third:
            skipped += 1
            continue
        if rtype == RES_KNOWLEDGE and int(dst_third) in a_space_ids:
            raise ValueError(f"groupresource {src} 目标知识库 {dst_third} 是 A 原空间")
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        lines.append(
            "INSERT INTO groupresource (id, group_id, third_id, type, tenant_id) VALUES ("
            f"{dst}, {sql_str(dst_group)}, {sql_str(dst_third)}, {rtype}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'group_resource', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(f'type={rtype} {third}->{dst_third}')});"
        )
        out.append(
            {
                "b_id": src,
                "a_id": str(dst),
                "group_id": dst_group,
                "third_id": dst_third,
                "type": str(rtype),
            }
        )
        obj_type = FGA_OBJECT_TYPE.get(rtype)
        if obj_type:
            tuples.append(
                {
                    "user": f"user_group:{dst_group}#admin",
                    "relation": "manager",
                    "object": f"{obj_type}:{dst_third}",
                }
            )
    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out, tuples
