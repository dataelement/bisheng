"""部门映射: 外部编码 bind 到 A; 对不上的不改 A 组织树, 改为本地用户组."""

from __future__ import annotations

from collections import defaultdict


def _ext(row: dict) -> str:
    raw = (row.get("external_id") or "").strip()
    if raw.lower() in {"", "null", "none", "nil"}:
        return ""
    return raw


def propose(a_depts: list[dict], b_depts: list[dict]) -> dict:
    a_by_ext: dict[str, list[dict]] = defaultdict(list)
    for row in a_depts:
        ext = _ext(row)
        if ext:
            a_by_ext[ext].append(row)

    mapped: list[dict] = []
    conflict: list[dict] = []
    manual: list[dict] = []

    for b in b_depts:
        bid = str(b.get("id") or "")
        ext = _ext(b)
        name = b.get("name") or b.get("dept_name") or ""
        if not ext:
            mapped.append(
                {
                    "b_dept_pk": bid,
                    "a_dept_pk": "",
                    "a_group_id": "",
                    "external_id": "",
                    "action": "as_group",
                    "b_name": name,
                    "note": "无外部编码, 不新建 A 部门, 迁为本地用户组",
                }
            )
            continue
        hits = a_by_ext.get(ext) or []
        if len(hits) > 1:
            conflict.append(
                {
                    "external_id": ext,
                    "a_dept_pks": ",".join(str(x.get("id")) for x in hits),
                    "b_dept_pk": bid,
                    "reason": "A 同一外部编码多部门, 阻断",
                }
            )
            continue
        if not hits:
            mapped.append(
                {
                    "b_dept_pk": bid,
                    "a_dept_pk": "",
                    "a_group_id": "",
                    "external_id": ext,
                    "action": "as_group",
                    "b_name": name,
                    "note": "编码在 A 不存在; 同名也不合并, 迁为 [B迁移] 用户组",
                }
            )
            continue
        a = hits[0]
        mapped.append(
            {
                "b_dept_pk": bid,
                "a_dept_pk": str(a.get("id") or ""),
                "a_group_id": "",
                "external_id": ext,
                "action": "bind",
                "b_name": name,
                "note": "外部编码匹配 A 部门, 校验层级需人工看 conflicts",
            }
        )

    return {"map": mapped, "conflict": conflict, "manual": manual}
