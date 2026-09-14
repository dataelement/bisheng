#!/usr/bin/env python3
"""把已签字 dept-map.csv 转成可审查 SQL。不连库。

bind: 只写 fusion_dept_map, 不改 B 部门树。
create: B 新发号, dept_id=fusion-a{a_pk}, 按 A 父映射挂接。
user_department: JOIN 已写入的 fusion_user_map / fusion_dept_map, 映不上的行不插入。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACK_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_PACK_LIB) not in sys.path:
    sys.path.insert(0, str(_PACK_LIB))

from sqlutil import escape, load_csv, load_tsv, sql_int, sql_str  # noqa: E402


def _var(a_pk: int) -> str:
    return f"@fusion_d_{a_pk}"


def generate_sql(
    map_rows: list[dict[str, str]],
    memberships: list[dict[str, str]],
    batch_no: str,
) -> str:
    lines: list[str] = [
        f"-- generated dept map batch_no={escape(batch_no)}",
        "START TRANSACTION;",
        "INSERT INTO fusion_batch (batch_no, phase, status, note) VALUES "
        f"('{escape(batch_no)}','p4_dept','open','dept map') "
        "ON DUPLICATE KEY UPDATE note=VALUES(note);",
    ]
    by_a = {int(r["a_dept_pk"]): r for r in map_rows if r.get("a_dept_pk")}
    emitted_parent_first: list[dict[str, str]] = []
    waiting = list(map_rows)
    guard = 0
    while waiting and guard < 10000:
        guard += 1
        progressed = False
        rest: list[dict[str, str]] = []
        done = {int(r["a_dept_pk"]) for r in emitted_parent_first}
        for row in waiting:
            parent = (row.get("a_parent_pk") or "").strip()
            if parent and int(parent) in by_a and int(parent) not in done:
                rest.append(row)
                continue
            emitted_parent_first.append(row)
            progressed = True
        if not progressed:
            emitted_parent_first.extend(rest)
            break
        waiting = rest

    for row in emitted_parent_first:
        action = row.get("action", "")
        a_pk = int(row["a_dept_pk"])
        code = escape(row.get("external_id") or "")
        src = escape(row.get("a_source") or "sg")
        if action == "bind":
            b_pk = int(row["b_dept_pk"])
            lines.append(f"SET {_var(a_pk)} := {b_pk};")
            lines.append(
                "INSERT INTO fusion_dept_map "
                "(batch_no,a_dept_pk,b_dept_pk,external_id,action) VALUES "
                f"('{escape(batch_no)}',{a_pk},{b_pk},'{code}','bind') "
                "ON DUPLICATE KEY UPDATE b_dept_pk=VALUES(b_dept_pk), action='bind';"
            )
            continue
        if action != "create":
            raise SystemExit(f"未知 action={action} a_dept_pk={a_pk}")
        parent = (row.get("a_parent_pk") or "").strip()
        parent_sql = "NULL"
        if parent and int(parent) in by_a:
            parent_sql = _var(int(parent))
        name = sql_str(row.get("a_name") or code or f"dept-{a_pk}")
        short_name = (
            sql_str(row.get("a_short_name") or None)
            if row.get("a_short_name")
            else "NULL"
        )
        sort_order = sql_int(row.get("a_sort_order"), "0")
        status = sql_str(row.get("a_status") or "active")
        tenant_id = sql_int(row.get("a_tenant_id"), "1")
        dept_id = sql_str(f"fusion-a{a_pk}")
        lines.append(f"-- create a_dept_pk={a_pk} external_id={code}")
        lines.append(
            "INSERT INTO department "
            "(dept_id, name, short_name, parent_id, tenant_id, path, sort_order, "
            "source, external_id, status) "
            f"SELECT {dept_id}, {name}, {short_name}, {parent_sql}, {tenant_id}, '', "
            f"{sort_order}, '{src}', '{code}', {status} FROM DUAL "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM department WHERE external_id="
            f"'{code}' AND external_id<>'' LIMIT 1);"
        )
        lines.append(
            f"SET {_var(a_pk)} := ("
            f"SELECT id FROM department WHERE external_id='{code}' AND external_id<>'' "
            "ORDER BY id LIMIT 1);"
        )
        lines.append(
            "INSERT INTO fusion_dept_map "
            "(batch_no,a_dept_pk,b_dept_pk,external_id,action) VALUES "
            f"('{escape(batch_no)}',{a_pk},{_var(a_pk)},'{code}','create') "
            "ON DUPLICATE KEY UPDATE b_dept_pk=VALUES(b_dept_pk), action='create';"
        )

    for _ in range(20):
        lines.append(
            "UPDATE department d "
            "LEFT JOIN department p ON p.id = d.parent_id "
            "INNER JOIN fusion_dept_map m ON m.b_dept_pk = d.id "
            f"AND m.batch_no='{escape(batch_no)}' AND m.action='create' "
            "SET d.path = IF(d.parent_id IS NULL, CONCAT('/', d.id, '/'), "
            "CONCAT(IFNULL(NULLIF(p.path, ''), '/'), d.id, '/'));"
        )

    for mem in memberships:
        a_user = (mem.get("user_id") or "").strip()
        a_dept = (mem.get("department_id") or "").strip()
        if not a_user or not a_dept:
            continue
        is_primary = sql_int(mem.get("is_primary"), "1")
        src = escape(mem.get("source") or "sg")
        lines.append(
            "INSERT INTO user_department (user_id, department_id, is_primary, source) "
            "SELECT um.b_user_id, dm.b_dept_pk, "
            f"{is_primary}, '{src}' "
            "FROM fusion_user_map um "
            "JOIN fusion_dept_map dm ON dm.a_dept_pk="
            f"{int(a_dept)} AND dm.b_dept_pk IS NOT NULL "
            f"WHERE um.a_user_id={int(a_user)} AND um.b_user_id IS NOT NULL "
            "AND um.b_user_id<>0 "
            "AND NOT EXISTS ("
            "SELECT 1 FROM user_department x "
            "WHERE x.user_id=um.b_user_id AND x.department_id=dm.b_dept_pk);"
        )

    lines.append(
        "SELECT COUNT(*) AS unbound_create FROM fusion_dept_map "
        f"WHERE batch_no='{escape(batch_no)}' AND action='create' AND b_dept_pk IS NULL;"
    )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def main() -> None:
    map_path = Path(sys.argv[1])
    batch_no = sys.argv[2] if len(sys.argv) > 2 else "p4-dept"
    memberships_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    memberships = load_tsv(memberships_path) if memberships_path else []
    print(generate_sql(load_csv(map_path), memberships, batch_no), end="")


if __name__ == "__main__":
    main()
