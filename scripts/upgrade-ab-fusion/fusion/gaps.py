"""B 独有模型/工具缺口清单: 不自动建行, 只列出需在 A 重配后再填 map 的项."""

from __future__ import annotations

from pathlib import Path

from fusion.sql import load_csv, load_table, write_csv


def _rows_from_map(path: Path, src_key: str, kind: str) -> list[dict]:
    out = []
    for row in load_csv(path):
        action = (row.get("action") or "").strip()
        dst = (
            row.get("a_model_id") or row.get("a_tool_id") or row.get("a_id") or ""
        ).strip()
        if action == "bind" and dst:
            continue
        out.append(
            {
                "kind": kind,
                "b_id": row.get(src_key) or "",
                "action": action or "unmapped",
                "note": row.get("note")
                or row.get("reason")
                or "需在 A 重配后再填 map, 禁止拷密钥",
            }
        )
    return out


def _rows_from_manual(path: Path, src_key: str, kind: str) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for row in load_table(path):
        out.append(
            {
                "kind": kind,
                "b_id": row.get(src_key)
                or row.get("b_model_id")
                or row.get("b_tool_id")
                or "",
                "action": "manual",
                "note": row.get("reason") or row.get("note") or "",
            }
        )
    return out


def collect_gaps(map_dir: Path, propose_dir: Path | None = None) -> list[dict]:
    """从已签字 map 和 propose manual/conflict 收集缺口. 同 b_id 去重."""
    rows = []
    rows.extend(_rows_from_map(map_dir / "model-map.csv", "b_model_id", "model"))
    rows.extend(_rows_from_map(map_dir / "tool-map.csv", "b_tool_id", "tool"))
    src = propose_dir or map_dir
    rows.extend(_rows_from_manual(src / "model-map.manual.csv", "b_model_id", "model"))
    rows.extend(_rows_from_manual(src / "tool-map.manual.csv", "b_tool_id", "tool"))
    rows.extend(
        _rows_from_manual(src / "model-map.conflicts.csv", "b_model_id", "model")
    )
    rows.extend(_rows_from_manual(src / "tool-map.conflicts.csv", "b_tool_id", "tool"))
    seen: set[tuple[str, str]] = set()
    uniq = []
    for row in rows:
        key = (row["kind"], row["b_id"])
        if not row["b_id"] or key in seen:
            continue
        seen.add(key)
        uniq.append(row)
    return uniq


def write_gaps(path: Path, rows: list[dict]) -> None:
    write_csv(path, ["kind", "b_id", "action", "note"], rows, delimiter="\t")
