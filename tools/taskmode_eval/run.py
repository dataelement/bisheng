"""Batch runner: submit eval cases to task mode through the v2 open API.

Usage (on 114, from the pack directory):
  PY=/opt/bisheng/src/backend/.venv/bin/python
  $PY -I harness/run.py --cases core --repeat 1 --concurrency 3 [--run-id NAME] [--resume]

For each case x repeat it uploads the inputs, submits with run_mode=task/execution=async,
polls until a terminal state (terminates on timeout), downloads deliverables and writes
  runs/<run_id>/<case>/r<k>/{meta.json, task.json, answer.md, files/}
"""

from __future__ import annotations

import argparse
import re
import sys as _sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from pathlib import Path as _P

import httpx

_sys.path.insert(0, str(_P(__file__).resolve().parent))

from common import CASES, RUNS, TERMINAL, dump_json, load_case, load_env, load_json, log, now_iso, select_cases

POLL_S = 10
RETRY_INFRA = 0  # set from --retry-infra

# Failures caused by the platform or the model provider rather than by the agent. With
# --retry-infra the case is resubmitted, so these failures do not count against the agent.
INFRA_CATEGORIES = {"rate_limit", "service_unavailable", "network_timeout", "task_aborted", "quota_exhausted"}
INFRA_MESSAGES = ("DSH quota state is temporarily unavailable",)


def is_infra_failure(view: dict) -> bool:
    if view.get("status") != "failed":
        return False
    f = view.get("failure") or {}
    return f.get("category") in INFRA_CATEGORIES or any(m in (f.get("message") or "") for m in INFRA_MESSAGES)


