#!/usr/bin/env python3
"""积分自动发分压测（路径 A）：直调 notify_* / _dispatch，测 enqueue 与到账延迟。

用法（cwd: src/backend）：
  PYTHONPATH=. config=config.yaml \\
    .venv/bin/python test/points/perf_award_async.py --scenario P1 --n 20 --concurrency 10

环境：
  - points.enabled / award_async_enabled=true（默认）
  - Celery worker：celery -A bisheng.worker.main worker -Q celery -c 20 -P threads
  - --sync 强制同步入账作对照
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 固定测试账号（与实施方案 C.3 一致）
USER_GZX01 = 4
USER_GZX02 = 5
SPACE_GZX01 = 4
SPACE_GZX02 = 5
TENANT_ID = 1


@dataclass
class Sample:
    """单次发分样本。"""

    scenario: str
    enqueue_ms: float
    ledger_ms: float | None
    ok: bool
    skipped_cap: bool = False
    double_credit: bool = False
    error: str | None = None
    idempotency_key: str | None = None


@dataclass
class ScenarioReport:
    """场景汇总。"""

    scenario: str
    n: int
    concurrency: int
    sync: bool
    network: str = "vpn_remote_middleware"
    applied: int = 0
    skipped_cap: int = 0
    failed: int = 0
    double_credit: int = 0
    enqueue_p50_ms: float = 0.0
    enqueue_p95_ms: float = 0.0
    ledger_p50_ms: float | None = None
    ledger_p95_ms: float | None = None
    pass_enqueue: bool = False
    pass_ledger: bool = False
    pass_correctness: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)


def _pct(values: list[float], p: float) -> float:
    """简单百分位（nearest-rank）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _file_id_base(run_id: str) -> int:
    """生成高位 file_id 前缀（字符串幂等键场景，如 G2/G4）。"""
    h = abs(hash(run_id)) % 10_000_000
    return 9_000_000_000_000_000 + h * 10_000


def _safe_int_file_id(run_id: str, offset: int) -> int:
    """生成落在 signed INT 内的 file_id（G3 会写入 point_favorite_tier_award.file_id）。"""
    h = abs(hash(run_id)) % 1_000_000
    # 2_147_483_647 上限；1.7e9+ 避开真实业务自增
    return 1_700_000_000 + h * 100 + int(offset)


async def _count_logs_by_key(idem_key: str) -> int:
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        row = (
            await session.execute(
                text(
                    "select count(*) from user_point_log "
                    "where tenant_id=:t and idempotency_key=:k"
                ),
                {"t": TENANT_ID, "k": idem_key},
            )
        ).first()
    return int(row[0]) if row else 0


async def _today_earn_sum(user_id: int, rule_code: str) -> int:
    """今日该规则已入账正分合计（用于识别 daily_cap 跳过）。"""
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        row = (
            await session.execute(
                text(
                    "select coalesce(sum(delta),0) from user_point_log "
                    "where tenant_id=:t and user_id=:u and rule_code=:r "
                    "and direction='earn' and create_time >= curdate()"
                ),
                {"t": TENANT_ID, "u": user_id, "r": rule_code},
            )
        ).first()
    return int(row[0]) if row else 0


async def _wait_log(idem_key: str, *, timeout_s: float) -> tuple[bool, float]:
    """轮询流水直到可见；返回 (可见, 耗时 ms)。"""
    t0 = time.perf_counter()
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        if await _count_logs_by_key(idem_key) >= 1:
            return True, (time.perf_counter() - t0) * 1000.0
        await asyncio.sleep(0.2)
    return False, (time.perf_counter() - t0) * 1000.0


async def _award_upload(
    *,
    user_id: int,
    space_id: int,
    file_id: int,
    sync: bool,
    wait_timeout_s: float,
) -> Sample:
    from bisheng.points.domain.services import points_award_hooks as hooks

    # 直调 _dispatch：部门库 G2；managers 置空避免受益人是空间管理员被 skip。
    idem = f"earn:G2:{file_id}:{space_id}"
    ctx = (
        patch.object(hooks, "_award_async_enabled", return_value=False)
        if sync
        else nullcontext()
    )
    t0 = time.perf_counter()
    try:
        with ctx:
            await hooks._dispatch(
                "space_file_ready",
                {
                    "tenant_id": TENANT_ID,
                    "space_id": space_id,
                    "space_level": "department",
                    "file_id": file_id,
                    "uploader_id": user_id,
                    "publisher_id": None,
                    "is_favorite_space": False,
                    "space_manager_ids": [],
                },
            )
        enqueue_ms = (time.perf_counter() - t0) * 1000.0
        visible, ledger_ms = await _wait_log(idem, timeout_s=wait_timeout_s)
        cnt = await _count_logs_by_key(idem)
        # G2 daily_cap=10：触顶时 Worker 不写流水，记 skipped_cap 而非失败。
        skipped_cap = False
        if not visible:
            earned = await _today_earn_sum(user_id, "G2")
            if earned >= 10:
                skipped_cap = True
        return Sample(
            scenario="upload",
            enqueue_ms=enqueue_ms,
            ledger_ms=ledger_ms if visible else None,
            ok=visible or skipped_cap,
            skipped_cap=skipped_cap,
            double_credit=cnt > 1,
            idempotency_key=idem,
            error=None if (visible or skipped_cap) else "ledger_timeout",
        )
    except Exception as exc:  # noqa: BLE001 — 压测汇总用
        return Sample(
            scenario="upload",
            enqueue_ms=(time.perf_counter() - t0) * 1000.0,
            ledger_ms=None,
            ok=False,
            error=str(exc),
            idempotency_key=idem,
        )


