"""按员工编码提出 B->A 用户映射. 禁止按姓名/手机/邮箱自动合并."""

from __future__ import annotations

from collections import defaultdict


def employee_code(row: dict) -> str:
    raw = (row.get("external_code") or row.get("external_id") or "").strip()
    # mysql TSV 把 SQL NULL 打成字面量 NULL, 不能当成员工编码.
    if raw.lower() in {"", "null", "none", "nil"}:
        return ""
    return raw


def _index_by_code(rows: list[dict], id_key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        code = employee_code(row)
        if not code:
            continue
        grouped[code].append(row)
    return grouped


def _prefer_a_user(rows: list[dict]) -> dict:
    """同一编码在 A 有 local+sg 时, 目标主体优先 sg, 不合并 A 行."""
    for row in rows:
        if (row.get("source") or "").strip() == "sg":
            return row
    return rows[0]


def propose(a_users: list[dict], b_users: list[dict]) -> dict:
    a_by_code = _index_by_code(a_users, "user_id")
    b_by_code = _index_by_code(b_users, "user_id")

    mapped: list[dict] = []
    conflict: list[dict] = []
    manual: list[dict] = []

    for b in b_users:
        bid = str(b.get("user_id") or "")
        code = employee_code(b)
        if not code:
            manual.append(
                {
                    "b_user_id": bid,
                    "b_user_name": b.get("user_name") or "",
                    "reason": "无员工编码, 人工确认后映射或 create",
                }
            )
            continue
        b_dups = b_by_code.get(code) or []
        if len(b_dups) > 1:
            conflict.append(
                {
                    "employee_code": code,
                    "b_user_ids": ",".join(str(x.get("user_id")) for x in b_dups),
                    "reason": "同一员工编码对应多个 B 用户, 阻断",
                }
            )
            continue
        a_hits = a_by_code.get(code) or []
        if not a_hits:
            mapped.append(
                {
                    "b_user_id": bid,
                    "a_user_id": "",
                    "employee_code": code,
                    "action": "create",
                    "note": "B 独有, 在 A 新建本地用户; 拷贝 B password 哈希",
                }
            )
            continue
        target = _prefer_a_user(a_hits)
        note = "员工编码匹配, 保留 A user_id"
        if len(a_hits) > 1:
            note += "; A 同编码多行, 目标取 sg 优先, 未合并 A 账号"
        mapped.append(
            {
                "b_user_id": bid,
                "a_user_id": str(target.get("user_id") or ""),
                "employee_code": code,
                "action": "bind",
                "note": note,
            }
        )

    # 去重 conflict 行
    seen = set()
    uniq_conflict = []
    for row in conflict:
        key = row["employee_code"]
        if key in seen:
            continue
        seen.add(key)
        uniq_conflict.append(row)

    return {"map": mapped, "conflict": uniq_conflict, "manual": manual}
