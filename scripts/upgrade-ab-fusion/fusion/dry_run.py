"""dry-run: 所有者必须已映射; 写集合不得碰到 A 原 type=3 空间."""

from __future__ import annotations


def dry_run_knowledge(
    knowledges: list[dict],
    user_map: dict[str, str],
    a_space_ids: set[int],
    migrate_b_spaces: bool = False,
) -> dict:
    blocked = []
    skipped = []
    ok = []
    for k in knowledges:
        src = str(k.get("id") or "")
        ktype = int(k.get("type") or 0)
        owner = str(k.get("user_id") or "")
        if owner not in user_map:
            blocked.append({"id": src, "reason": f"所有者 {owner} 未映射"})
            continue
        if ktype == 3 and not migrate_b_spaces:
            skipped.append({"id": src, "reason": "D08: 只迁传统库, 跳过 B 的 type=3"})
            continue
        ok.append(src)
    return {
        "ok": ok,
        "blocked": blocked,
        "skipped": skipped,
        "a_space_ids": sorted(a_space_ids),
    }


def dry_run_flows(flows: list[dict], user_map: dict[str, str]) -> dict:
    blocked = []
    ok = []
    for fl in flows:
        src = str(fl.get("id") or "")
        owner = str(fl.get("user_id") or "")
        if owner not in user_map:
            blocked.append({"id": src, "reason": f"所有者 {owner} 未映射"})
        else:
            ok.append(src)
    return {"ok": ok, "blocked": blocked}


def protect_a_spaces(
    write_knowledge_ids: list[int], a_space_ids: set[int]
) -> list[str]:
    hits = [i for i in write_knowledge_ids if i in a_space_ids]
    if hits:
        return [f"P0: 写集合命中 A 原空间 {hits}"]
    return []
