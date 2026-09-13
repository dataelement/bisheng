#!/usr/bin/env python3
"""Query the read-only BiSheng knowledge endpoints (list + retrieve)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

LIST_TYPES = {"space": 3, "doc": 0}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--list-knowledge-bases",
        choices=sorted(LIST_TYPES),
        help="List knowledge spaces or document libraries the token can see, then exit.",
    )
    parser.add_argument("--cursor", help="next_cursor from a previous listing page.")
    parser.add_argument("--query")
    parser.add_argument("--knowledge-base-id", action="append", type=int)
    parser.add_argument("--top-k", type=int, default=10)
    return parser.parse_args()


def _call(url: str, token: str, body: bytes | None = None) -> int:
    request = Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Surface the API's business error body: its status_code (e.g. 26044
        # data-scope restricted, 26040 capability off) tells the agent which
        # action to take — see references/api.md.
        detail = exc.read().decode("utf-8", "replace")
        print(f"knowledge search failed: HTTP {exc.code}", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"knowledge search failed: {exc}", file=sys.stderr)
        return 1
    return 0


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
    base = args.base_url.rstrip("/")

    if args.list_knowledge_bases:
        params = {"type": LIST_TYPES[args.list_knowledge_bases], "page_size": 50}
        if args.cursor:
            params["cursor"] = args.cursor
        return _call(f"{base}/api/v2/filelib/?{urlencode(params)}", token)

    if not args.query or not args.knowledge_base_id:
        print(
            "--query and --knowledge-base-id are required (or use --list-knowledge-bases)",
            file=sys.stderr,
        )
        return 2
    body = json.dumps(
        {
            "query": args.query,
            "knowledge_base_ids": args.knowledge_base_id,
            "top_k": args.top_k,
        }
    ).encode("utf-8")
    return _call(f"{base}/api/v2/filelib/retrieve", token, body)


if __name__ == "__main__":
    raise SystemExit(main())
