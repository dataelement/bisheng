#!/usr/bin/env python3
"""按 dump + maps + 缺口/向量例外生成工作流/助手上线 SQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.flow_publish import gate_assistant, gate_flow, generate_publish_sql
from fusion.maps import load_map
from fusion.sql import load_table, write_csv

GATE_FIELDS = ["kind", "src_id", "dst_id", "ok", "reason"]


def _maps(map_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "user": load_map(map_dir / "user-map.csv", "b_user_id", "a_user_id"),
        "tenant": load_map(map_dir / "tenant-map.csv", "b_tenant_id", "a_tenant_id"),
        "model": load_map(map_dir / "model-map.csv", "b_model_id", "a_model_id"),
        "tool": load_map(map_dir / "tool-map.csv", "b_tool_id", "a_tool_id"),
        "knowledge": load_map(map_dir / "knowledge-map.csv", "b_id", "a_id"),
        "file": load_map(map_dir / "file-map.csv", "b_id", "a_id"),
        "flow": load_map(map_dir / "flow-map.csv", "b_id", "a_id"),
        "assistant": load_map(map_dir / "assistant-map.csv", "b_id", "a_id"),
    }


def _gap_ids(path: Path, kind: str) -> set[str]:
    out = set()
    if not path.exists():
        return out
    for row in load_table(path):
        if (row.get("kind") or "") == kind and row.get("b_id"):
            out.add(str(row["b_id"]))
    return out


def _vector_exception_kids(path: Path) -> set[str]:
    out = set()
    if not path.exists():
        return out
    for row in load_table(path):
        src = (row.get("src_id") or "").strip()
        verdict = (row.get("verdict") or "").strip()
        if src and verdict in {"need_reparse", "pending", "exception"}:
            out.add(src)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dump", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--batch", default="fusion")
    p.add_argument("--gaps", default="")
    p.add_argument("--vector-exceptions", default="")
    args = p.parse_args()
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    maps = _maps(Path(args.maps))
    gap_models = _gap_ids(Path(args.gaps), "model") if args.gaps else set()
    gap_tools = _gap_ids(Path(args.gaps), "tool") if args.gaps else set()
    vec_ex = (
        _vector_exception_kids(Path(args.vector_exceptions))
        if args.vector_exceptions
        else set()
    )
    flow_rows = []
    for fl in dump.get("flows") or []:
        src = str(fl.get("id") or "")
        dst = (maps.get("flow") or {}).get(src, "")
        flow_rows.append(
            gate_flow(
                src_id=src,
                dst_id=dst,
                desired_status=int(fl.get("status") or 1),
                data=fl.get("data"),
                maps=maps,
                gap_model_ids=gap_models,
                gap_tool_ids=gap_tools,
                vector_exception_kids=vec_ex,
            )
        )
    asst_rows = []
    for a in dump.get("assistants") or []:
        src = str(a.get("id") or "")
        dst = (maps.get("assistant") or {}).get(src, "")
        asst_rows.append(
            gate_assistant(
                src_id=src,
                dst_id=dst,
                desired_status=int(a.get("status") or 1),
                model_name=str(a.get("model_name") or ""),
                maps=maps,
                gap_model_ids=gap_models,
            )
        )
    sql = generate_publish_sql(
        batch=args.batch, flow_rows=flow_rows, assistant_rows=asst_rows
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sql, encoding="utf-8")
    gate_rows = []
    for kind, rows in (("flow", flow_rows), ("assistant", asst_rows)):
        for row in rows:
            gate_rows.append(
                {
                    "kind": kind,
                    "src_id": row.get("src_id") or "",
                    "dst_id": row.get("dst_id") or "",
                    "ok": "1" if row.get("ok") else "0",
                    "reason": row.get("reason") or "",
                }
            )
    write_csv(out.parent / "publish-gate.tsv", GATE_FIELDS, gate_rows, delimiter="\t")
    passed = sum(1 for r in gate_rows if r["ok"] == "1")
    print(f"publish passed={passed}/{len(gate_rows)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
