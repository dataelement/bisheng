#!/usr/bin/env python3
"""在 backend 容器内对当前环境的 MinIO 做 get/put/exists。密码走容器配置, 不写进脚本。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _client():
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

    return get_minio_storage_sync()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_get(object_name: str, out_path: Path) -> None:
    client = _client()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client.minio_client_sync.fget_object(client.bucket, object_name, str(out_path))
    stat = out_path.stat()
    print(
        json.dumps(
            {
                "object_name": object_name,
                "size": stat.st_size,
                "sha256": _sha256(out_path),
            }
        )
    )


def cmd_put(object_name: str, in_path: Path) -> None:
    client = _client()
    if not in_path.is_file():
        raise SystemExit(f"missing file {in_path}")
    if client.object_exists_sync(object_name=object_name):
        raise SystemExit(f"refuse overwrite existing object {object_name}")
    client.put_object_sync(object_name=object_name, file=str(in_path))
    print(
        json.dumps(
            {
                "object_name": object_name,
                "size": in_path.stat().st_size,
                "sha256": _sha256(in_path),
            }
        )
    )


def cmd_exists(object_name: str) -> None:
    client = _client()
    ok = client.object_exists_sync(object_name=object_name)
    print(json.dumps({"object_name": object_name, "exists": bool(ok)}))
    sys.exit(0 if ok else 1)


def cmd_rm(object_name: str) -> None:
    client = _client()
    client.minio_client_sync.remove_object(client.bucket, object_name)
    print(json.dumps({"object_name": object_name, "removed": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("object_name")
    g.add_argument("out_path")
    p = sub.add_parser("put")
    p.add_argument("object_name")
    p.add_argument("in_path")
    e = sub.add_parser("exists")
    e.add_argument("object_name")
    r = sub.add_parser("rm")
    r.add_argument("object_name")
    args = parser.parse_args()
    if args.cmd == "get":
        cmd_get(args.object_name, Path(args.out_path))
    elif args.cmd == "put":
        cmd_put(args.object_name, Path(args.in_path))
    elif args.cmd == "exists":
        cmd_exists(args.object_name)
    else:
        cmd_rm(args.object_name)


if __name__ == "__main__":
    main()
