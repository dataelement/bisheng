#!/usr/bin/env python3
"""Verify POST /api/v2/filelib/inspection-standard/sync with a developer token.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/verify_inspection_standard_sync.py \\
      --token bst_xxx \\
      --payload scripts/examples/inspection_standard_sync_payload.example.json

    bash scripts/verify_inspection_standard_sync.sh \\
      --token bst_xxx \\
      --payload scripts/examples/inspection_standard_sync_payload.example.json

Environment fallbacks:
- ``INSPECTION_STANDARD_SYNC_TOKEN`` or ``FILELIB_SYNC_TOKEN`` when ``--token`` is omitted
- ``INSPECTION_STANDARD_SYNC_BASE_URL`` or ``FILELIB_SYNC_BASE_URL`` when ``--base-url`` is omitted
  (default: http://10.171.0.50:7860)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import httpx  # noqa: E402

DEFAULT_BASE_URL = "http://10.171.0.50:7860"
SYNC_PATH = "/api/v2/filelib/inspection-standard/sync"


def _load_payload(payload_path: Path) -> dict:
    raw = payload_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload file must contain a JSON object")
    for key in ("start_time", "end_time", "data"):
        if key not in data:
            raise ValueError(f"payload must include {key!r}")
    if not isinstance(data.get("data"), dict):
        raise ValueError("payload.data must be an object")
    return data


def _format_body(body: object) -> str:
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, indent=2)
    return str(body)


def _resolve_token(explicit_token: str | None) -> str | None:
    if explicit_token and str(explicit_token).strip():
        return str(explicit_token).strip()
    for env_key in ("INSPECTION_STANDARD_SYNC_TOKEN", "FILELIB_SYNC_TOKEN"):
        value = os.environ.get(env_key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _resolve_base_url(explicit_base_url: str | None) -> str:
    if explicit_base_url and str(explicit_base_url).strip():
        return str(explicit_base_url).strip()
    for env_key in ("INSPECTION_STANDARD_SYNC_BASE_URL", "FILELIB_SYNC_BASE_URL"):
        value = os.environ.get(env_key)
        if value and str(value).strip():
            return str(value).strip()
    return DEFAULT_BASE_URL


def verify_inspection_standard_sync(
    *,
    base_url: str,
    token: str,
    payload_path: Path,
    timeout: float,
) -> int:
    if not payload_path.is_file():
        print(f"[verify_inspection_standard_sync] payload file not found: {payload_path}", file=sys.stderr)
        return 1

    try:
        payload = _load_payload(payload_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[verify_inspection_standard_sync] invalid payload: {exc}", file=sys.stderr)
        return 1

    url = f"{base_url.rstrip('/')}{SYNC_PATH}"
    headers = {
        "X-Developer-Token": token,
        "Content-Type": "application/json",
    }

    print(f"[verify_inspection_standard_sync] POST {url}")
    print(f"[verify_inspection_standard_sync] payload={payload_path}")
    print(f"[verify_inspection_standard_sync] body={json.dumps(payload, ensure_ascii=False)}")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, json=payload)

    print(f"[verify_inspection_standard_sync] HTTP {response.status_code}")
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            print(_format_body(response.json()))
        except json.JSONDecodeError:
            print(response.text)
    else:
        print(response.text)

    if response.status_code == 200:
        try:
            body = response.json()
        except json.JSONDecodeError:
            return 1
        if body.get("status_code") == 200:
            return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"API base URL (default: {DEFAULT_BASE_URL} or env override)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Developer token (or INSPECTION_STANDARD_SYNC_TOKEN / FILELIB_SYNC_TOKEN)",
    )
    parser.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="Path to JSON request body (start_time, end_time, data)",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="Request timeout in seconds")
    args = parser.parse_args()

    token = _resolve_token(args.token)
    if not token:
        print(
            "[verify_inspection_standard_sync] --token or "
            "INSPECTION_STANDARD_SYNC_TOKEN / FILELIB_SYNC_TOKEN is required",
            file=sys.stderr,
        )
        return 1

    return verify_inspection_standard_sync(
        base_url=_resolve_base_url(args.base_url),
        token=token,
        payload_path=args.payload.expanduser().resolve(),
        timeout=float(args.timeout),
    )


if __name__ == "__main__":
    sys.exit(main())
