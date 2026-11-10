"""Measure post-development audit timing against the disposable loopback fixture.

Run from src/backend: python scripts/measure_dsh_model_audit.py --base
http://127.0.0.1:8786 --apply. Tokens come from DSH_AUDIT_ADMIN_TOKEN and
DSH_AUDIT_USER_TOKEN; never pass real credentials. Default is read-only preflight.
Only the opt-in test/dsh/audit_local_server fixture is accepted. --apply sends
synthetic model calls and changes tenant 2's modes, restoring its original mode.
No application config, database client, production environment, or SLA is used.
"""

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import httpx  # noqa: E402

ADMIN = "/api/v1/dsh/admin/model-audit"


def percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    return round(values[max(0, math.ceil(quantile * len(values)) - 1)], 3)


def summarize(samples, *, entered_count):
    expected = [sample for sample in samples if sample["mode"] != "OFF"]
    report = {
        "independent_entered_count": entered_count,
        "submitted_count": len(samples),
        "expected_audit_count": len(expected),
        "audit_visible_count": sum(sample["metadata_ms"] is not None for sample in expected),
        "content_expected_count": sum(sample["mode"] == "CONTENT" for sample in samples),
        "content_complete_count": sum(sample["content_ms"] is not None for sample in samples),
        "off_not_in_audit_denominator": True,
        "usage_baseline": "persisted dsh_model_call; synthetic fixture producer, not Redis allowance",
        "scope": "loopback fixture, synthetic model/identity, real stores; not production latency or SLA",
        "modes": {},
    }
    for mode in ("OFF", "METADATA", "CONTENT"):
        group = [sample for sample in samples if sample["mode"] == mode]
        metrics = {}
        for key in ("first_content_ms", "total_ms", "metadata_ms", "content_ms", "usage_ms"):
            values = [sample[key] for sample in group if sample[key] is not None]
            metrics[key] = {"count": len(values), "p95": percentile(values, 0.95), "p99": percentile(values, 0.99)}
        report["modes"][mode] = metrics
    return report


async def run(args):
    parsed = urlsplit(args.base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Only an explicit HTTP loopback fixture BASE is permitted")
    async with httpx.AsyncClient(base_url=args.base, timeout=30, trust_env=False) as client:
        initial = (await client.get("/health")).json()
        if initial.get("fixture") is not True:
            raise ValueError("Not an isolated audit test fixture")
        if not args.apply:
            return {"preflight": "read_only", "fixture": True, "apply_required": True}
        admin_token, user_token = os.environ.get("DSH_AUDIT_ADMIN_TOKEN"), os.environ.get("DSH_AUDIT_USER_TOKEN")
        if not admin_token or not user_token:
            raise ValueError("Synthetic fixture tokens must be supplied through environment variables")
        admin_headers, user_headers = (
            {"Authorization": "Bearer " + admin_token},
            {"Authorization": "Bearer " + user_token},
        )

        async def setting():
            result = (await client.get(ADMIN + "/settings", headers=admin_headers, params={"tenant_id": 2})).json()
            if result.get("status_code") != 200:
                raise ValueError("Fixture administrator preflight failed")
            return result["data"]

        async def change(mode):
            state = await setting()
            response = await client.put(
                ADMIN + "/settings/2",
                headers=admin_headers,
                json={"operation_id": str(uuid4()), "expected_version": state["version"], "mode": mode},
            )
            if response.json().get("status_code") != 200:
                raise ValueError("Fixture mode change failed")

        original = (await setting())["mode"]
        samples = []
        try:
            for mode in ("OFF", "METADATA", "CONTENT"):
                await change(mode)
                for _ in range(args.samples):
                    start = perf_counter()
                    first = None
                    async with client.stream(
                        "POST",
                        "/api/v1/dsh/chat/completions",
                        headers=user_headers,
                        json={
                            "model": "bisheng:42",
                            "stream": True,
                            "messages": [{"role": "user", "content": "synthetic-" + "x" * args.prompt_bytes}],
                            "audit_context": {"conversation_id": "measure-" + str(uuid4()), "request_kind": "chat"},
                        },
                    ) as response:
                        response.raise_for_status()
                        request_id = response.headers["x-request-id"]
                        async for line in response.aiter_lines():
                            if not line.startswith("data: ") or line == "data: [DONE]":
                                continue
                            event = json.loads(line[6:])
                            if event.get("error"):
                                raise ValueError("Synthetic model call failed")
                            if first is None and any(
                                choice.get("delta", {}).get("content") for choice in event.get("choices", [])
                            ):
                                first = (perf_counter() - start) * 1000
                    sample = {
                        "mode": mode,
                        "request_id": request_id,
                        "first_content_ms": first,
                        "total_ms": (perf_counter() - start) * 1000,
                        "metadata_ms": None,
                        "content_ms": None,
                        "usage_ms": None,
                    }
                    deadline = perf_counter() + args.visibility_timeout
                    while perf_counter() < deadline:
                        usage = (await client.get("/fixture/usage/" + request_id, headers=admin_headers)).json()
                        if usage.get("source") != "dsh_model_call":
                            raise ValueError("Unexpected usage baseline")
                        if usage.get("total_tokens") is not None and sample["usage_ms"] is None:
                            sample["usage_ms"] = (perf_counter() - start) * 1000
                        if mode != "OFF":
                            detail = (
                                (await client.get(ADMIN + "/requests/" + request_id, headers=admin_headers))
                                .json()
                                .get("data", {})
                            )
                            if not detail.get("audit_record_missing", False) and "effective_mode" in detail:
                                elapsed = (perf_counter() - start) * 1000
                                if sample["metadata_ms"] is None:
                                    sample["metadata_ms"] = elapsed
                                if detail.get("content_status") == "COMPLETE" and sample["content_ms"] is None:
                                    sample["content_ms"] = elapsed
                        if sample["usage_ms"] is not None and (
                            mode == "OFF"
                            or (
                                sample["metadata_ms"] is not None
                                and (mode != "CONTENT" or sample["content_ms"] is not None)
                            )
                        ):
                            break
                        await asyncio.sleep(0.025)
                    samples.append(sample)
        finally:
            await change(original)
        final = (await client.get("/health")).json()
        report = summarize(samples, entered_count=final["calls"] - initial["calls"])
        report.update(
            {
                "samples_per_mode": args.samples,
                "synthetic_prompt_bytes": args.prompt_bytes,
                "peak_rss_bytes": final["peak_rss_bytes"],
                "peak_rss_growth_bytes": max(0, final["peak_rss_bytes"] - initial["peak_rss_bytes"]),
                "request_ids": [sample["request_id"] for sample in samples],
                "mode_restored": original,
                "poll_interval_ms": 25,
            }
        )
        if report["independent_entered_count"] != len(samples):
            raise ValueError("Independent model-entered count differs: fixture was shared or replay occurred")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--samples", type=int, choices=range(1, 51), default=10)
    parser.add_argument("--prompt-bytes", type=int, choices=range(1, 1048577), default=16384)
    parser.add_argument("--visibility-timeout", type=float, default=10)
    args = parser.parse_args()
    if not 0 < args.visibility_timeout <= 60:
        parser.error("visibility timeout must be in (0, 60]")
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2))
    except Exception as error:
        print("Audit measurement failed: " + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
