#!/usr/bin/env python3
"""对金标对打结果打分. 不连 Milvus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.maps import load_map
from fusion.retrieve_gold import score_jobs
from fusion.sql import write_csv

FIELDS = [
    "b_id",
    "a_collection",
    "ok",
    "overlap_at_k",
    "top1",
    "reason",
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--k", default="5")
    p.add_argument("--min-overlap", default="0.8")
    args = p.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if not cases:
        Path(args.out).write_text("b_id\ta_collection\tok\n", encoding="utf-8")
        print("gold cases=0")
        return 0
    file_map = load_map(Path(args.maps) / "file-map.csv", "b_id", "a_id")
    scored = score_jobs(
        cases,
        file_map=file_map,
        k=int(args.k),
        min_overlap=float(args.min_overlap),
    )
    rows = []
    for row in scored["rows"]:
        rows.append(
            {
                "b_id": row.get("b_id") or "",
                "a_collection": row.get("a_collection") or "",
                "ok": "1" if row.get("ok") else "0",
                "overlap_at_k": f"{row.get('overlap_at_k') or 0:.2f}",
                "top1": "1" if row.get("top1") else "0",
                "reason": row.get("reason") or "",
            }
        )
    write_csv(Path(args.out), FIELDS, rows, delimiter="\t")
    summary = Path(str(args.out) + ".json")
    dump = {
        "ok": scored["ok"],
        "failed": scored["failed"],
        "total": scored["total"],
    }
    summary.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gold total={scored['total']} failed={scored['failed']} -> {args.out}")
    if not scored["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
