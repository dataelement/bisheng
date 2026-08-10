#!/usr/bin/env python3
"""积分管理员写路径压测：同步 POST /admin/deduct 与 /admin/adjust。

用法（cwd: src/backend，需 Backend :7860）：
  E2E_POINTS_PASSWORD=… \\
    .venv/bin/python test/points/perf_admin_write.py --scenario P7 --n 20 --concurrency 10

环境变量：
  E2E_POINTS_ADMIN（默认 admin）
  E2E_POINTS_PASSWORD（必填）
  POINTS_PERF_BASE_URL（默认 http://127.0.0.1:7860）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("httpx required") from exc

BACKEND_ROOT = Path(__file__).resolve().parents[2]

USER_GZX01 = 4
USER_GZX02 = 5
RULES = ("R1", "R2", "R3")


@dataclass
class Sample:
    """单次 HTTP 写样本。"""

    scenario: str
    http_ms: float
    status: int
    ok: bool
    error: str | None = None
    rule_code: str | None = None
    user_id: int | None = None


@dataclass
class ScenarioReport:
    """场景汇总。"""

    scenario: str
    n: int
    concurrency: int
    network: str = "vpn_remote_middleware"
    ok_count: int = 0
    failed: int = 0
    http_p50_ms: float = 0.0
    http_p95_ms: float = 0.0
    pass_http: bool = False
    pass_correctness: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _login_token(base_url: str, username: str, password: str) -> str:
    """登录一次拿 JWT，避免压测时每请求重复登录抬高 HTTP P95。"""
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        resp = client.post(
            "/api/v1/user/login",
            json={"user_name": username, "password": password, "force_login": True},
        )
        resp.raise_for_status()
        body = resp.json()
        token = (body.get("data") or {}).get("access_token") or client.cookies.get(
            "access_token_cookie"
        )
    if not token:
        raise RuntimeError(f"login missing token: {body}")
    return str(token)


def _client_with_token(base_url: str, token: str) -> httpx.Client:
    """构造已带 access_token_cookie 的短生命周期 client。"""
    client = httpx.Client(base_url=base_url, timeout=30.0)
    client.cookies.set("access_token_cookie", token)
    return client


def _deduct(
    client: httpx.Client,
    *,
    user_id: int,
    rule_code: str,
    remark: str,
) -> Sample:
    t0 = time.perf_counter()
    try:
        resp = client.post(
            "/api/v1/points/admin/deduct",
            json={
                "user_id": user_id,
                "rule_code": rule_code,
                "remark": remark,
            },
        )
        ms = (time.perf_counter() - t0) * 1000.0
        ok = resp.status_code == 200 and int(resp.json().get("status_code", 200)) == 200
        return Sample(
            scenario="deduct",
            http_ms=ms,
            status=resp.status_code,
            ok=ok,
            error=None if ok else resp.text[:300],
            rule_code=rule_code,
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        return Sample(
            scenario="deduct",
            http_ms=(time.perf_counter() - t0) * 1000.0,
            status=0,
            ok=False,
            error=str(exc),
            rule_code=rule_code,
            user_id=user_id,
        )


def _adjust(
    client: httpx.Client,
    *,
    user_id: int,
    delta: int,
    remark: str,
) -> Sample:
    t0 = time.perf_counter()
    try:
        resp = client.post(
            "/api/v1/points/admin/adjust",
            json={"user_id": user_id, "delta": delta, "remark": remark},
        )
        ms = (time.perf_counter() - t0) * 1000.0
        ok = resp.status_code == 200 and int(resp.json().get("status_code", 200)) == 200
        return Sample(
            scenario="adjust",
            http_ms=ms,
            status=resp.status_code,
            ok=ok,
            error=None if ok else resp.text[:300],
            user_id=user_id,
        )
    except Exception as exc:  # noqa: BLE001
        return Sample(
            scenario="adjust",
            http_ms=(time.perf_counter() - t0) * 1000.0,
            status=0,
            ok=False,
            error=str(exc),
            user_id=user_id,
        )


def run_scenario(
    scenario: str,
    *,
    n: int,
    concurrency: int,
    base_url: str,
    run_id: str,
) -> ScenarioReport:
    username = os.environ.get("E2E_POINTS_ADMIN", "admin")
    password = os.environ.get("E2E_POINTS_PASSWORD")
    if not password:
        raise SystemExit("E2E_POINTS_PASSWORD is required")

    token = _login_token(base_url, username, password)

    jobs: list[tuple[str, dict]] = []
    if scenario == "P7":
        for i in range(n):
            jobs.append(
                (
                    "deduct",
                    {
                        "user_id": USER_GZX01,
                        "rule_code": "R1",
                        "remark": f"perf-deduct-{run_id}-p7-{i:04d}",
                    },
                )
            )
    elif scenario == "P8":
        users = (USER_GZX01, USER_GZX02)
        for i in range(n):
            jobs.append(
                (
                    "deduct",
                    {
                        "user_id": users[i % 2],
                        "rule_code": RULES[i % 3],
                        "remark": f"perf-deduct-{run_id}-p8-{i:04d}",
                    },
                )
            )
    elif scenario == "P9":
        for i in range(n):
            jobs.append(
                (
                    "adjust",
                    {
                        "user_id": USER_GZX01,
                        "delta": -1,
                        "remark": f"perf-deduct-{run_id}-p9-{i:04d}",
                    },
                )
            )
    else:
        raise SystemExit(f"unknown scenario {scenario} (use P7/P8/P9)")

    samples: list[Sample] = []

    def _run_one(kind: str, payload: dict) -> Sample:
        client = _client_with_token(base_url, token)
        try:
            if kind == "deduct":
                return _deduct(client, **payload)
            return _adjust(client, **payload)
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(_run_one, kind, payload) for kind, payload in jobs]
        for fut in as_completed(futs):
            samples.append(fut.result())

    http_ms = [s.http_ms for s in samples]
    ok_count = sum(1 for s in samples if s.ok)
    failed = len(samples) - ok_count
    p95 = _pct(http_ms, 95)
    # VPN 档：deduct/adjust P95 < 2s
    return ScenarioReport(
        scenario=scenario,
        n=n,
        concurrency=concurrency,
        ok_count=ok_count,
        failed=failed,
        http_p50_ms=_pct(http_ms, 50),
        http_p95_ms=p95,
        pass_http=p95 < 2000.0,
        pass_correctness=failed == 0,
        samples=[asdict(s) for s in samples],
    )


def _write_report(report: ScenarioReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"perf_admin_{report.scenario}_{ts}.json"
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md = out_dir / f"perf_admin_{report.scenario}_{ts}.md"
    md.write_text(
        "\n".join(
            [
                f"# Points admin write perf — {report.scenario}",
                "",
                f"- network: `{report.network}`",
                f"- n={report.n} concurrency={report.concurrency}",
                f"- http P50/P95: {report.http_p50_ms:.1f} / {report.http_p95_ms:.1f} ms",
                f"- ok={report.ok_count} failed={report.failed}",
                f"- pass_http={report.pass_http} pass_correctness={report.pass_correctness}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Points admin deduct/adjust perf")
    parser.add_argument("--scenario", default="P7", choices=["P7", "P8", "P9"])
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("POINTS_PERF_BASE_URL", "http://127.0.0.1:7860"),
    )
    parser.add_argument(
        "--out-dir",
        default=str(BACKEND_ROOT / "test/points/_perf_reports"),
    )
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    run_id = args.run_id or uuid.uuid4().hex[:12]

    report = run_scenario(
        args.scenario,
        n=args.n,
        concurrency=args.concurrency,
        base_url=args.base_url.rstrip("/"),
        run_id=run_id,
    )
    path = _write_report(report, Path(args.out_dir))
    summary = {k: v for k, v in asdict(report).items() if k != "samples"}
    print("PERF_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    print(f"report={path}")
    if not (report.pass_http and report.pass_correctness):
        sys.exit(2)


if __name__ == "__main__":
    main()
