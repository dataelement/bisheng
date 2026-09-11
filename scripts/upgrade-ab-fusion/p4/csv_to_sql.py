#!/usr/bin/env python3
"""把已签字的 user-map.csv 转成可审查 SQL。不连库。

takeover: 保留 B 主键, 写 source=sg + external_id。
create_on_b: 按员工编码插入一行 B 用户, 同一编码的 A 双行映到 LAST_INSERT_ID。
"""

from __future__ import annotations

import csv
import hashlib
import sys
from collections import defaultdict
from pathlib import Path


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "''")


def _password_hash(code: str) -> str:
    digest = hashlib.sha256(f"fusion-disabled:{code}".encode("utf-8")).hexdigest()
    return f"fusion-disabled-{digest}"


def _load_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    reader = csv.DictReader(filtered)
    for row in reader:
        rows.append({k: (v or "").strip() for k, v in row.items() if k})
    return rows


def main() -> None:
    path = Path(sys.argv[1])
    batch_no = sys.argv[2] if len(sys.argv) > 2 else "p4-manual"
    rows = _load_rows(path)

    by_code: dict[str, set[str]] = defaultdict(set)
    by_code_action: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        code = row.get("employee_code", "")
        if not code:
            continue
        action = row.get("action", "")
        by_code_action[code].add(action)
        b_id = row.get("b_user_id", "") or "0"
        if action == "takeover":
            by_code[code].add(b_id)
        elif action == "create_on_b":
            by_code[code].add("NEW")
    mixed = {c: v for c, v in by_code_action.items() if len(v) > 1}
    if mixed:
        raise SystemExit(f"同一员工编码混用了多种 action: {mixed}")
    bad = {c: v for c, v in by_code.items() if len(v) > 1}
    if bad:
        raise SystemExit(f"同一员工编码映到多个 B user_id: {bad}")

    print("-- generated from", path)
    print(f"-- batch_no={batch_no}")
    print("START TRANSACTION;")
    print(
        "INSERT INTO fusion_batch (batch_no, phase, status, note) VALUES "
        f"('{escape(batch_no)}','p4_identity','open','identity map') "
        "ON DUPLICATE KEY UPDATE note=VALUES(note);"
    )

    emitted_create: set[str] = set()
    for row in rows:
        action = row.get("action", "")
        a_id = int(row["a_user_id"])
        code = row.get("employee_code", "")
        src = escape(row.get("a_source", ""))
        code_sql = escape(code)
        if action == "takeover":
            b_id = int(row["b_user_id"])
            print(
                f"UPDATE `user` SET source='sg', external_id='{code_sql}' "
                f"WHERE user_id={b_id} AND `delete`=0;"
            )
            print(
                "INSERT INTO fusion_user_map "
                "(batch_no,a_user_id,b_user_id,employee_code,action,a_source) VALUES "
                f"('{escape(batch_no)}',{a_id},{b_id},'{code_sql}','takeover','{src}');"
            )
        elif action == "create_on_b":
            if not code:
                raise SystemExit(f"create_on_b 缺少 employee_code: a_user_id={a_id}")
            if code not in emitted_create:
                emitted_create.add(code)
                uname = escape(
                    row.get("create_user_name") or row.get("a_user_name") or code
                )
                pwd = escape(_password_hash(code))
                print(f"-- create_on_b employee_code={code}")
                print(
                    "INSERT INTO `user` (user_name, password, source, external_id, `delete`) "
                    f"SELECT '{uname}', '{pwd}', 'sg', '{code_sql}', 0 FROM DUAL "
                    "WHERE NOT EXISTS ("
                    "SELECT 1 FROM `user` WHERE external_id="
                    f"'{code_sql}' AND external_id<>'' LIMIT 1);"
                )
                print(
                    f"SET @fusion_b_{a_id} := ("
                    f"SELECT user_id FROM `user` WHERE external_id='{code_sql}' "
                    "AND external_id<>'' ORDER BY user_id LIMIT 1);"
                )
                print(
                    "INSERT INTO userrole (user_id, role_id, tenant_id) "
                    "SELECT @fusion_b_"
                    f"{a_id}, 2, 1 FROM DUAL WHERE @fusion_b_{a_id} IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM userrole WHERE user_id=@fusion_b_"
                    f"{a_id} AND role_id=2);"
                )
                print(
                    "INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) "
                    "SELECT @fusion_b_"
                    f"{a_id}, 2, 0, 1 FROM DUAL WHERE @fusion_b_{a_id} IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM usergroup WHERE user_id=@fusion_b_"
                    f"{a_id} AND group_id=2);"
                )
                print(
                    "INSERT INTO user_tenant (user_id, tenant_id, is_default, status, is_active) "
                    "SELECT @fusion_b_"
                    f"{a_id}, 1, 1, 'active', 1 FROM DUAL WHERE @fusion_b_{a_id} IS NOT NULL "
                    "AND NOT EXISTS (SELECT 1 FROM user_tenant WHERE user_id=@fusion_b_"
                    f"{a_id} AND tenant_id=1);"
                )
                create_var = f"@fusion_b_{a_id}"
            else:
                first_a = next(
                    int(r["a_user_id"])
                    for r in rows
                    if r.get("employee_code") == code
                    and r.get("action") == "create_on_b"
                )
                create_var = f"@fusion_b_{first_a}"
            print(
                "INSERT INTO fusion_user_map "
                "(batch_no,a_user_id,b_user_id,employee_code,action,a_source) VALUES "
                f"('{escape(batch_no)}',{a_id},{create_var},'{code_sql}','create_on_b','{src}');"
            )
        elif action in {"skip", "keep_local"}:
            b_raw = row.get("b_user_id") or "0"
            b_id = int(b_raw) if b_raw not in {"", "NEW"} else 0
            if b_id <= 0:
                print(f"-- skip a_user_id={a_id} (no b_user_id)")
                continue
            print(
                "INSERT INTO fusion_user_map "
                "(batch_no,a_user_id,b_user_id,employee_code,action,a_source) VALUES "
                f"('{escape(batch_no)}',{a_id},{b_id},'{code_sql}','{escape(action)}','{src}');"
            )
        else:
            raise SystemExit(f"未知 action={action} a_user_id={a_id}")

    print(
        "SELECT COUNT(*) AS dup_ext_groups FROM ("
        "SELECT external_id FROM `user` WHERE external_id IS NOT NULL AND external_id<>'' "
        "GROUP BY external_id HAVING COUNT(*)>1) t;"
    )
    print(
        "SELECT employee_code, COUNT(DISTINCT b_user_id) AS b_ids FROM fusion_user_map "
        f"WHERE batch_no='{escape(batch_no)}' AND employee_code IS NOT NULL AND employee_code<>'' "
        "GROUP BY employee_code HAVING COUNT(DISTINCT b_user_id)>1;"
    )
    print("COMMIT;")


if __name__ == "__main__":
    main()
