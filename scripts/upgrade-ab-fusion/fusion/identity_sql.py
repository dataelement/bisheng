"""把映射写成 fusion_map INSERT, 以及身份相关 INSERT. 默认不 UPDATE A 用户/部门."""

from __future__ import annotations

from fusion import NAME_SUFFIX, UNUSABLE_PASSWORD
from fusion.sql import escape, fusion_batch_open_sql, sql_int, sql_str, tsv_none


def copied_login_password(src_user: dict) -> str:
    """create 用户带上 B 已存的 password 哈希, 供 A 本地登录校验.

    库里存的是 MD5 哈希, 不是明文. 空/NULL 仍用不可登录占位, 避免写成空串后登录路径崩溃.
    """
    pwd = tsv_none(src_user.get("password"))
    return pwd if pwd else UNUSABLE_PASSWORD


def _map_row(batch: str, entity: str, src: str, dst: str, action: str, note: str = "") -> str:
    return (
        "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
        f"{sql_str(batch)}, {sql_str(entity)}, {sql_str(src)}, {sql_str(dst)}, "
        f"{sql_str(action)}, {sql_str(note)}) "
        "ON DUPLICATE KEY UPDATE dst_id=VALUES(dst_id), action=VALUES(action), note=VALUES(note);"
    )


def unique_user_name(desired: str, existing: set[str], src_id: str) -> str:
    """existing 存小写. MySQL 用户名/编码唯一索引大小写不敏感."""
    if desired.lower() not in existing:
        return desired
    candidate = f"{desired}_{NAME_SUFFIX}_{src_id}"
    n = 1
    while candidate.lower() in existing:
        n += 1
        candidate = f"{desired}_{NAME_SUFFIX}_{src_id}_{n}"
    return candidate


