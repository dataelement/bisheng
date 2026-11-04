"""Materialise the historical 106 executions as a run (runs/baseline-106) so grade.py can score them.

The baseline is "what the customer actually got": answers come from raw/baseline_full_answers.json
(full text pulled from 106), deliverables from cases/<id>/baseline/. Run once:
  $PY -I harness/baseline_run.py && $PY -I harness/grade.py --run-id baseline-106
"""

from __future__ import annotations

import shutil
import sys as _sys
from pathlib import Path as _P

_sys.path.insert(0, str(_P(__file__).resolve().parent))

from common import CASES, PACK, RUNS, dump_json, load_json, log, now_iso, select_cases

STATUS = {
    "COMPLETED": "completed",
    "FAILED": "failed",
    "TERMINATED": "terminated",
    "WAITING_FOR_USER_INPUT": "waiting_input",
    "NOT_STARTED": "not_started",
}


def main():
    full = load_json(PACK / "raw" / "baseline_full_answers.json", {}) or {}
    run_dir = RUNS / "baseline-106"
    cases = select_cases("all")
    dump_json(
        run_dir / "run.json",
        {
            "run_id": "baseline-106",
            "started_at": now_iso(),
            "cases": [c["id"] for c in cases],
            "repeat": 1,
            "model": "106 历史执行（dsv4 为主）",
            "note": "106 生产环境的历史产出，作为 v0 基线",
        },
    )
    for sel in cases:
        case = load_json(CASES / sel["id"] / "case.json")
        b = case.get("baseline") or {}
        out = run_dir / sel["id"] / "r1"
        out.mkdir(parents=True, exist_ok=True)
        answer = (full.get(case["source_version_id"]) or {}).get("answer") or b.get("answer") or ""
        (out / "answer.md").write_text(answer, encoding="utf-8")
        fdir = out / "files"
        if fdir.exists():
            shutil.rmtree(fdir)
        src = CASES / sel["id"] / "baseline"
        if src.is_dir():
            fdir.mkdir()
            for p in src.iterdir():
                shutil.copy2(p, fdir / p.name)
        status = STATUS.get(b.get("status"), str(b.get("status")).lower())
        dump_json(out / "task.json", {"status": status, "source_version_id": case["source_version_id"]})
        dump_json(out / "meta.json", {"case_id": sel["id"], "rep": 1, "exec_s": b.get("duration_s")})
    log(f"已生成 {run_dir}")


if __name__ == "__main__":
    main()
