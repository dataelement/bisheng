#!/usr/bin/env python3
"""Query the read-only BiSheng knowledge retrieval endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--knowledge-base-id", action="append", type=int, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    token = os.environ.get("BISHENG_API_KEY", "")
    if not token:
        print("BISHENG_API_KEY is required", file=sys.stderr)
        return 2
    parsed = urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("--base-url must be an absolute HTTP(S) URL", file=sys.stderr)
        return 2

    body = json.dumps(
        {
            "query": args.query,
            "knowledge_base_ids": args.knowledge_base_id,
            "top_k": args.top_k,
        }
    ).encode("utf-8")
    request = Request(
        f"{args.base_url.rstrip('/')}/api/v2/filelib/retrieve",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        print(f"knowledge search failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