class Api:
    def __init__(self, env: dict):
        headers = {"Authorization": f"Bearer {env['api_key']}"}
        if env.get("end_user"):
            headers["X-End-User"] = env["end_user"]
        if env.get("on_behalf_of"):
            headers["X-On-Behalf-Of"] = str(env["on_behalf_of"])
        self.c = httpx.Client(base_url=env["base_url"].rstrip("/") + "/api/v2", headers=headers, timeout=120)
        self.lock = threading.Lock()

    @staticmethod
    def _data(r: httpx.Response):
        try:
            body = r.json()
        except Exception:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code != 200 or body.get("status_code") not in (200, None):
            raise RuntimeError(
                f"HTTP {r.status_code} biz={body.get('status_code')} {body.get('status_message')} data={body.get('data')}"
            )
        return body.get("data")

    def config(self):
        return self._data(self.c.get("/workstation/config", params={"run_mode": "task"}))

    def upload(self, path: Path) -> dict:
        with open(path, "rb") as f:
            d = self._data(self.c.post("/knowledge/upload", files={"file": (path.name, f)}, timeout=600))
        return {"file_path": d["file_path"], "file_name": path.name}

    def submit(self, body: dict) -> dict:
        return self._data(self.c.post("/workstation/chat/completions", json=body))

    def task(self, task_id: str) -> dict:
        return self._data(self.c.get(f"/workstation/tasks/{task_id}"))

    def terminate(self, task_id: str):
        r = self.c.post(f"/workstation/tasks/{task_id}/terminate")
        return r.status_code

    def download(self, task_id: str, file_id: str, dest: Path) -> int:
        with self.c.stream("GET", f"/workstation/tasks/{task_id}/files/{file_id}", timeout=600) as r:
            if r.status_code != 200:
                raise RuntimeError(f"download {file_id}: HTTP {r.status_code}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            n = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    n += len(chunk)
        return n


def build_body(case: dict, ref: dict, env: dict, uploaded: list[dict]) -> dict:
    cid = case["case_id"]
    skill_map = env.get("skill_map", {})
    skills = []
    for s in case.get("skills") or []:
        s = skill_map.get(s, s)
        if s and s not in skills:
            skills.append(s)
    ks_map = {str(k): v for k, v in env.get("knowledge_space_map", {}).items()}
    ks = []
    for k in case.get("knowledge_space_ids") or []:
        if str(k) not in ks_map:
            raise RuntimeError(f"{cid}: 知识空间 {k} 在 env.json knowledge_space_map 里没有对应")
        ks.append(int(ks_map[str(k)]))
    body = {
        "run_mode": "task",
        "execution": "async",
        "clientTimestamp": now_iso(),
        "text": ref.get("query_override") or case["question"],
        "model": str(env.get("model_overrides", {}).get(cid) or env["model"]),
    }
    if skills:
        body["skills"] = skills
    if ks:
        body["knowledge_space_ids"] = ks
    if uploaded:
        body["files"] = uploaded
    return body


def safe_name(name: str) -> str:
    return re.sub(r"[\\/\x00]", "_", name) or "unnamed"


def run_one(api: Api, env: dict, case_id: str, rep: int, out: Path, timeout_s: int) -> dict:
    case, ref = load_case(case_id)
    meta_path, task_path = out / "meta.json", out / "task.json"
    prev = load_json(task_path)
    if prev and prev.get("status") in TERMINAL + ("timeout", "error"):
        return {"case": case_id, "rep": rep, "status": prev["status"], "skipped": True}

    meta = {"case_id": case_id, "rep": rep, "started_at": now_iso(), "model": None, "task_id": None}
    try:
        exclude = set(ref.get("inputs_exclude") or [])
        in_dir = CASES / case_id / "inputs"
        paths = sorted(p for p in in_dir.iterdir() if p.is_file() and p.name not in exclude) if in_dir.is_dir() else []
        uploaded = [api.upload(p) for p in paths]
        body = build_body(case, ref, env, uploaded)
        meta.update(
            model=body["model"],
            skills=body.get("skills"),
            knowledge_space_ids=body.get("knowledge_space_ids"),
            input_files=[p.name for p in paths],
            query_override=bool(ref.get("query_override")),
        )
        attempts = []
        for attempt in range(1 + RETRY_INFRA):
            sub = api.submit(body)
            task_id = sub["task_id"]
            meta.update(task_id=task_id, submitted_at=time.time(), attempts=attempts)
            dump_json(meta_path, meta)
            log(f"{case_id} r{rep} 已提交 task_id={task_id}" + (f"（第 {attempt + 1} 次）" if attempt else ""))

            running_at = None
            view = sub
            while True:
                time.sleep(POLL_S)
                try:
                    view = api.task(task_id)
                except Exception as e:  # transient API errors: keep polling
                    log(f"{case_id} r{rep} 轮询出错：{e}")
                    continue
                st = view.get("status")
                if st == "running" and running_at is None:
                    running_at = time.time()
                if st in TERMINAL:
                    break
                if time.time() - (running_at or meta["submitted_at"]) > timeout_s:
                    api.terminate(task_id)
                    view = dict(api.task(task_id), status="timeout")
                    break
            if not is_infra_failure(view) or attempt == RETRY_INFRA:
                break
            attempts.append({"task_id": task_id, "failure": view.get("failure")})
            log(f"{case_id} r{rep} 基础设施故障，重新提交：{(view.get('failure') or {}).get('message', '')[:120]}")
        end = time.time()
        meta.update(
            finished_at=end,
            queue_s=round((running_at or end) - meta["submitted_at"], 1),
            exec_s=round(end - (running_at or meta["submitted_at"]), 1),
        )

        result = view.get("result") or {}
        (out / "answer.md").write_text(result.get("answer") or "", encoding="utf-8")
        got = []
        for f in result.get("files") or []:
            name = safe_name(f.get("file_name") or f["file_id"])
            dest = out / "files" / name
            if dest.exists():
                dest = out / "files" / f"{f['file_id']}_{name}"
            try:
                size = api.download(task_id, f["file_id"], dest)
                got.append({"file_name": dest.name, "size": size, "primary": f.get("primary", False)})
            except Exception as e:
                got.append({"file_name": name, "error": str(e)})
        meta["downloaded"] = got
        dump_json(task_path, view)
        dump_json(meta_path, meta)
        log(f"{case_id} r{rep} 结束：{view.get('status')}，执行 {meta['exec_s']}s，产物 {len(got)} 个")
        return {"case": case_id, "rep": rep, "status": view.get("status"), "exec_s": meta["exec_s"]}
    except Exception as e:
        meta["error"] = str(e)
        dump_json(meta_path, meta)
        dump_json(task_path, {"status": "error", "error": str(e)})
        log(f"{case_id} r{rep} 出错：{e}")
        return {"case": case_id, "rep": rep, "status": "error", "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="core", help="core | extended | all | A01,B03,...（可混用）")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--run-id", default=None, help="默认 时间戳_模型id；--resume 时填已有的 run-id")
    ap.add_argument("--resume", action="store_true", help="跳过已到终态的用例")
    ap.add_argument("--env", default=None)
    ap.add_argument(
        "--retry-infra", type=int, default=1, help="基础设施故障（限流、服务不可用、任务被中止等）自动重新提交的次数"
    )
    ap.add_argument(
        "--timeout-min", type=int, default=None, help="单条执行超时（分钟），默认取 env.json case_timeout_min 或 90"
    )
    args = ap.parse_args()
    global RETRY_INFRA
    RETRY_INFRA = args.retry_infra

    env = load_env(args.env)
    cases = select_cases(args.cases)
    api = Api(env)
    cfg = api.config()
    avail_skills = {s["name"] for s in cfg.get("skills") or []}
    avail_models = {str(m["id"]) for m in cfg.get("models") or []}
    problems = []
    for c in cases:
        case, ref = load_case(c["id"])
        if not ref:
            problems.append(f"{c['id']} 没有 reference.json（仍会执行，但无法判分）")
        for s in case.get("skills") or []:
            s2 = env.get("skill_map", {}).get(s, s)
            if s2 not in avail_skills:
                problems.append(f"{c['id']} 需要技能 {s2}，当前执行身份不可用")
        m = str(env.get("model_overrides", {}).get(c["id"]) or env["model"])
        if m not in avail_models:
            problems.append(f"{c['id']} 的模型 {m} 不可用")
    for p in problems:
        log("预检：" + p)
    if any("不可用" in p for p in problems):
        raise SystemExit("预检失败，修好 env.json 或环境后再跑")

    run_id = args.run_id or time.strftime("%Y%m%d-%H%M") + f"_m{env['model']}"
    run_dir = RUNS / run_id
    if run_dir.exists() and not args.resume:
        raise SystemExit(f"{run_dir} 已存在；续跑请加 --resume")
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "started_at": now_iso(),
            "cases": [c["id"] for c in cases],
            "repeat": args.repeat,
            "base_url": env["base_url"],
            "model": env["model"],
            "model_overrides": env.get("model_overrides", {}),
            "skill_map": env.get("skill_map", {}),
            "knowledge_space_map": env.get("knowledge_space_map", {}),
            "platform_version": env.get("platform_version"),
        },
    )
    timeout_s = 60 * (args.timeout_min or env.get("case_timeout_min", 90))
    jobs = [(c["id"], k) for k in range(1, args.repeat + 1) for c in cases]
    log(f"run_id={run_id}，共 {len(jobs)} 个任务，并发 {args.concurrency}")
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(run_one, api, env, cid, k, run_dir / cid / f"r{k}", timeout_s) for cid, k in jobs]
        for f in as_completed(futs):
            results.append(f.result())
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    log(f"全部结束：{summary}。判分：$PY -I harness/grade.py --run-id {run_id}")


if __name__ == "__main__":
    main()