async def _award_favorite(
    *,
    user_id: int,
    file_id: int,
    unique_count: int,
    sync: bool,
    wait_timeout_s: float,
) -> Sample:
    from bisheng.points.domain.services import points_award_hooks as hooks

    # G3 阶梯：count 足够触发第一档；幂等键含 s_target，先按常见首档 1 分估键，
    # 实际以 DB 中 earn:G3:{file_id}:* 出现为准。
    ctx = (
        patch.object(hooks, "_award_async_enabled", return_value=False)
        if sync
        else nullcontext()
    )
    t0 = time.perf_counter()
    try:
        with ctx:
            await hooks._dispatch(
                "favorite_changed",
                {
                    "tenant_id": TENANT_ID,
                    "file_id": file_id,
                    "uploader_id": user_id,
                    "unique_favoriter_count": unique_count,
                    "space_manager_ids": [],
                },
            )
        enqueue_ms = (time.perf_counter() - t0) * 1000.0
        # 轮询任意 G3 流水（该 file）
        visible, ledger_ms = await _wait_g3(file_id, timeout_s=wait_timeout_s)
        return Sample(
            scenario="favorite",
            enqueue_ms=enqueue_ms,
            ledger_ms=ledger_ms if visible else None,
            ok=visible,
            error=None if visible else "ledger_timeout",
            idempotency_key=f"earn:G3:{file_id}:*",
        )
    except Exception as exc:  # noqa: BLE001
        return Sample(
            scenario="favorite",
            enqueue_ms=(time.perf_counter() - t0) * 1000.0,
            ledger_ms=None,
            ok=False,
            error=str(exc),
        )


async def _wait_g3(file_id: int, *, timeout_s: float) -> tuple[bool, float]:
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session

    t0 = time.perf_counter()
    deadline = t0 + timeout_s
    prefix = f"earn:G3:{file_id}:"
    while time.perf_counter() < deadline:
        async with get_async_db_session() as session:
            row = (
                await session.execute(
                    text(
                        "select count(*) from user_point_log "
                        "where tenant_id=:t and idempotency_key like :p"
                    ),
                    {"t": TENANT_ID, "p": prefix + "%"},
                )
            ).first()
        if row and int(row[0]) >= 1:
            return True, (time.perf_counter() - t0) * 1000.0
        await asyncio.sleep(0.2)
    return False, (time.perf_counter() - t0) * 1000.0


async def _award_adopt(
    *,
    user_id: int,
    answer_id: int,
    sync: bool,
    wait_timeout_s: float,
) -> Sample:
    from bisheng.points.domain.services.points_award_hooks import notify_answer_adopted

    idem = f"earn:G4:{answer_id}"
    ctx = (
        patch(
            "bisheng.points.domain.services.points_award_hooks._award_async_enabled",
            return_value=False,
        )
        if sync
        else nullcontext()
    )
    t0 = time.perf_counter()
    try:
        with ctx:
            await notify_answer_adopted(
                tenant_id=TENANT_ID,
                answer_id=answer_id,
                answerer_id=user_id,
            )
        enqueue_ms = (time.perf_counter() - t0) * 1000.0
        visible, ledger_ms = await _wait_log(idem, timeout_s=wait_timeout_s)
        cnt = await _count_logs_by_key(idem)
        return Sample(
            scenario="adopt",
            enqueue_ms=enqueue_ms,
            ledger_ms=ledger_ms if visible else None,
            ok=visible,
            double_credit=cnt > 1,
            error=None if visible else "ledger_timeout",
            idempotency_key=idem,
        )
    except Exception as exc:  # noqa: BLE001
        return Sample(
            scenario="adopt",
            enqueue_ms=(time.perf_counter() - t0) * 1000.0,
            ledger_ms=None,
            ok=False,
            error=str(exc),
            idempotency_key=idem,
        )


