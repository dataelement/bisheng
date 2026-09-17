#!/usr/bin/env python3
"""用 B 文件导出 + file-map 重建 MinIO 拷贝任务. 续跑时 30-apply 可能清掉 minio-jobs.tsv."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.maps import load_map
from fusion.minio_keys import jobs_from_exported_files, merge_jobs_tsv


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dump", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    file_map = load_map(Path(args.maps) / "file-map.csv", "b_id", "a_id")
    jobs = jobs_from_exported_files(dump.get("files") or [], file_map)
    a_keys = set(dump.get("a_minio_keys") or [])
    merged = merge_jobs_tsv(Path(args.out), jobs, a_keys)
    print(f"minio-jobs={len(merged)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
