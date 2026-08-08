#!/usr/bin/env python3
"""按实施方案 C.7 顺序跑压测场景并汇总 Markdown 报告。

用法：
  E2E_POINTS_PASSWORD=… \\
    .venv/bin/python test/points/perf_run_matrix.py --quick

--quick：各场景缩小规模（VPN 联调推荐）
不加 --quick：接近计划矩阵下限
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
PY = BACKEND / ".venv/bin/python"
OUT = BACKEND / "test/points/_perf_reports"


def _run(cmd: list[str]) -> dict:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    # 2=门禁未过仍产出摘要；其它非 0 记入结果但继续后续场景
    if proc.returncode not in (0, 2):
        data = {"_exit": proc.returncode, "error": (proc.stderr or "")[-500:]}
        for ln in (proc.stdout or "").splitlines():
            if ln.startswith("PERF_SUMMARY "):
                data.update(json.loads(ln[len("PERF_SUMMARY ") :]))
                break
        return data
    data: dict = {"_exit": proc.returncode}
    for ln in proc.stdout.splitlines():
        if ln.startswith("PERF_SUMMARY "):
            data.update(json.loads(ln[len("PERF_SUMMARY ") :]))
            break
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--skip-admin", action="store_true")
    parser.add_argument("--skip-award", action="store_true")
    parser.add_argument("--sync-baseline", action="store_true")
    args = parser.parse_args()

    if args.quick:
        award = [
            ("P1", 20, 10),
            ("P2", 20, 10),
            ("P3", 10, 5),
            ("P4", 20, 10),
            ("P5", 15, 10),
            ("P6", 5, 1),
        ]
        admin = [
            ("P7", 20, 10),
            ("P8", 20, 10),
            ("P9", 20, 10),
        ]
    else:
        award = [
            ("P1", 50, 20),
            ("P2", 50, 20),
            ("P3", 30, 10),
            ("P4", 50, 20),
            ("P5", 30, 20),
            ("P6", 10, 1),
        ]
        admin = [
            ("P7", 50, 10),
            ("P8", 50, 20),
            ("P9", 50, 20),
        ]

    OUT.mkdir(parents=True, exist_ok=True)
    # 共享 Redis Broker 上有远端旧 Worker；压测默认走本地专用队列。
    os.environ.setdefault("POINTS_AWARD_CELERY_QUEUE", "points_award_local")
    rows: list[dict] = []
    env_note = {
        "network": "vpn_remote_middleware",
        "quick": args.quick,
        "award_queue": os.environ.get("POINTS_AWARD_CELERY_QUEUE"),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    if args.sync_baseline and not args.skip_award:
        cmd = [
            str(PY),
            "test/points/perf_award_async.py",
            "--scenario",
            "P1",
            "--n",
            "20",
            "--concurrency",
            "10",
            "--sync",
        ]
        rows.append({"kind": "award_sync_baseline", **_run(cmd)})

    if not args.skip_award:
        for scenario, n, conc in award:
            cmd = [
                str(PY),
                "test/points/perf_award_async.py",
                "--scenario",
                scenario,
                "--n",
                str(n),
                "--concurrency",
                str(conc),
            ]
            rows.append({"kind": "award", **_run(cmd)})

    if not args.skip_admin:
        if not os.environ.get("E2E_POINTS_PASSWORD"):
            print("WARN: skip admin scenarios; E2E_POINTS_PASSWORD unset", file=sys.stderr)
        else:
            for scenario, n, conc in admin:
                cmd = [
                    str(PY),
                    "test/points/perf_admin_write.py",
                    "--scenario",
                    scenario,
                    "--n",
                    str(n),
                    "--concurrency",
                    str(conc),
                ]
                rows.append({"kind": "admin", **_run(cmd)})

    ts = time.strftime("%Y%m%d_%H%M%S")
    summary_json = OUT / f"perf_matrix_{ts}.json"
    summary_md = OUT / f"perf_matrix_{ts}.md"
    summary_json.write_text(
        json.dumps({"env": env_note, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Points perf matrix summary",
        "",
        f"- network: `{env_note['network']}`",
        f"- time: {env_note['ts']}",
        f"- quick: {env_note['quick']}",
        "",
        "| kind | scenario | n | conc | enqueue/http P95 | ledger P95 | ok/fail | gates |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        scen = r.get("scenario", "?")
        n = r.get("n", "")
        conc = r.get("concurrency", "")
        if "enqueue_p95_ms" in r:
            p95 = f"{r.get('enqueue_p95_ms', 0):.1f}ms"
            ledger = r.get("ledger_p95_ms")
            ledger_s = f"{ledger:.1f}ms" if isinstance(ledger, (int, float)) else "-"
            ok = f"{r.get('applied', 0)}/{r.get('failed', 0)}"
            gates = (
                f"enq={r.get('pass_enqueue')} led={r.get('pass_ledger')} "
                f"corr={r.get('pass_correctness')}"
            )
        else:
            p95 = f"{r.get('http_p95_ms', 0):.1f}ms"
            ledger_s = "-"
            ok = f"{r.get('ok_count', 0)}/{r.get('failed', 0)}"
            gates = f"http={r.get('pass_http')} corr={r.get('pass_correctness')}"
        lines.append(
            f"| {r.get('kind')} | {scen} | {n} | {conc} | {p95} | {ledger_s} | {ok} | {gates} |"
        )
    lines.append("")
    summary_md.write_text("\n".join(lines), encoding="utf-8")
    print(summary_md.read_text(encoding="utf-8"))
    print(f"summary={summary_md}")


if __name__ == "__main__":
    main()