class nullcontext:
    """无操作上下文（兼容未装 contextlib.nullcontext 的旧环境）。"""

    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


async def _run_pool(jobs: list, concurrency: int) -> list[Sample]:
    """有界并发执行协程工厂列表。"""
    sem = asyncio.Semaphore(concurrency)
    results: list[Sample] = []

    async def _one(factory):
        async with sem:
            return await factory()

    for batch_start in range(0, len(jobs), concurrency):
        batch = jobs[batch_start : batch_start + concurrency]
        results.extend(await asyncio.gather(*[_one(j) for j in batch]))
    return results


def _summarize(
    scenario: str,
    samples: list[Sample],
    *,
    n: int,
    concurrency: int,
    sync: bool,
) -> ScenarioReport:
    # 丢弃首笔冷启动 enqueue（导入 Celery/Broker），避免 VPN 档误杀。
    enqueue_src = samples[1:] if len(samples) > 1 else samples
    enqueue = [s.enqueue_ms for s in enqueue_src]
    ledger = [s.ledger_ms for s in samples if s.ledger_ms is not None]
    failed = sum(1 for s in samples if not s.ok)
    double = sum(1 for s in samples if s.double_credit)
    applied = sum(1 for s in samples if s.ok and not s.skipped_cap)
    enqueue_p95 = _pct(enqueue, 95)
    ledger_p95 = _pct(ledger, 95) if ledger else None
    # VPN 联调档：enqueue <200ms；ledger <15s；双发=0；cap skip 不算失败
    pass_enqueue = enqueue_p95 < 200.0 if not sync else True
    # 若全部触顶跳过则无 ledger 样本，仍视为 ledger 门禁通过
    all_cap = bool(samples) and all(s.skipped_cap for s in samples)
    pass_ledger = (
        sync
        or all_cap
        or (ledger_p95 is not None and ledger_p95 < 15_000.0)
    )
    pass_correctness = double == 0 and failed == 0
    return ScenarioReport(
        scenario=scenario,
        n=n,
        concurrency=concurrency,
        sync=sync,
        applied=applied,
        skipped_cap=sum(1 for s in samples if s.skipped_cap),
        failed=failed,
        double_credit=double,
        enqueue_p50_ms=_pct(enqueue, 50),
        enqueue_p95_ms=enqueue_p95,
        ledger_p50_ms=_pct(ledger, 50) if ledger else None,
        ledger_p95_ms=ledger_p95,
        pass_enqueue=pass_enqueue,
        pass_ledger=pass_ledger,
        pass_correctness=pass_correctness,
        samples=[asdict(s) for s in samples],
    )


