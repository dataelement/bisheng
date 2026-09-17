"""按 B 导出基线核对本批映射数量. A 原空间计数不得下降."""

from __future__ import annotations

from pathlib import Path

from fusion.maps import load_map
from fusion.sql import load_table


def expected_business_counts(
    dump: dict, migrate_b_spaces: bool = False
) -> dict[str, int]:
    """从 dump 计算应迁条数. type=3 默认不计入."""
    k_ok: list[str] = []
    for k in dump.get("knowledges") or []:
        ktype = int(k.get("type") or 0)
        if ktype == 3 and not migrate_b_spaces:
            continue
        kid = str(k.get("id") or "")
        if kid:
            k_ok.append(kid)
    kset = set(k_ok)
    files = [
        f for f in dump.get("files") or [] if str(f.get("knowledge_id") or "") in kset
    ]
    qas = [q for q in dump.get("qas") or [] if str(q.get("knowledge_id") or "") in kset]
    session_ids = {str(s.get("chat_id") or "") for s in dump.get("sessions") or []}
    messages = [
        m
        for m in dump.get("messages") or []
        if str(m.get("chat_id") or "") in session_ids
    ]
    return {
        "knowledge": len(k_ok),
        "file": len(files),
        "qa": len(qas),
        "flow": len(dump.get("flows") or []),
        "assistant": len(dump.get("assistants") or []),
        "session": len(dump.get("sessions") or []),
        "message": len(messages),
    }


def map_counts(map_dir: Path) -> dict[str, int]:
    specs = (
        ("knowledge", "knowledge-map.csv", "b_id", "a_id"),
        ("file", "file-map.csv", "b_id", "a_id"),
        ("qa", "qa-map.csv", "b_id", "a_id"),
        ("flow", "flow-map.csv", "b_id", "a_id"),
        ("assistant", "assistant-map.csv", "b_id", "a_id"),
        ("session", "chat-map.csv", "b_id", "a_id"),
        ("message", "message-map.csv", "b_id", "a_id"),
    )
    out: dict[str, int] = {}
    for name, filename, src, dst in specs:
        path = map_dir / filename
        out[name] = len(load_map(path, src, dst)) if path.exists() else 0
    return out


def baseline_num(path: Path, metric: str) -> int | None:
    if not path.exists():
        return None
    for row in load_table(path):
        if (row.get("metric") or "") == metric:
            try:
                return int(row.get("value") or 0)
            except ValueError:
                return None
    return None


def compare_counts(
    *,
    expected: dict[str, int],
    mapped: dict[str, int],
    a_space_base: int | None,
    a_space_now: int | None,
    a_space_file_base: int | None = None,
    a_space_file_now: int | None = None,
    hard: tuple[str, ...] = (
        "knowledge",
        "file",
        "qa",
        "flow",
        "assistant",
        "session",
        "message",
    ),
) -> dict:
    """hard 项 mapped 必须等于 expected. A 空间不得下降."""
    errors: list[str] = []
    warns: list[str] = []
    if (
        a_space_base is not None
        and a_space_now is not None
        and a_space_now < a_space_base
    ):
        errors.append(f"A 空间数从 {a_space_base} 变成 {a_space_now}")
    if (
        a_space_file_base is not None
        and a_space_file_now is not None
        and a_space_file_now < a_space_file_base
    ):
        errors.append(f"A 空间文件数从 {a_space_file_base} 变成 {a_space_file_now}")
    for key in hard:
        exp = expected.get(key, 0)
        got = mapped.get(key, 0)
        if got != exp:
            errors.append(f"{key} 期望 {exp} 条映射, 实际 {got}")
    return {
        "ok": not errors,
        "errors": errors,
        "warns": warns,
        "expected": expected,
        "mapped": mapped,
    }
