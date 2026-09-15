#!/usr/bin/env python3
"""冻结水位 vs 当前: 有漂移则失败."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.watermark import (
    WATERMARK_TABLES,
    freeze_drift,
    freeze_id_drift,
    load_id_snapshot,
    load_summary,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--freeze", required=True)
    p.add_argument("--current", required=True)
    args = p.parse_args()
    freeze_dir = Path(args.freeze)
    current_dir = Path(args.current)
    errors = freeze_drift(
        load_summary(freeze_dir / "summary.tsv"),
        load_summary(current_dir / "summary.tsv"),
    )
    for table, _entity in WATERMARK_TABLES:
        errors.extend(
            f"{table} {e}"
            for e in freeze_id_drift(
                load_id_snapshot(freeze_dir / f"{table}-ids.tsv"),
                load_id_snapshot(current_dir / f"{table}-ids.tsv"),
            )
        )
    if errors:
        print("freeze drift:", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
        return 2
    print("freeze OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