async def run_scenario(
    scenario: str,
    *,
    n: int,
    concurrency: int,
    sync: bool,
    wait_timeout_s: float,
    run_id: str,
) -> ScenarioReport:
    """执行单个场景矩阵项。"""
    if not sync:
        # 预热 Celery 客户端导入，避免首笔 enqueue 含冷启动。
        from bisheng.points.domain.services import points_award_hooks as hooks

        try:
            hooks._enqueue_award_event(
                {
                    "event_type": "answer_adopted",
                    "tenant_id": TENANT_ID,
                    "answer_id": 1,
                    "answerer_id": USER_GZX01,
                }
            )
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.5)

    base = _file_id_base(run_id)
    jobs = []

    if scenario == "P1":
        for i in range(n):
            fid = base + i
            jobs.append(
                lambda fid=fid: _award_upload(
                    user_id=USER_GZX01,
                    space_id=SPACE_GZX01,
                    file_id=fid,
                    sync=sync,
                    wait_timeout_s=wait_timeout_s,
                )
            )
    elif scenario == "P2":
        users = [(USER_GZX01, SPACE_GZX01), (USER_GZX02, SPACE_GZX02)]
        for i in range(n):
            uid, sid = users[i % 2]
            fid = base + i
            jobs.append(
                lambda fid=fid, uid=uid, sid=sid: _award_upload(
                    user_id=uid,
                    space_id=sid,
                    file_id=fid,
                    sync=sync,
                    wait_timeout_s=wait_timeout_s,
                )
            )
    elif scenario == "P3":
        for i in range(n):
            fid = _safe_int_file_id(run_id, i)
            jobs.append(
                lambda fid=fid: _award_favorite(
                    user_id=USER_GZX01,
                    file_id=fid,
                    # 现网 G3 首档 threshold=75
                    unique_count=80,
                    sync=sync,
                    wait_timeout_s=wait_timeout_s,
                )
            )
    elif scenario == "P4":
        for i in range(n):
            aid = base + 200_000 + i
            jobs.append(
                lambda aid=aid: _award_adopt(
                    user_id=USER_GZX01,
                    answer_id=aid,
                    sync=sync,
                    wait_timeout_s=wait_timeout_s,
                )
            )
    elif scenario == "P5":
        # 混合：上传 / 收藏 / 采纳各约 n/3
        for i in range(n):
            kind = i % 3
            if kind == 0:
                fid = base + i
                jobs.append(
                    lambda fid=fid: _award_upload(
                        user_id=USER_GZX01,
                        space_id=SPACE_GZX01,
                        file_id=fid,
                        sync=sync,
                        wait_timeout_s=wait_timeout_s,
                    )
                )
            elif kind == 1:
                fid = _safe_int_file_id(run_id, 50_000 + i)
                jobs.append(
                    lambda fid=fid: _award_favorite(
                        user_id=USER_GZX01,
                        file_id=fid,
                        unique_count=80,
                        sync=sync,
                        wait_timeout_s=wait_timeout_s,
                    )
                )
            else:
                aid = base + 200_000 + i
                jobs.append(
                    lambda aid=aid: _award_adopt(
                        user_id=USER_GZX01,
                        answer_id=aid,
                        sync=sync,
                        wait_timeout_s=wait_timeout_s,
                    )
                )
    elif scenario == "P6":
        # 同 payload 重放：每对两次，期望仅一笔 ledger
        samples: list[Sample] = []
        for i in range(n):
            fid = base + 300_000 + i
            first = await _award_upload(
                user_id=USER_GZX01,
                space_id=SPACE_GZX01,
                file_id=fid,
                sync=sync,
                wait_timeout_s=wait_timeout_s,
            )
            second = await _award_upload(
                user_id=USER_GZX01,
                space_id=SPACE_GZX01,
                file_id=fid,
                sync=sync,
                wait_timeout_s=wait_timeout_s,
            )
            cnt = await _count_logs_by_key(f"earn:G2:{fid}:{SPACE_GZX01}")
            first.double_credit = cnt > 1
            second.ok = True  # 幂等重放成功不算失败
            second.double_credit = cnt > 1
            samples.extend([first, second])
        return _summarize("P6", samples, n=n, concurrency=1, sync=sync)
    else:
        raise SystemExit(f"unknown scenario {scenario}")

    samples = await _run_pool(jobs, concurrency)
    return _summarize(scenario, samples, n=n, concurrency=concurrency, sync=sync)


def _write_report(report: ScenarioReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"perf_award_{report.scenario}_{ts}.json"
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md = out_dir / f"perf_award_{report.scenario}_{ts}.md"
    md.write_text(
        "\n".join(
            [
                f"# Points award perf — {report.scenario}",
                "",
                f"- network: `{report.network}`",
                f"- sync: `{report.sync}`",
                f"- n={report.n} concurrency={report.concurrency}",
                f"- enqueue P50/P95: {report.enqueue_p50_ms:.1f} / {report.enqueue_p95_ms:.1f} ms",
                f"- ledger P50/P95: {report.ledger_p50_ms} / {report.ledger_p95_ms} ms",
                f"- applied={report.applied} failed={report.failed} "
                f"double={report.double_credit} cap_skip={report.skipped_cap}",
                f"- pass_enqueue={report.pass_enqueue} pass_ledger={report.pass_ledger} "
                f"pass_correctness={report.pass_correctness}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Points async award perf harness")
    parser.add_argument(
        "--scenario",
        default="P1",
        choices=["P1", "P2", "P3", "P4", "P5", "P6"],
    )
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--sync", action="store_true", help="强制同步入账对照")
    parser.add_argument("--wait-timeout", type=float, default=20.0)
    parser.add_argument(
        "--out-dir",
        default=str(BACKEND_ROOT / "test/points/_perf_reports"),
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--queue",
        default=os.environ.get("POINTS_AWARD_CELERY_QUEUE", "points_award_local"),
        help="异步发分队列；共享 Broker 时需本地 Worker 单独监听，避免旧节点抢走任务",
    )
    args = parser.parse_args()
    run_id = args.run_id or uuid.uuid4().hex[:12]
    if not args.sync and args.queue:
        os.environ["POINTS_AWARD_CELERY_QUEUE"] = args.queue

    report = asyncio.run(
        run_scenario(
            args.scenario,
            n=args.n,
            concurrency=args.concurrency,
            sync=args.sync,
            wait_timeout_s=args.wait_timeout,
            run_id=run_id,
        )
    )
    path = _write_report(report, Path(args.out_dir))
    summary = {k: v for k, v in asdict(report).items() if k != "samples"}
    print("PERF_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    print(f"report={path}")
    if not (report.pass_correctness and report.pass_ledger and (report.pass_enqueue or report.sync)):
        sys.exit(2)


if __name__ == "__main__":
    main()
