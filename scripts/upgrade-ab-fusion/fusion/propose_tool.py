"""工具映射: 同 tenant 下 tool_key 完全一致才 bind, 不按名称合并; 对不上则 create 并拷 extra."""

from __future__ import annotations

from collections import defaultdict


def unique_tool_key(desired: str, existing: set[str], src: str) -> str:
    """给 A 分配不冲突的 tool_key. 空 key 用 btool_{src}, 不编造业务含义."""
    base = desired or f"btool_{src}"
    if base not in existing:
        return base
    n = 1
    candidate = f"{base}_{src}"
    while candidate in existing:
        n += 1
        candidate = f"{base}_{src}_{n}"
    return candidate


def propose(a_tools: list[dict], b_tools: list[dict]) -> dict:
    a_by_key: dict[str, list[dict]] = defaultdict(list)
    taken: set[str] = set()
    for row in a_tools:
        key = (row.get("tool_key") or "").strip()
        if key:
            a_by_key[key].append(row)
            taken.add(key)
    mapped = []
    conflict = []
    manual = []
    for b in b_tools:
        bid = str(b.get("id") or "")
        key = (b.get("tool_key") or "").strip()
        hits = a_by_key.get(key) or [] if key else []
        if key and len(hits) > 1:
            conflict.append(
                {
                    "tool_key": key,
                    "a_tool_ids": ",".join(str(x.get("id")) for x in hits),
                    "b_tool_id": bid,
                    "reason": "A 同一 tool_key 多行, 阻断",
                }
            )
            continue
        if key and len(hits) == 1:
            mapped.append(
                {
                    "b_tool_id": bid,
                    "a_tool_id": str(hits[0].get("id") or ""),
                    "action": "bind",
                    "b_tool_key": key,
                    "a_tool_key": key,
                    "note": f"tool_key={key}",
                }
            )
            continue
        a_key = unique_tool_key(key, taken, bid)
        taken.add(a_key)
        note = "A 无同 key, 在 A 新建并拷 extra/api_params"
        if not key:
            note = f"无 tool_key, 在 A 新建 key={a_key} 并拷 extra/api_params"
        elif a_key != key:
            note = f"A 已占用 {key}, 新建为 {a_key} 并拷 extra/api_params"
        mapped.append(
            {
                "b_tool_id": bid,
                "a_tool_id": "",
                "action": "create",
                "b_tool_key": key,
                "a_tool_key": a_key,
                "note": note,
            }
        )
    return {"map": mapped, "conflict": conflict, "manual": manual}
