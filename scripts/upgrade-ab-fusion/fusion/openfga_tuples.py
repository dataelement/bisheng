"""为 B 新增资源生成 OpenFGA Tuple. 只写 owner / 组 manager, 不改 A 原空间."""

from __future__ import annotations

WRITE_CHUNK = 40


def _flow_object_type(flow_type) -> str | None:
    try:
        ft = int(flow_type if flow_type not in (None, "") else 10)
    except (TypeError, ValueError):
        return None
    if ft == 10:
        return "workflow"
    return None


def _kid_type(ktype) -> str | None:
    try:
        t = int(ktype or 0)
    except (TypeError, ValueError):
        return None
    if t == 3:
        return None
    return "knowledge_library"


def assert_no_a_space_objects(tuples: list[dict], a_space_ids: set[int]) -> None:
    """写集合不得出现 A 原 type=3 空间 id."""
    if not a_space_ids:
        return
    for row in tuples:
        obj = str(row.get("object") or "")
        typ, _, oid = obj.partition(":")
        if typ not in {"knowledge_library", "knowledge_space"}:
            continue
        try:
            nid = int(oid)
        except ValueError:
            continue
        if nid in a_space_ids:
            raise ValueError(f"OpenFGA 写集合命中 A 原空间 {obj}")


def owner_tuple(user_id: str, object_type: str, object_id: str) -> dict:
    return {
        "user": f"user:{user_id}",
        "relation": "owner",
        "object": f"{object_type}:{object_id}",
    }


def generate_owner_tuples(
    *,
    knowledges: list[dict],
    flows: list[dict],
    assistants: list[dict],
    maps: dict[str, dict[str, str]],
    migrate_b_spaces: bool = False,
) -> list[dict]:
    """按映射后的 A 用户/资源生成 owner. 空间默认不生成."""
    user_map = maps.get("user") or {}
    k_map = maps.get("knowledge") or {}
    flow_map = maps.get("flow") or {}
    asst_map = maps.get("assistant") or {}
    out: list[dict] = []
    for k in knowledges:
        src = str(k.get("id") or "")
        dst = k_map.get(src)
        obj_type = _kid_type(k.get("type"))
        if not dst or not obj_type:
            if int(k.get("type") or 0) == 3 and migrate_b_spaces and dst:
                obj_type = "knowledge_space"
            else:
                continue
        owner = user_map.get(str(k.get("user_id") or ""))
        if not owner:
            raise ValueError(f"knowledge {src} owner 未映射, 拒绝写 OpenFGA")
        out.append(owner_tuple(owner, obj_type, dst))
    for fl in flows:
        src = str(fl.get("id") or "")
        dst = flow_map.get(src)
        obj_type = _flow_object_type(fl.get("flow_type"))
        if not dst or not obj_type:
            continue
        owner = user_map.get(str(fl.get("user_id") or ""))
        if not owner:
            raise ValueError(f"flow {src} owner 未映射, 拒绝写 OpenFGA")
        out.append(owner_tuple(owner, obj_type, dst))
    for a in assistants:
        src = str(a.get("id") or "")
        dst = asst_map.get(src)
        if not dst:
            continue
        owner = user_map.get(str(a.get("user_id") or ""))
        if not owner:
            raise ValueError(f"assistant {src} owner 未映射, 拒绝写 OpenFGA")
        out.append(owner_tuple(owner, "assistant", dst))
    return out


def merge_tuples(*groups: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for group in groups:
        for row in group:
            key = (row["user"], row["relation"], row["object"])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out


def chunk_tuples(tuples: list[dict], size: int = WRITE_CHUNK) -> list[list[dict]]:
    return [tuples[i : i + size] for i in range(0, len(tuples), size)]


def write_body(tuples: list[dict], model_id: str | None = None) -> dict:
    body: dict = {
        "writes": {
            "tuple_keys": [
                {"user": t["user"], "relation": t["relation"], "object": t["object"]}
                for t in tuples
            ],
            # 续跑幂等: 已写入的 owner 不再 400
            "on_duplicate": "ignore",
        }
    }
    if model_id:
        body["authorization_model_id"] = model_id
    return body


def delete_body(tuples: list[dict], model_id: str | None = None) -> dict:
    body: dict = {
        "deletes": {
            "tuple_keys": [
                {"user": t["user"], "relation": t["relation"], "object": t["object"]}
                for t in tuples
            ]
        }
    }
    if model_id:
        body["authorization_model_id"] = model_id
    return body
