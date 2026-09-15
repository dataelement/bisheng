#!/usr/bin/env python3
"""对比 start/freeze 水位, 写出 created/updated/deleted TSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.watermark import (
    WATERMARK_TABLES,
    diff_snapshot,
    flatten_diff,
    load_id_snapshot,
    write_diff_tsv,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--freeze", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    start_dir = Path(args.start)
    freeze_dir = Path(args.freeze)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[dict] = []
    updated: list[dict] = []
    deleted: list[dict] = []
    all_rows: list[dict] = []
    for table, entity in WATERMARK_TABLES:
        start_ids = load_id_snapshot(start_dir / f"{table}-ids.tsv")
        freeze_ids = load_id_snapshot(freeze_dir / f"{table}-ids.tsv")
        diff = diff_snapshot(start_ids, freeze_ids)
        rows = flatten_diff(entity, diff)
        all_rows.extend(rows)
        for row in rows:
            if row["change"] == "created":
                created.append(row)
            elif row["change"] == "updated":
                updated.append(row)
            elif row["change"] == "deleted":
                deleted.append(row)
    write_diff_tsv(out_dir / "incr-all.tsv", all_rows)
    write_diff_tsv(out_dir / "incr-created.tsv", created)
    write_diff_tsv(out_dir / "incr-updated.tsv", updated)
    write_diff_tsv(out_dir / "incr-deleted.tsv", deleted)
    print(
        f"created={len(created)} updated={len(updated)} deleted={len(deleted)} -> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
