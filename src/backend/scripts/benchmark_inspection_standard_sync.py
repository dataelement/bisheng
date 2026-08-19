#!/usr/bin/env python3
"""HTTP benchmark for POST /api/v2/filelib/inspection-standard/sync.

Run from ``src/backend``::

    bash scripts/benchmark_inspection_standard_sync.sh --mode per-dept

Modes:
- ``per-dept`` (recommended): one HTTP request per CREATE_DEPT_ID
- ``single-request``: all departments in one request (stress test)

Environment:
- ``INSPECTION_STANDARD_SYNC_TOKEN`` or ``FILELIB_SYNC_TOKEN``
- ``INSPECTION_STANDARD_SYNC_BASE_URL`` or ``FILELIB_SYNC_BASE_URL``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from inspection_standard_bulk_factory import (  # noqa: E402
    DEFAULT_DEPT_COUNT,
    DEFAULT_RECORDS_PER_DEPT,
    build_bulk_payload_dict,
    build_create_dept_id,
)

DEFAULT_BASE_URL = "http://127.0.0.1:7860"
SYNC_PATH = "/api/v2/filelib/inspection-standard/sync"


@dataclass
class RequestResult:
    label: str
    http_status: int
    elapsed_seconds: float
    payload_bytes: int
    business_status: int | None
    group_count: int | None
    file_count: int | None
    error_message: str | None
    ok: bool


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


def _payload_size_bytes(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _parse_response(label: str, response: httpx.Response, elapsed_seconds: float, payload_bytes: int) -> RequestResult:
    business_status: int | None = None
    group_count: int | None = None
    file_count: int | None = None
    error_message: str | None = None
    ok = False

    if "application/json" in response.headers.get("content-type", ""):
        try:
            body = response.json()
            business_status = body.get("status_code")
            data = body.get("data") or {}
            group_count = data.get("group_count")
            files = data.get("files") or []
            file_count = len(files) if isinstance(files, list) else None
            error_message = body.get("status_message")
            ok = response.status_code == 200 and business_status == 200
        except json.JSONDecodeError:
            error_message = response.text[:500]
    else:
        error_message = response.text[:500]

    return RequestResult(
        label=label,
        http_status=response.status_code,
        elapsed_seconds=round(elapsed_seconds, 2),
        payload_bytes=payload_bytes,
        business_status=business_status,
        group_count=group_count,
        file_count=file_count,
        error_message=error_message,
        ok=ok,
    )


def _post_payload(
    *,
    client: httpx.Client,
    url: str,
    token: str,
    payload: dict,
    label: str,
) -> RequestResult:
    payload_bytes = _payload_size_bytes(payload)
    started = time.perf_counter()
    response = client.post(
        url,
        headers={
            "X-Developer-Token": token,
            "Content-Type": "application/json",
        },
        json=payload,
    )
    elapsed = time.perf_counter() - started
    return _parse_response(label, response, elapsed, payload_bytes)


def _print_result(result: RequestResult) -> None:
    size_mb = result.payload_bytes / 1024 / 1024
    status = "OK" if result.ok else "FAIL"
    print(
        f"[{status}] {result.label} "
        f"http={result.http_status} business={result.business_status} "
        f"groups={result.group_count} files={result.file_count} "
        f"payload={size_mb:.2f}MB elapsed={result.elapsed_seconds}s"
    )
    if not result.ok and result.error_message:
        print(f"       message={result.error_message}")


def run_benchmark(
    *,
    base_url: str,
    token: str,
    mode: str,
    dept_count: int,
    records_per_dept: int,
    start_time: str,
    end_time: str,
    timeout: float,
    dry_run: bool,
    save_payload: Path | None,
) -> int:
    url = f"{base_url.rstrip('/')}{SYNC_PATH}"
    print(f"[benchmark] target={url}")
    print(
        f"[benchmark] mode={mode} dept_count={dept_count} "
        f"records_per_dept={records_per_dept} timeout={timeout}s dry_run={dry_run}"
    )

    results: list[RequestResult] = []
    overall_started = time.perf_counter()

    if mode == "single-request":
        payload = build_bulk_payload_dict(
            dept_count=dept_count,
            records_per_dept=records_per_dept,
            start_time=start_time,
            end_time=end_time,
        )
        if save_payload is not None:
            save_payload.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            print(f"[benchmark] saved payload -> {save_payload}")
        print(
            f"[benchmark] payload standards={len(payload['data']['check_standards'])} "
            f"items={len(payload['data']['check_standard_items'])} "
            f"bytes={_payload_size_bytes(payload) / 1024 / 1024:.2f}MB"
        )
        if dry_run:
            return 0
        with httpx.Client(timeout=timeout) as client:
            results.append(_post_payload(client=client, url=url, token=token, payload=payload, label="all-depts"))
    elif mode == "per-dept":
        with httpx.Client(timeout=timeout) as client:
            for dept_idx in range(dept_count):
                label = build_create_dept_id(dept_idx)
                payload = build_bulk_payload_dict(
                    dept_count=dept_count,
                    records_per_dept=records_per_dept,
                    dept_indices=[dept_idx],
                    start_time=start_time,
                    end_time=end_time,
                )
                if save_payload is not None and dept_idx == 0:
                    save_payload.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    print(f"[benchmark] saved sample payload -> {save_payload}")
                print(
                    f"[benchmark] {label} standards={len(payload['data']['check_standards'])} "
                    f"items={len(payload['data']['check_standard_items'])} "
                    f"bytes={_payload_size_bytes(payload) / 1024 / 1024:.2f}MB"
                )
                if dry_run:
                    continue
                results.append(
                    _post_payload(client=client, url=url, token=token, payload=payload, label=label),
                )
                _print_result(results[-1])
        if dry_run:
            return 0
    else:
        print(f"[benchmark] unsupported mode: {mode}", file=sys.stderr)
        return 1

    if mode == "single-request":
        for result in results:
            _print_result(result)

    overall_elapsed = round(time.perf_counter() - overall_started, 2)
    ok_count = sum(1 for item in results if item.ok)
    print(
        f"[benchmark] summary requests={len(results)} ok={ok_count} "
        f"failed={len(results) - ok_count} total_elapsed={overall_elapsed}s"
    )
    return 0 if ok_count == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help=f"API base URL (default: {DEFAULT_BASE_URL} or env)")
    parser.add_argument("--token", default=None, help="Developer token (or env INSPECTION_STANDARD_SYNC_TOKEN)")
    parser.add_argument(
        "--mode",
        choices=("per-dept", "single-request"),
        default="per-dept",
        help="per-dept=one request per CREATE_DEPT_ID; single-request=all departments in one POST",
    )
    parser.add_argument("--dept-count", type=int, default=DEFAULT_DEPT_COUNT)
    parser.add_argument("--records-per-dept", type=int, default=DEFAULT_RECORDS_PER_DEPT)
    parser.add_argument("--start-time", default="2026-08-01T00:00:00")
    parser.add_argument("--end-time", default="2026-08-14T23:59:59")
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Generate payloads only, do not call API")
    parser.add_argument("--save-payload", type=Path, default=None, help="Optional path to save generated JSON payload")
    args = parser.parse_args()

    token = _resolve_token(args.token)
    if not token and not args.dry_run:
        print(
            "[benchmark] --token or INSPECTION_STANDARD_SYNC_TOKEN / FILELIB_SYNC_TOKEN is required",
            file=sys.stderr,
        )
        return 1

    return run_benchmark(
        base_url=_resolve_base_url(args.base_url),
        token=token or "",
        mode=args.mode,
        dept_count=max(1, int(args.dept_count)),
        records_per_dept=max(1, int(args.records_per_dept)),
        start_time=str(args.start_time),
        end_time=str(args.end_time),
        timeout=float(args.timeout),
        dry_run=bool(args.dry_run),
        save_payload=args.save_payload.expanduser().resolve() if args.save_payload else None,
    )


if __name__ == "__main__":
    sys.exit(main())
