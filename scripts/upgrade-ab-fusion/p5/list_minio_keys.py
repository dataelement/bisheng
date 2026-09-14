#!/usr/bin/env python3
"""从空间 JSON 列出要拉的 MinIO 对象: 原文件 / 预览 / 缩略图。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def extra_object_keys(file_row: dict) -> list[tuple[str, str]]:
    """返回 (本地文件名后缀, object_key)。原文件后缀为空字符串, 本地名= a_file_id。"""
    out: list[tuple[str, str]] = []
    preview = (file_row.get("preview_file_object_name") or "").strip()
    if preview:
        out.append((".preview", preview))
    thumb = (file_row.get("thumbnails") or "").strip()
    if thumb and not thumb.startswith("["):
        out.append((".thumb", thumb))
    return out


def list_pull_jobs(payload: dict) -> list[tuple[str, str, str]]:
    """(a_file_id, local_name, object_key)"""
    jobs: list[tuple[str, str, str]] = []
    for row in payload.get("files") or []:
        if int(row.get("file_type") or 1) != 1:
            continue
        fid = str(int(row["id"]))
        src = (row.get("object_name") or "").strip()
        if src:
            jobs.append((fid, fid, src))
        for suffix, key in extra_object_keys(row):
            jobs.append((fid, f"{fid}{suffix}", key))
    return jobs


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for fid, local_name, key in list_pull_jobs(data):
        print(f"{fid}\t{local_name}\t{key}")


if __name__ == "__main__":
    main()
