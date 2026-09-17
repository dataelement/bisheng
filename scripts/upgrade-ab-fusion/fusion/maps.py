"""加载已签字的映射 CSV. 列约定: src=B, dst=A."""

from __future__ import annotations

from pathlib import Path

from fusion.sql import load_csv, write_csv

# bind/dedupe 的 dst 是 A 原对象, 回滚禁止 DELETE
SKIP_ROLLBACK_ACTIONS = frozenset({"bind", "dedupe", "skip", "manual", "conflict"})


def load_map(path: Path, src_key: str, dst_key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in load_csv(path):
        src = (row.get(src_key) or "").strip()
        dst = (row.get(dst_key) or "").strip()
        action = (row.get("action") or "").strip()
        if not src:
            continue
        if action in {"skip", "manual", "conflict"}:
            continue
        if dst:
            out[src] = dst
    return out


def require_mapped_model(
    kind: str, src: str, model: str | None, model_map: dict[str, str]
) -> str:
    """非空模型必须在 map 中. 禁止把 B 的数字 id 原样写入 A."""
    text = str(model or "").strip()
    if not text:
        return ""
    if text not in model_map:
        raise ValueError(f"{kind} {src} 模型 {text} 未映射")
    return model_map[text]


def load_tool_key_map(path: Path) -> dict[str, str]:
    """tool-map.csv 可选列 b_tool_key/a_tool_key; 仅两边不同才需要改 JSON."""
    out: dict[str, str] = {}
    for row in load_csv(path):
        src = (row.get("b_tool_key") or "").strip()
        dst = (row.get("a_tool_key") or "").strip()
        if src and dst and src != dst:
            out[src] = dst
    return out


def load_user_map(path: Path) -> dict[str, str]:
    return load_map(path, "b_user_id", "a_user_id")


def load_tenant_map(path: Path) -> dict[str, str]:
    return load_map(path, "b_tenant_id", "a_tenant_id")


def require_mapped(kind: str, src_id: str | int | None, table: dict[str, str]) -> str:
    key = "" if src_id is None else str(src_id)
    if key not in table:
        raise ValueError(f"{kind} {key} 未映射")
    return table[key]


def fill_dst_column(
    path: Path, src_key: str, dst_key: str, alloc: dict[str, str]
) -> None:
    """把 create 分配到的 A ID 填回已签字 csv, 不改其它列."""
    if not alloc:
        return
    rows = load_csv(path)
    if not rows:
        write_csv(
            path,
            [src_key, dst_key, "action"],
            [
                {src_key: src, dst_key: dst, "action": "create"}
                for src, dst in alloc.items()
            ],
        )
        return
    fields = list(rows[0].keys())
    if dst_key not in fields:
        fields.insert(1, dst_key)
    for row in rows:
        src = (row.get(src_key) or "").strip()
        if src in alloc and not (row.get(dst_key) or "").strip():
            row[dst_key] = alloc[src]
    write_csv(path, fields, rows)


def write_pair_csv(
    path: Path,
    src_key: str,
    dst_key: str,
    rows: list[dict],
    src_field: str,
    dst_field: str,
) -> None:
    out = []
    for row in rows:
        src = str(row.get(src_field) or "")
        dst = str(row.get(dst_field) or "")
        if src and dst:
            out.append(
                {
                    src_key: src,
                    dst_key: dst,
                    "action": row.get("action") or "create",
                }
            )
    write_csv(path, [src_key, dst_key, "action"], out)


def write_alloc_csv(
    path: Path,
    src_key: str,
    dst_key: str,
    alloc: dict[str, str],
    action: str = "create",
) -> None:
    write_csv(
        path,
        [src_key, dst_key, "action"],
        [
            {src_key: src, dst_key: dst, "action": action}
            for src, dst in alloc.items()
            if src and dst
        ],
    )


def upsert_alloc(
    path: Path,
    src_key: str,
    dst_key: str,
    alloc: dict[str, str],
    action: str = "create",
) -> None:
    if path.exists() and load_csv(path):
        fill_dst_column(path, src_key, dst_key, alloc)
    else:
        write_alloc_csv(path, src_key, dst_key, alloc, action=action)


def persist_runtime_maps(map_dir: Path, extra: dict | None) -> None:
    """把本域生成的 ID 映射写回 maps 目录, 供后序域重写引用."""
    if not extra:
        return
    map_dir.mkdir(parents=True, exist_ok=True)
    if extra.get("user_alloc"):
        upsert_alloc(
            map_dir / "user-map.csv", "b_user_id", "a_user_id", extra["user_alloc"]
        )
    if extra.get("group_alloc"):
        upsert_alloc(
            map_dir / "group-map.csv", "b_group_id", "a_group_id", extra["group_alloc"]
        )
    if extra.get("role_alloc"):
        upsert_alloc(
            map_dir / "role-map.csv", "b_role_id", "a_role_id", extra["role_alloc"]
        )
    if extra.get("dept_as_group"):
        fill_dst_column(
            map_dir / "dept-map.csv", "b_dept_pk", "a_group_id", extra["dept_as_group"]
        )
    if extra.get("knowledge_maps"):
        write_pair_csv(
            map_dir / "knowledge-map.csv",
            "b_id",
            "a_id",
            extra["knowledge_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("file_maps"):
        write_pair_csv(
            map_dir / "file-map.csv", "b_id", "a_id", extra["file_maps"], "b_id", "a_id"
        )
    if extra.get("flow_maps"):
        write_pair_csv(
            map_dir / "flow-map.csv", "b_id", "a_id", extra["flow_maps"], "b_id", "a_id"
        )
    if extra.get("flowversion_maps"):
        write_pair_csv(
            map_dir / "flowversion-map.csv",
            "b_id",
            "a_id",
            extra["flowversion_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("assistant_maps"):
        write_pair_csv(
            map_dir / "assistant-map.csv",
            "b_id",
            "a_id",
            extra["assistant_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("session_maps"):
        write_pair_csv(
            map_dir / "chat-map.csv",
            "b_id",
            "a_id",
            extra["session_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("message_maps"):
        write_pair_csv(
            map_dir / "message-map.csv",
            "b_id",
            "a_id",
            extra["message_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("qa_maps"):
        write_pair_csv(
            map_dir / "qa-map.csv", "b_id", "a_id", extra["qa_maps"], "b_id", "a_id"
        )
    if extra.get("tag_maps"):
        write_pair_csv(
            map_dir / "tag-map.csv", "b_id", "a_id", extra["tag_maps"], "b_id", "a_id"
        )
    if extra.get("tag_link_maps"):
        write_pair_csv(
            map_dir / "tag-link-map.csv",
            "b_id",
            "a_id",
            extra["tag_link_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("dictionary_maps"):
        write_pair_csv(
            map_dir / "dictionary-map.csv",
            "b_id",
            "a_id",
            extra["dictionary_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("citation_maps"):
        write_pair_csv(
            map_dir / "citation-map.csv",
            "b_id",
            "a_id",
            extra["citation_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("citation_relation_maps"):
        write_pair_csv(
            map_dir / "citation-relation-map.csv",
            "b_id",
            "a_id",
            extra["citation_relation_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("mark_task_maps"):
        write_pair_csv(
            map_dir / "mark-task-map.csv",
            "b_id",
            "a_id",
            extra["mark_task_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("mark_record_maps"):
        write_pair_csv(
            map_dir / "mark-record-map.csv",
            "b_id",
            "a_id",
            extra["mark_record_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("mark_app_user_maps"):
        write_pair_csv(
            map_dir / "mark-app-user-map.csv",
            "b_id",
            "a_id",
            extra["mark_app_user_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("report_maps"):
        write_pair_csv(
            map_dir / "report-map.csv",
            "b_id",
            "a_id",
            extra["report_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("tool_type_maps"):
        write_pair_csv(
            map_dir / "tool-type-map.csv",
            "b_id",
            "a_id",
            extra["tool_type_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("role_access_maps"):
        write_pair_csv(
            map_dir / "role-access-map.csv",
            "b_id",
            "a_id",
            extra["role_access_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("group_resource_maps"):
        write_pair_csv(
            map_dir / "group-resource-map.csv",
            "b_id",
            "a_id",
            extra["group_resource_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("share_link_maps"):
        write_pair_csv(
            map_dir / "share-link-map.csv",
            "b_id",
            "a_id",
            extra["share_link_maps"],
            "b_id",
            "a_id",
        )
    if extra.get("audit_maps"):
        write_pair_csv(
            map_dir / "audit-map.csv",
            "b_id",
            "a_id",
            extra["audit_maps"],
            "b_id",
            "a_id",
        )
