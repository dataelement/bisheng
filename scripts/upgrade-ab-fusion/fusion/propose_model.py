"""模型映射: Provider+model_name 完全一致才 bind, 否则人工. 密钥不从 B 复制."""

from __future__ import annotations


def _key(row: dict) -> tuple[str, str]:
    return (
        (row.get("provider") or row.get("server_type") or "").strip(),
        (row.get("model_name") or "").strip(),
    )


def propose(a_models: list[dict], b_models: list[dict]) -> dict:
    a_index: dict[tuple[str, str], dict] = {}
    for row in a_models:
        k = _key(row)
        if k[1]:
            a_index.setdefault(k, row)
    mapped = []
    manual = []
    for b in b_models:
        bid = str(b.get("id") or "")
        k = _key(b)
        hit = a_index.get(k)
        if hit:
            mapped.append(
                {
                    "b_model_id": bid,
                    "a_model_id": str(hit.get("id") or ""),
                    "action": "bind",
                    "note": "provider+model_name 一致, 复用 A",
                }
            )
        else:
            manual.append(
                {
                    "b_model_id": bid,
                    "model_name": b.get("model_name") or "",
                    "reason": "参数不一致或 A 不存在, 在 A 重配后再填 model-map.csv; 禁止拷密钥",
                }
            )
    return {"map": mapped, "conflict": [], "manual": manual}