def generate_identity_sql(
    *,
    batch: str,
    tenant_map: list[dict],
    user_map: list[dict],
    b_users: list[dict],
    a_user_names: set[str],
    next_user_id: int,
    dept_map: list[dict],
    next_group_id: int,
    b_groups: list[dict],
    b_usergroups: list[dict],
    b_user_departments: list[dict],
    role_map: list[dict],
    b_roles: list[dict],
    b_userroles: list[dict],
    next_role_id: int,
    a_tenant_id: str,
    a_external_ids: set[str] | None = None,
) -> tuple[str, dict]:
    """生成身份 SQL. bind 只写映射表; create 在 A INSERT 并拷贝 B password 哈希.

    返回 (sql, extra), extra 含 user_alloc/group_alloc/role_alloc 供后序域使用.
    """
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {escape(batch)} identity B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "identity"),
    ]
    for row in tenant_map:
        if (row.get("action") or "") == "bind" and row.get("b_tenant_id") and row.get("a_tenant_id"):
            lines.append(
                _map_row(
                    batch,
                    "tenant",
                    row["b_tenant_id"],
                    row["a_tenant_id"],
                    "bind",
                    row.get("note") or "",
                )
            )

    allocated_users: dict[str, str] = {}
    uid = next_user_id
    names = {n.lower() for n in a_user_names}
    ext_taken = {x.lower() for x in (a_external_ids or []) if x and str(x).lower() not in {"null", "none"}}
    b_by_id = {str(u.get("user_id")): u for u in b_users}

    for row in user_map:
        action = row.get("action") or ""
        src = row.get("b_user_id") or ""
        if action == "bind":
            dst = row.get("a_user_id") or ""
            if not dst:
                continue
            allocated_users[src] = dst
            lines.append(_map_row(batch, "user", src, dst, "bind", row.get("note") or ""))
        elif action == "create":
            src_user = b_by_id.get(src) or {}
            dst = str(uid)
            uid += 1
            allocated_users[src] = dst
            uname = unique_user_name(src_user.get("user_name") or f"buser_{src}", names, src)
            names.add(uname.lower())
            ext = tsv_none(src_user.get("external_id"))
            # A 已有 source=local + 同 external_id 时置空, 避免 uk_user_source_external_id
            if ext and ext.lower() in ext_taken:
                ext = None
            if ext:
                ext_taken.add(ext.lower())
            code = tsv_none(src_user.get("external_code"))
            lines.append(
                "INSERT INTO `user` (user_id, user_name, password, email, phone_number, "
                "`source`, external_id, external_code, `delete`) VALUES ("
                f"{sql_int(dst)}, {sql_str(uname)}, {sql_str(copied_login_password(src_user))}, "
                f"{sql_str(tsv_none(src_user.get('email')))}, "
                f"{sql_str(tsv_none(src_user.get('phone_number')))}, "
                f"'local', {sql_str(ext)}, {sql_str(code)}, "
                f"{sql_int(src_user.get('delete') or 0, '0')});"
            )
            lines.append(
                "INSERT INTO user_tenant (user_id, tenant_id, is_active, is_default, status) VALUES ("
                f"{sql_int(dst)}, {sql_int(a_tenant_id)}, 1, 1, 'active');"
            )
            lines.append(_map_row(batch, "user", src, dst, "create", f"user_name={uname}"))

    gid = next_group_id
    group_alloc: dict[str, str] = {}
    for g in b_groups:
        src = str(g.get("id") or "")
        dst = str(gid)
        gid += 1
        group_alloc[src] = dst
        gname = g.get("group_name") or f"group-{src}"
        if NAME_SUFFIX not in gname:
            gname = f"{NAME_SUFFIX}{gname}"
        owner = allocated_users.get(str(g.get("create_user") or ""), "NULL")
        owner_sql = sql_int(owner) if owner != "NULL" else "NULL"
        lines.append(
            "INSERT INTO `group` (id, group_name, remark, visibility, create_user, tenant_id) VALUES ("
            f"{sql_int(dst)}, {sql_str(gname)}, {sql_str(g.get('remark') or None)}, "
            f"{sql_str(g.get('visibility') or 'public')}, {owner_sql}, {sql_int(a_tenant_id)});"
        )
        lines.append(_map_row(batch, "group", src, dst, "create", gname))

    for row in dept_map:
        action = row.get("action") or ""
        src = row.get("b_dept_pk") or ""
        if action == "bind" and row.get("a_dept_pk"):
            lines.append(_map_row(batch, "dept", src, row["a_dept_pk"], "bind", row.get("note") or ""))
        elif action == "as_group":
            dst = str(gid)
            gid += 1
            gname = f"{NAME_SUFFIX}{row.get('b_name') or src}"
            lines.append(
                "INSERT INTO `group` (id, group_name, remark, visibility, tenant_id) VALUES ("
                f"{sql_int(dst)}, {sql_str(gname)}, {sql_str('from B department ' + src)}, "
                f"'public', {sql_int(a_tenant_id)});"
            )
            lines.append(_map_row(batch, "dept_as_group", src, dst, "as_group", gname))
            lines.append(_map_row(batch, "group", f"dept:{src}", dst, "as_group", gname))

    dept_bind = {r["b_dept_pk"]: r["a_dept_pk"] for r in dept_map if r.get("action") == "bind" and r.get("a_dept_pk")}
    dept_as_group = {}
    # as_group dst comes from fusion_map generation order; reconstruct from SQL maps we just allocated
    # 上面循环已写 SQL, 这里用第二次扫描按相同顺序还原 id
    gid2 = next_group_id + len(b_groups)
    for row in dept_map:
        if row.get("action") == "as_group":
            dept_as_group[row.get("b_dept_pk") or ""] = str(gid2)
            gid2 += 1

    for ug in b_usergroups:
        u = allocated_users.get(str(ug.get("user_id") or ""))
        g = group_alloc.get(str(ug.get("group_id") or ""))
        if not u or not g:
            continue
        admin = sql_int(ug.get("is_group_admin") or 0, "0")
        lines.append(
            "INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) VALUES ("
            f"{sql_int(u)}, {sql_int(g)}, {admin}, {sql_int(a_tenant_id)});"
        )

    for ud in b_user_departments:
        u = allocated_users.get(str(ud.get("user_id") or ""))
        src_dept = str(ud.get("department_id") or "")
        if not u:
            continue
        if src_dept in dept_bind:
            lines.append(
                "INSERT IGNORE INTO user_department (user_id, department_id, is_primary, source) VALUES ("
                f"{sql_int(u)}, {sql_int(dept_bind[src_dept])}, "
                f"{sql_int(ud.get('is_primary') or 0, '0')}, 'fusion');"
            )
        elif src_dept in dept_as_group:
            lines.append(
                "INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) VALUES ("
                f"{sql_int(u)}, {sql_int(dept_as_group[src_dept])}, 0, {sql_int(a_tenant_id)});"
            )

    rid = next_role_id
    role_alloc: dict[str, str] = {}
    b_role_by_id = {str(r.get("id")): r for r in b_roles}
    for row in role_map:
        action = row.get("action") or ""
        src = row.get("b_role_id") or ""
        if action == "bind" and row.get("a_role_id"):
            role_alloc[src] = row["a_role_id"]
            lines.append(_map_row(batch, "role", src, row["a_role_id"], "bind", row.get("note") or ""))
        elif action == "create":
            dst = str(rid)
            rid += 1
            role_alloc[src] = dst
            src_role = b_role_by_id.get(src) or {}
            rname = src_role.get("role_name") or f"role-{src}"
            if NAME_SUFFIX not in rname:
                rname = f"{NAME_SUFFIX}{rname}"
            lines.append(
                "INSERT INTO role (id, role_name, role_type, remark, tenant_id) VALUES ("
                f"{sql_int(dst)}, {sql_str(rname)}, {sql_str(src_role.get('role_type') or 'tenant')}, "
                f"{sql_str(src_role.get('remark') or None)}, {sql_int(a_tenant_id)});"
            )
            lines.append(_map_row(batch, "role", src, dst, "create", rname))

    for ur in b_userroles:
        u = allocated_users.get(str(ur.get("user_id") or ""))
        r = role_alloc.get(str(ur.get("role_id") or ""))
        if not u or not r:
            continue
        lines.append(
            "INSERT INTO userrole (user_id, role_id, tenant_id) VALUES ("
            f"{sql_int(u)}, {sql_int(r)}, {sql_int(a_tenant_id)});"
        )

    lines.append("COMMIT;")
    extra = {
        "user_alloc": allocated_users,
        "group_alloc": group_alloc,
        "role_alloc": role_alloc,
        "dept_as_group": dept_as_group,
    }
    return "\n".join(lines) + "\n", extra
