#!/usr/bin/env python3
"""Verify the filelib sync OpenAPI endpoint with a developer token.

Posts multipart ``file`` + ``params`` to ``POST /api/v2/filelib/file/sync``.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/verify_filelib_sync.py \\
      --token bst_xxx \\
      --file /path/to/report.pdf \\
      --params /path/to/sync_params.json

    bash scripts/verify_filelib_sync.sh \\
      --token bst_xxx \\
      --file /path/to/report.pdf \\
      --params /path/to/sync_params.json

``params`` JSON example::

    {
      "external_file_id": "ext-20260728-001",
      "file_name": "report.pdf",
      "department_id": "20491061"
    }

Environment fallbacks:
- ``FILELIB_SYNC_TOKEN`` when ``--token`` is omitted
- ``FILELIB_SYNC_BASE_URL`` when ``--base-url`` is omitted (default: http://127.0.0.1:7860)
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
SYNC_PATH = "/api/v2/filelib/file/sync"


def _load_params(params_path: Path) -> dict:
    raw = params_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("params file must contain a JSON object")
    return data


def _resolve_file_name(params: dict, file_path: Path) -> dict:
    payload = dict(params)
    file_name = str(payload.get("file_name") or "").strip()
    if not file_name:
        payload["file_name"] = file_path.name
    external_file_id = str(payload.get("external_file_id") or "").strip()
    if not external_file_id:
        raise ValueError("params must include non-empty external_file_id")
    return payload


def _format_body(body: object) -> str:
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, indent=2)
    return str(body)


def verify_filelib_sync(
    *,
    base_url: str,
    token: str,
    file_path: Path,
    params_path: Path,
    timeout: float,
) -> int:
    if not file_path.is_file():
        print(f"[verify_filelib_sync] file not found: {file_path}", file=sys.stderr)
        return 1
    if not params_path.is_file():
        print(f"[verify_filelib_sync] params file not found: {params_path}", file=sys.stderr)
        return 1

    try:
        params = _resolve_file_name(_load_params(params_path), file_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[verify_filelib_sync] invalid params: {exc}", file=sys.stderr)
        return 1

    url = f"{base_url.rstrip('/')}{SYNC_PATH}"
    headers = {"X-Developer-Token": token.strip()}
    params_json = json.dumps(params, ensure_ascii=False)

    print(f"[verify_filelib_sync] POST {url}")
    print(f"[verify_filelib_sync] file={file_path}")
    print(f"[verify_filelib_sync] params={params_json}")

    with httpx.Client(timeout=timeout) as client:
        with file_path.open("rb") as handle:
            response = client.post(
                url,
                headers=headers,
                files={
                    "file": (params["file_name"], handle, "application/octet-stream"),
                },
                data={"params": params_json},
            )

    print(f"[verify_filelib_sync] HTTP {response.status_code}")
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
        default=os.environ.get("FILELIB_SYNC_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL} or FILELIB_SYNC_BASE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("FILELIB_SYNC_TOKEN"),
        help="Developer token (or set FILELIB_SYNC_TOKEN)",
    )
    parser.add_argument("--file", required=True, type=Path, help="Path to the file to upload")
    parser.add_argument("--params", required=True, type=Path, help="Path to JSON params file")
    parser.add_argument("--timeout", type=float, default=120.0, help="Request timeout in seconds")
    args = parser.parse_args()

    if not args.token or not str(args.token).strip():
        print("[verify_filelib_sync] --token or FILELIB_SYNC_TOKEN is required", file=sys.stderr)
        return 1

    return verify_filelib_sync(
        base_url=str(args.base_url),
        token=str(args.token),
        file_path=args.file.expanduser().resolve(),
        params_path=args.params.expanduser().resolve(),
        timeout=float(args.timeout),
    )


if __name__ == "__main__":
    sys.exit(main())
