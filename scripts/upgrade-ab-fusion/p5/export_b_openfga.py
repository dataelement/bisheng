#!/usr/bin/env python3
"""从 B 本机 OpenFGA 分页导出全部 Tuple, 写成 jsonl. 失败时由 shell 忽略."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def store_id(base: str, name: str) -> str:
    data = _get(f"{base.rstrip('/')}/stores")
    hit = next((s for s in data.get("stores") or [] if s.get("name") == name), None)
    if not hit:
        raise SystemExit(f"no store {name}")
    return hit["id"]


def dump_tuples(base: str, sid: str, out: Path) -> int:
    n = 0
    token = None
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        while True:
            body: dict = {"page_size": 100}
            if token:
                body["continuation_token"] = token
            data = _post(f"{base.rstrip('/')}/stores/{sid}/read", body)
            for row in data.get("tuples") or []:
                key = row.get("key") or row
                f.write(json.dumps(key, ensure_ascii=False) + "\n")
                n += 1
            token = data.get("continuation_token") or data.get("continuationToken")
            if not token:
                break
    return n


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    name = sys.argv[2] if len(sys.argv) > 2 else "bisheng"
    out = Path(sys.argv[3] if len(sys.argv) > 3 else "logs/p5/b-openfga-tuples.jsonl")
    try:
        sid = store_id(base, name)
        n = dump_tuples(base, sid, out)
    except (urllib.error.URLError, TimeoutError, OSError, SystemExit) as exc:
        print(f"export-b-openfga skip: {exc}", file=sys.stderr)
        return 2
    print(f"tuples={n} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
