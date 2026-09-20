"""部门/角色授权: 只写本批新建资源, 禁止给 A 原对象扩权.

角色授权来源: B roleaccess + userrole, 展开成 user: 元组, 并 INSERT 重写后的 roleaccess.
部门授权来源: 可选的 B OpenFGA dump (department:#member / user_group:#member).
不拷 B 的 Tuple ID. 工具/看板/菜单不迁.
"""

from __future__ import annotations

from fusion.openfga_tuples import assert_no_a_space_objects
from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_str

ADMIN_ROLE = 1
SKIP_ACCESS_TYPES = frozenset({7, 8, 11, 12, 99})
ALLOWED_RELATIONS = frozenset({"owner", "manager", "editor", "viewer"})
ALLOWED_OBJECT_TYPES = frozenset(
    {"knowledge_library", "workflow", "assistant", "knowledge_file"}
)

ACCESS_TYPE_MAPPING = {
    1: ("knowledge_library", "viewer", "knowledge"),
    3: ("knowledge_library", "editor", "knowledge"),
    5: ("assistant", "viewer", "assistant"),
    6: ("assistant", "editor", "assistant"),
    9: ("workflow", "viewer", "flow"),
    10: ("workflow", "editor", "flow"),
}

OBJECT_MAP_ENTITY = {
    "knowledge_library": "knowledge",
    "knowledge_space": "knowledge",
    "workflow": "flow",
    "assistant": "assistant",
    "knowledge_file": "file",
}


def dept_subjects_from_rows(dept_rows: list[dict]) -> dict[str, str]:
    """b_dept_pk -> OpenFGA subject. bind 用部门, as_group 用用户组."""
    out: dict[str, str] = {}
    for row in dept_rows:
        src = str(row.get("b_dept_pk") or "").strip()
        action = (row.get("action") or "").strip()
        if not src:
            continue
        if action == "bind" and row.get("a_dept_pk"):
            out[src] = f"department:{row['a_dept_pk']}#member"
        elif action == "as_group" and row.get("a_group_id"):
            out[src] = f"user_group:{row['a_group_id']}#member"
    return out


def _split_obj(obj: str) -> tuple[str, str]:
    typ, _, oid = str(obj or "").partition(":")
    return typ, oid


def _remap_object(
    obj: str,
    maps: dict[str, dict[str, str]],
    *,
    migrate_b_spaces: bool,
    a_space_ids: set[int],
) -> str | None:
    typ, oid = _split_obj(obj)
    if typ == "knowledge_space" and not migrate_b_spaces:
        return None
    if typ not in ALLOWED_OBJECT_TYPES and not (
        typ == "knowledge_space" and migrate_b_spaces
    ):
        return None
    entity = OBJECT_MAP_ENTITY.get(typ)
    dst = (maps.get(entity) or {}).get(oid) if entity else None
    if not dst:
        return None
    if typ in {"knowledge_library", "knowledge_space"}:
        try:
            nid = int(dst)
        except (TypeError, ValueError):
            nid = None
        if nid is not None and nid in a_space_ids:
            raise ValueError(f"OpenFGA 授权命中 A 原空间 {typ}:{dst}")
    return f"{typ}:{dst}"


def _remap_subject(
    user: str,
    maps: dict[str, dict[str, str]],
    dept_subjects: dict[str, str],
) -> str | None:
    text = str(user or "")
    if text.startswith("user:"):
        uid = text[5:].split("#", 1)[0]
        dst = (maps.get("user") or {}).get(uid)
        return f"user:{dst}" if dst else None
    if text.startswith("department:"):
        rest = text[len("department:") :]
        oid, _, rel = rest.partition("#")
        mapped = dept_subjects.get(oid)
        if not mapped:
            return None
        if rel:
            base = mapped.split("#", 1)[0]
            return f"{base}#{rel}"
        return mapped
    if text.startswith("user_group:"):
        rest = text[len("user_group:") :]
        oid, _, rel = rest.partition("#")
        dst = (maps.get("group") or {}).get(oid)
        if not dst:
            return None
        return f"user_group:{dst}#{rel or 'member'}"
    return None


def _tuple_from_row(row: dict) -> dict | None:
    if "user" in row and "relation" in row and "object" in row:
        return {
            "user": row["user"],
            "relation": row["relation"],
            "object": row["object"],
        }
    key = row.get("key") if isinstance(row.get("key"), dict) else None
    if key:
        return _tuple_from_row(key)
    return None


