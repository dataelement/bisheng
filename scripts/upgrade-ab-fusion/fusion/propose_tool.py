"""工具映射: 同 tenant 下 tool_key 完全一致才 bind, 不按名称合并, 不拷密钥."""

from __future__ import annotations

from collections import defaultdict


def propose(a_tools: list[dict], b_tools: list[dict]) -> dict:
    a_by_key: dict[str, list[dict]] = defaultdict(list)
    for row in a_tools:
        key = (row.get("tool_key") or "").strip()
        if key:
            a_by_key[key].append(row)
    mapped = []
    conflict = []
    manual = []
    for b in b_tools:
        bid = str(b.get("id") or "")
        key = (b.get("tool_key") or "").strip()
        if not key:
            manual.append(
                {
                    "b_tool_id": bid,
                    "name": b.get("name") or "",
                    "reason": "无 tool_key, 人工在 A 重建后再填 tool-map.csv; 禁止拷密钥",
                }
            )
            continue
        hits = a_by_key.get(key) or []
        if len(hits) > 1:
            conflict.append(
                {
                    "tool_key": key,
                    "a_tool_ids": ",".join(str(x.get("id")) for x in hits),
                    "b_tool_id": bid,
                    "reason": "A 同一 tool_key 多行, 阻断",
                }
            )
            continue
        if not hits:
            manual.append(
                {
                    "b_tool_id": bid,
                    "tool_key": key,
                    "name": b.get("name") or "",
                    "reason": "A 无同 key, 在 A 重建工具后再填; 禁止从 B 复制 api_key",
                }
            )
            continue
        mapped.append(
            {
                "b_tool_id": bid,
                "a_tool_id": str(hits[0].get("id") or ""),
                "action": "bind",
                "note": f"tool_key={key}",
            }
        )
    return {"map": mapped, "conflict": conflict, "manual": manual}
