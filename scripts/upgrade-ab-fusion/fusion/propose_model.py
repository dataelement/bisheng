"""模型映射: Provider+model_name 完全一致才 bind, 否则 create 并在写入时拷 config 密钥."""

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
            mapped.append(
                {
                    "b_model_id": bid,
                    "a_model_id": "",
                    "action": "create",
                    "note": "A 无同 provider+model_name, 在 A 新建并拷 config 密钥",
                }
            )
    return {"map": mapped, "conflict": [], "manual": manual}
