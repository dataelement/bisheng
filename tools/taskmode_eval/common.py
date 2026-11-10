"""Shared helpers for the task-mode eval harness.

Layout (PACK = the unpacked taskmode-eval-v1 directory):
  PACK/cases/<id>/{case.json, reference.json, inputs/}
  PACK/harness/{selection.json, env.json, *.py}
  PACK/runs/<run_id>/<case>/r<k>/   (written by run.py, read by grade.py)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
PACK = HARNESS.parent
CASES = PACK / "cases"
RUNS = PACK / "runs"
TERMINAL = ("completed", "failed", "terminated")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def load_env(path: str | None = None) -> dict:
    env_path = Path(path) if path else HARNESS / "env.json"
    env = load_json(env_path)
    if env is None:
        raise SystemExit(f"缺少 {env_path}，先运行 setup_env.py 或照 env.example.json 手写一份")
    return env


def load_selection() -> dict:
    return load_json(HARNESS / "selection.json")


def select_cases(spec: str) -> list[dict]:
    """spec: 'core' | 'extended' | 'all' | comma list of case ids (may mix, e.g. 'core,A11')."""
    sel = load_selection()["cases"]
    by_id = {c["id"]: c for c in sel}
    chosen: list[dict] = []
    for token in [t.strip() for t in spec.split(",") if t.strip()]:
        if token == "all":
            picked = sel
        elif token in ("core", "extended"):
            picked = [c for c in sel if c["tier"] == token]
        elif token in by_id:
            picked = [by_id[token]]
        else:
            raise SystemExit(f"未知用例或分组：{token}")
        for c in picked:
            if c not in chosen:
                chosen.append(c)
    return chosen


def load_case(case_id: str) -> tuple[dict, dict]:
    case = load_json(CASES / case_id / "case.json")
    ref = load_json(CASES / case_id / "reference.json", default={}) or {}
    return case, ref


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
