"""系统角色 1/2 bind; 其它 B 角色默认在 A 新建, 不按名合并."""

from __future__ import annotations


def propose(a_roles: list[dict], b_roles: list[dict]) -> dict:
    a_ids = {str(r.get("id")) for r in a_roles}
    mapped = []
    for b in b_roles:
        bid = str(b.get("id") or "")
        name = b.get("role_name") or ""
        if bid in {"1", "2"} and bid in a_ids:
            mapped.append(
                {
                    "b_role_id": bid,
                    "a_role_id": bid,
                    "action": "bind",
                    "note": f"系统角色 {name} 以 A 为准",
                }
            )
            continue
        mapped.append(
            {
                "b_role_id": bid,
                "a_role_id": "",
                "action": "create",
                "note": "自定义角色不按名合并, 在 A 新建 [B迁移] 角色",
            }
        )
    return {"map": mapped, "conflict": [], "manual": []}
