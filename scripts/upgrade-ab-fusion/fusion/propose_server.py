"""llm_server 映射: type+name 一致才 bind. 不拷 config 里的密钥."""

from __future__ import annotations


def _key(row: dict) -> tuple[str, str]:
    return ((row.get("type") or "").strip(), (row.get("name") or "").strip())


def propose(a_servers: list[dict], b_servers: list[dict]) -> dict:
    a_index: dict[tuple[str, str], dict] = {}
    for row in a_servers:
        k = _key(row)
        if k[0] and k[1]:
            a_index.setdefault(k, row)
    mapped = []
    manual = []
    for b in b_servers:
        bid = str(b.get("id") or "")
        k = _key(b)
        hit = a_index.get(k)
        if hit:
            mapped.append(
                {
                    "b_server_id": bid,
                    "a_server_id": str(hit.get("id") or ""),
                    "action": "bind",
                    "note": f"type+name={k[0]}/{k[1]}",
                }
            )
        else:
            manual.append(
                {
                    "b_server_id": bid,
                    "name": b.get("name") or "",
                    "reason": "A 无同 type+name 的 llm_server, 在 A 配好后再填; 禁止拷密钥",
                }
            )
    return {"map": mapped, "conflict": [], "manual": manual}
