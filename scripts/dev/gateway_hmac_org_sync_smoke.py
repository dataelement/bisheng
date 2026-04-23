#!/usr/bin/env python3
"""Smoke test: F014 POST /api/v1/departments/sync with HMAC (via Gateway or direct bisheng).

Examples:
  python scripts/dev/gateway_hmac_org_sync_smoke.py --base http://127.0.0.1:8180
  python scripts/dev/gateway_hmac_org_sync_smoke.py --base http://127.0.0.1:7860
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request


def sign(method: str, path: str, raw_body: bytes, secret: str) -> str:
    msg = f"{method.upper()}\n{path}\n".encode("utf-8") + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8180", help="Gateway or bisheng base URL")
    p.add_argument(
        "--secret",
        default="bisheng-local-hmac-20260422",
        help="Must match bisheng sso_sync.gateway_hmac_secret",
    )
    p.add_argument("--path", default="/api/v1/departments/sync")
    args = p.parse_args()

    base = args.base.rstrip("/")
    path = args.path
    if not path.startswith("/"):
        path = "/" + path

    ts = 1_710_000_000
    body_obj = {
        "upsert": [
            {
                "external_id": "smoke-dept-1",
                "name": "HMAC Smoke Dept",
                "parent_external_id": None,
                "sort": 0,
                "ts": ts,
            }
        ],
        "remove": [],
        "source_ts": ts,
    }
    raw = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = sign("POST", path, raw, args.secret)

    url = base + path
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Signature": sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = resp.read().decode("utf-8", errors="replace")
            print(resp.status, out[:2000])
            return 0 if resp.status == 200 else 1
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(e.code, err[:2000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