def generate_role_grant_tuples(
    *,
    role_access: list[dict],
    user_roles: list[dict],
    maps: dict[str, dict[str, str]],
    a_space_ids: set[int],
) -> list[dict]:
    """roleaccess 按 userrole 展开成 user viewer/editor. 跳过工具/看板/管理员角色."""
    role_map = maps.get("role") or {}
    user_map = maps.get("user") or {}
    role_users: dict[str, list[str]] = {}
    for ur in user_roles:
        src_role = str(ur.get("role_id") or "")
        src_user = str(ur.get("user_id") or "")
        dst_role = role_map.get(src_role)
        dst_user = user_map.get(src_user)
        if not dst_role or not dst_user:
            continue
        if int(dst_role) == ADMIN_ROLE or src_role == str(ADMIN_ROLE):
            continue
        role_users.setdefault(src_role, []).append(dst_user)

    out: list[dict] = []
    for ra in role_access:
        try:
            access_type = int(ra.get("type") or 0)
        except (TypeError, ValueError):
            continue
        if access_type in SKIP_ACCESS_TYPES:
            continue
        src_role = str(ra.get("role_id") or "")
        if src_role == str(ADMIN_ROLE) or role_map.get(src_role) == str(ADMIN_ROLE):
            continue
        spec = ACCESS_TYPE_MAPPING.get(access_type)
        if not spec:
            continue
        obj_type, relation, entity = spec
        src_third = str(ra.get("third_id") or "")
        dst_third = (maps.get(entity) or {}).get(src_third)
        if not dst_third:
            continue
        if entity == "knowledge":
            if int(dst_third) in a_space_ids:
                raise ValueError(f"roleaccess 目标知识库 {dst_third} 是 A 原空间")
        for uid in role_users.get(src_role, []):
            out.append(
                {
                    "user": f"user:{uid}",
                    "relation": relation,
                    "object": f"{obj_type}:{dst_third}",
                }
            )
    return out


def generate_role_access_sql(
    *,
    batch: str,
    role_access: list[dict],
    maps: dict[str, dict[str, str]],
    a_existing_ids: set[int],
    next_id: int,
    a_tenant_default: str,
    a_space_ids: set[int],
) -> tuple[str, list[dict]]:
    """把 B 角色对新建资源的授权 INSERT 到 A roleaccess."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} roleaccess B->A (created resources only)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "role_access"),
    ]
    role_map = maps.get("role") or {}
    tenant_map = maps.get("tenant") or {}
    taken = set(a_existing_ids)
    nxt = next_id
    out: list[dict] = []
    skipped = 0
    preexisting_ra = dict(maps.get("role_access") or {})
    for ra in role_access:
        src = str(ra.get("id") or "")
        if src in preexisting_ra:
            out.append({"b_id": src, "a_id": preexisting_ra[src]})
            continue
        try:
            access_type = int(ra.get("type") or 0)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if access_type in SKIP_ACCESS_TYPES:
            skipped += 1
            continue
        src_role = str(ra.get("role_id") or "")
        dst_role = role_map.get(src_role)
        if not dst_role or dst_role == str(ADMIN_ROLE) or src_role == str(ADMIN_ROLE):
            skipped += 1
            continue
        spec = ACCESS_TYPE_MAPPING.get(access_type)
        if not spec:
            skipped += 1
            continue
        _obj_type, _rel, entity = spec
        src_third = str(ra.get("third_id") or "")
        dst_third = (maps.get(entity) or {}).get(src_third)
        if not dst_third:
            skipped += 1
            continue
        if entity == "knowledge" and int(dst_third) in a_space_ids:
            raise ValueError(f"roleaccess {src} 目标知识库 {dst_third} 是 A 原空间")
        tenant = tenant_map.get(str(ra.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        lines.append(
            "INSERT INTO roleaccess (id, role_id, third_id, type, tenant_id) VALUES ("
            f"{dst}, {sql_int(dst_role)}, {sql_str(dst_third)}, {access_type}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'role_access', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(f'type={access_type} {src_third}->{dst_third}')});"
        )
        out.append({"b_id": src, "a_id": str(dst)})
    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out


def remap_b_openfga_tuples(
    *,
    rows: list[dict],
    maps: dict[str, dict[str, str]],
    dept_subjects: dict[str, str],
    a_space_ids: set[int],
    migrate_b_spaces: bool = False,
) -> list[dict]:
    """只保留对象属于本批新建资源的元组, 重写 subject/object."""
    out: list[dict] = []
    for raw in rows:
        row = _tuple_from_row(raw)
        if not row:
            continue
        relation = str(row.get("relation") or "")
        if relation not in ALLOWED_RELATIONS:
            continue
        obj = _remap_object(
            str(row.get("object") or ""),
            maps,
            migrate_b_spaces=migrate_b_spaces,
            a_space_ids=a_space_ids,
        )
        if not obj:
            continue
        user = _remap_subject(str(row.get("user") or ""), maps, dept_subjects)
        if not user:
            continue
        out.append({"user": user, "relation": relation, "object": obj})
    assert_no_a_space_objects(out, a_space_ids)
    return out
