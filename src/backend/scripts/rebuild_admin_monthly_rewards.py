#!/usr/bin/env python3
"""按当前管理员名单重发指定月份的管理员月奖。

已确认的 2026-09、2026-10 修复方式:

1. 不修改 point_rule。M1、M4、M6 必须已经是启用且分值为 200、100、50,否则停止且不删流水。
2. 删除这两个 biz_id 上 source=monthly_reward 的全部流水,并按原 delta 扣回余额。
3. 按当前知识空间所有者/管理员重新圈人,多规则取最高分,平台超管不发。
4. 用当前月奖配置写入新流水。9 月记 2026-10-01 00:05,10 月记 2026-11-01 00:05(北京时间,naive)。
5. 新流水插回该时刻,重算其后的 balance_after。不发站内信。
6. last_earned_at 取该用户剩余获得流水的最晚时间,不把账户最近获得时间改早。

默认只预览。写入必须显式 --apply。执行前暂停积分发放和月奖任务。

在 src/backend 目录运行::

    PYTHONPATH=./ .venv/bin/python scripts/rebuild_admin_monthly_rewards.py
    PYTHONPATH=./ .venv/bin/python scripts/rebuild_admin_monthly_rewards.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_PERIODS = ("2026-09", "2026-10")
EXPECTED_SCORES = {"M1": 200, "M4": 100, "M6": 50}
SOURCE_MONTHLY = "monthly_reward"


class RebuildRejected(Exception):
    """预览或写入前发现不能继续的数据问题。"""


@dataclass(frozen=True)
class LedgerEntry:
    """规划用的一条已有流水。"""

    id: int
    user_id: int
    occurred_at: datetime
    delta: int
    balance_after: int
    direction: str
    idempotency_key: str


@dataclass(frozen=True)
class NewAward:
    """待插入的一笔月奖。"""

    user_id: int
    period_key: str
    rule_code: str
    delta: int
    occurred_at: datetime
    title: str
    idempotency_key: str


@dataclass(frozen=True)
class UserRebuildPlan:
    """单个用户删旧奖、插新奖后的余额计划。"""

    delete_ids: tuple[int, ...]
    balance_updates: dict[int, int]
    new_balances: tuple[tuple[NewAward, int], ...]
    balance_delta: int
    lifetime_earned_delta: int
    last_earned_at: datetime | None


def award_occurred_at(period_key: str) -> datetime:
    """月奖入账时间:结算月的次月 1 日 00:05(naive,上海墙钟)。"""
    year_text, month_text = period_key.split("-")
    year, month = int(year_text), int(month_text)
    if month == 12:
        return datetime(year + 1, 1, 1, 0, 5)
    return datetime(year, month + 1, 1, 0, 5)


def monthly_idempotency_key(rule_code: str, user_id: int, period_key: str) -> str:
    """与月奖任务相同的幂等键。"""
    return f"reward:{rule_code}:{user_id}:{period_key}"


def validate_admin_reward_scores(rules: list[tuple[str, str, int]]) -> list[str]:
    """M1/M4/M6 必须启用且等于 200/100/50。返回问题列表,空列表表示通过。"""
    found = {code: (status, score) for code, status, score in rules}
    problems: list[str] = []
    for code, expected in EXPECTED_SCORES.items():
        current = found.get(code)
        if current is None:
            problems.append(f"{code} 不存在")
            continue
        status, score = current
        if status != "enabled" or score != expected:
            problems.append(f"{code} 当前 status={status} score={score},要求 enabled/{expected}")
    return problems


def _sort_logs(logs: list[LedgerEntry]) -> list[LedgerEntry]:
    return sorted(logs, key=lambda row: (row.occurred_at, row.id))


def opening_balance(logs: list[LedgerEntry]) -> int:
    """第一条流水之前的余额。"""
    first = _sort_logs(logs)[0]
    return int(first.balance_after) - int(first.delta)


def assert_chain(logs: list[LedgerEntry], account_balance: int, *, user_id: int) -> None:
    """已有流水的 balance_after 必须能从前往后加总到账户余额。"""
    if not logs:
        if account_balance != 0:
            raise RebuildRejected(f"user {user_id} 没有流水但余额是 {account_balance}")
        return
    running = opening_balance(logs)
    for row in _sort_logs(logs):
        running += int(row.delta)
        if running != int(row.balance_after):
            raise RebuildRejected(
                f"user {user_id} log {row.id} balance_after={row.balance_after},按流水累加应为 {running}"
            )
    if running != account_balance:
        raise RebuildRejected(f"user {user_id} 账户余额 {account_balance} 与最后一条流水 {running} 不一致")


def plan_user_rebuild(
    logs: list[LedgerEntry],
    *,
    account_balance: int,
    delete_ids: set[int],
    new_awards: list[NewAward],
) -> UserRebuildPlan:
    """删掉指定流水并按入账时间插入新奖,返回余额调整。"""
    if not logs and not new_awards:
        raise RebuildRejected("没有可处理的流水")
    user_ids = {row.user_id for row in logs} | {row.user_id for row in new_awards}
    if len(user_ids) != 1:
        raise RebuildRejected(f"一次只能规划一个用户,当前 {sorted(user_ids)}")
    user_id = next(iter(user_ids))
    known_ids = {row.id for row in logs}
    missing = delete_ids - known_ids
    if missing:
        raise RebuildRejected(f"user {user_id} 缺少待删流水 {sorted(missing)}")
    for row in logs:
        if row.id in delete_ids and (row.delta <= 0 or row.direction != "earn"):
            raise RebuildRejected(f"user {user_id} log {row.id} 不是正向获得流水,delta={row.delta}")
    assert_chain(logs, account_balance, user_id=user_id)

    kept = [row for row in logs if row.id not in delete_ids]
    kept_keys = {row.idempotency_key for row in kept}
    for award in new_awards:
        if award.idempotency_key in kept_keys:
            raise RebuildRejected(f"user {user_id} 幂等键仍被其他流水占用: {award.idempotency_key}")
        if award.delta <= 0:
            raise RebuildRejected(f"user {user_id} 新月奖分值必须为正")

    opening = opening_balance(logs) if logs else 0
    combined: list[tuple[str, LedgerEntry | NewAward]] = [("old", row) for row in kept]
    combined.extend(("new", award) for award in new_awards)
    combined.sort(
        key=lambda item: (
            item[1].occurred_at,
            0 if item[0] == "old" else 1,
            item[1].id if item[0] == "old" else 0,
        )
    )
    running = opening
    balance_updates: dict[int, int] = {}
    new_balances: list[tuple[NewAward, int]] = []
    earn_times: list[datetime] = []
    for kind, item in combined:
        running += int(item.delta)
        if kind == "old":
            assert isinstance(item, LedgerEntry)
            if int(item.balance_after) != running:
                balance_updates[item.id] = running
            if item.direction == "earn" and item.delta > 0:
                earn_times.append(item.occurred_at)
        else:
            assert isinstance(item, NewAward)
            new_balances.append((item, running))
            earn_times.append(item.occurred_at)
    deleted_sum = sum(row.delta for row in logs if row.id in delete_ids)
    added_sum = sum(award.delta for award in new_awards)
    balance_delta = running - account_balance
    if balance_delta != added_sum - deleted_sum:
        raise RebuildRejected(f"user {user_id} 余额差额 {balance_delta} 与删插分值 {added_sum - deleted_sum} 不一致")
    return UserRebuildPlan(
        delete_ids=tuple(sorted(delete_ids)),
        balance_updates=balance_updates,
        new_balances=tuple(new_balances),
        balance_delta=balance_delta,
        lifetime_earned_delta=added_sum - deleted_sum,
        last_earned_at=max(earn_times) if earn_times else None,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    raise TypeError(f"无法备份的数据类型: {type(value).__name__}")


def save_backup(directory: Path, document: dict[str, Any]) -> Path:
    """独占创建 0600 备份,写盘成功后才允许提交删除。"""
    content = json.dumps(document, ensure_ascii=False, indent=2, default=_json_default)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"monthly_reward_rebuild_t{document['tenant_id']}_{uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, default=1)
    parser.add_argument(
        "--period",
        action="append",
        dest="periods",
        help="结算月 YYYY-MM,可重复。默认 2026-09 和 2026-10",
    )
    parser.add_argument("--apply", action="store_true", help="确认后写入。缺省只预览")
    parser.add_argument("--config", help="BiSheng 配置文件名或路径")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("points-backups"),
        help="--apply 时的删除备份目录",
    )
    return parser


async def _load_rules(tenant_id: int):
    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        return await repo.list_rules(tenant_id, rule_type="admin_reward")


async def _ensure_openfga() -> None:
    """脚本不在 FastAPI 进程里, 先按 Worker 的方式初始化 OpenFGA."""
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import app_context
    from bisheng.core.openfga.manager import FGAManager, aget_fga_client

    if not settings.openfga.enabled:
        raise RebuildRejected("OpenFGA 未启用, 未删除任何流水")
    try:
        app_context.get_context("openfga")
    except KeyError:
        app_context.register_context(FGAManager(openfga_config=settings.openfga), optional=True)
    client = await aget_fga_client()
    if client is None:
        raise RebuildRejected("OpenFGA 客户端未初始化, 未删除任何流水")


async def _collect_candidates(rules) -> dict[int, tuple[str, int]]:
    from bisheng.points.domain.constants.monthly_reward_rules import (
        MONTHLY_RULE_MATCHERS,
        fixed_score,
    )
    from bisheng.points.domain.services.points_monthly_reward_service import PointsMonthlyRewardService
    from bisheng.points.domain.services.space_fga_roles import SpaceFgaRolesError

    rule_by_code = {rule.rule_code: rule for rule in rules if rule.status == "enabled"}
    active = {
        code: matcher
        for code, matcher in MONTHLY_RULE_MATCHERS.items()
        if code in rule_by_code and fixed_score(rule_by_code[code].score_expr) > 0
    }
    service = PointsMonthlyRewardService()
    try:
        candidates = await service._collect_user_candidates(active, rule_by_code)
    except SpaceFgaRolesError as exc:
        raise RebuildRejected(f"OpenFGA 不可用,未删除任何流水: {exc}") from exc
    exclude = await service._load_super_admin_ids()
    return {user_id: pair for user_id, pair in candidates.items() if user_id not in exclude}


def _awards_for(candidates: dict[int, tuple[str, int]], rules, periods: tuple[str, ...]) -> list[NewAward]:
    from bisheng.points.domain.constants.rule_display_name import resolve_point_rule_display_name

    by_code = {rule.rule_code: rule for rule in rules}
    awards: list[NewAward] = []
    for period in periods:
        occurred = award_occurred_at(period)
        for user_id, (rule_code, score) in sorted(candidates.items()):
            awards.append(
                NewAward(
                    user_id=int(user_id),
                    period_key=period,
                    rule_code=rule_code,
                    delta=int(score),
                    occurred_at=occurred,
                    title=resolve_point_rule_display_name(by_code[rule_code]),
                    idempotency_key=monthly_idempotency_key(rule_code, int(user_id), period),
                )
            )
    return awards


async def _load_monthly_logs(tenant_id: int, periods: tuple[str, ...]):
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.models import UserPointLog

    async with get_async_db_session() as session:
        rows = (
            await session.exec(
                select(UserPointLog).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.source == SOURCE_MONTHLY,
                    UserPointLog.biz_id.in_(periods),
                )
            )
        ).all()
    return list(rows)


async def _load_user_state(tenant_id: int, user_ids: list[int]):
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.models import UserPointLog
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        accounts = {}
        for user_id in user_ids:
            accounts[user_id] = await repo.find_account(tenant_id, user_id)
        logs = (
            await session.exec(
                select(UserPointLog).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.user_id.in_(user_ids),
                )
            )
        ).all()
    grouped = _entries_from_rows(logs)
    for user_id in user_ids:
        grouped.setdefault(user_id, [])
    balances = {user_id: int(account.balance) if account is not None else 0 for user_id, account in accounts.items()}
    return grouped, balances


def _plans_for(
    user_ids: list[int],
    logs_by_user: dict[int, list[LedgerEntry]],
    balances: dict[int, int],
    delete_ids_by_user: dict[int, set[int]],
    awards_by_user: dict[int, list[NewAward]],
) -> dict[int, UserRebuildPlan]:
    plans: dict[int, UserRebuildPlan] = {}
    for user_id in user_ids:
        plans[user_id] = plan_user_rebuild(
            logs_by_user.get(user_id, []),
            account_balance=balances.get(user_id, 0),
            delete_ids=delete_ids_by_user.get(user_id, set()),
            new_awards=awards_by_user.get(user_id, []),
        )
    return plans


def _print_preview(
    periods: tuple[str, ...], monthly_rows, awards: list[NewAward], plans: dict[int, UserRebuildPlan]
) -> None:
    print(f"periods={','.join(periods)}")
    print(f"delete_rows={len(monthly_rows)} award_rows={len(awards)} users={len(plans)}")
    delete_groups: dict[tuple[str, str, int], int] = {}
    for row in monthly_rows:
        key = (str(row.biz_id), str(row.rule_code), int(row.delta))
        delete_groups[key] = delete_groups.get(key, 0) + 1
    for (period, rule_code, delta), count in sorted(delete_groups.items()):
        print(f"delete period={period} rule={rule_code} delta={delta} count={count}")
    award_groups: dict[tuple[str, str, int, str], int] = {}
    for award in awards:
        key = (award.period_key, award.rule_code, award.delta, award.occurred_at.isoformat(sep=" "))
        award_groups[key] = award_groups.get(key, 0) + 1
    for (period, rule_code, delta, occurred), count in sorted(award_groups.items()):
        print(f"award period={period} rule={rule_code} delta={delta} occurred_at={occurred} count={count}")
    net = sum(plan.balance_delta for plan in plans.values())
    print(f"net_balance_delta={net}")
    for user_id, plan in sorted(plans.items()):
        if plan.balance_delta == 0 and not plan.delete_ids and not plan.new_balances:
            continue
        print(
            f"user={user_id} delete={len(plan.delete_ids)} award={len(plan.new_balances)} "
            f"balance_delta={plan.balance_delta} last_earned_at={plan.last_earned_at}"
        )


def _entries_from_rows(rows) -> dict[int, list[LedgerEntry]]:
    grouped: dict[int, list[LedgerEntry]] = {}
    for row in rows:
        grouped.setdefault(int(row.user_id), []).append(
            LedgerEntry(
                id=int(row.id),
                user_id=int(row.user_id),
                occurred_at=row.occurred_at,
                delta=int(row.delta),
                balance_after=int(row.balance_after),
                direction=row.direction,
                idempotency_key=row.idempotency_key,
            )
        )
    return grouped


async def _apply(
    tenant_id: int,
    periods: tuple[str, ...],
    user_ids: list[int],
    expected_delete_ids: set[int],
    awards_by_user: dict[int, list[NewAward]],
) -> None:
    """锁定账户后按当前流水重算并提交。待删月奖集合变化则回滚。"""
    from sqlalchemy import delete as sql_delete
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.points.domain.models import PointSyncOutbox, UserPointLog
    from bisheng.points.domain.repositories.points_repository import PointsRepository

    async with get_async_db_session() as session:
        repo = PointsRepository(session)
        accounts = {}
        for user_id in sorted(user_ids):
            accounts[user_id] = await repo.lock_or_create_account(tenant_id, user_id)
        locked_logs = (
            await session.exec(
                select(UserPointLog).where(
                    UserPointLog.tenant_id == tenant_id,
                    UserPointLog.user_id.in_(user_ids),
                )
            )
        ).all()
        current_monthly_ids = {
            int(row.id) for row in locked_logs if row.source == SOURCE_MONTHLY and row.biz_id in periods
        }
        if current_monthly_ids != expected_delete_ids:
            raise RebuildRejected("锁定后月奖流水已变化,已回滚")
        logs_by_user = _entries_from_rows(locked_logs)
        balances = {user_id: int(account.balance) for user_id, account in accounts.items()}
        delete_ids_by_user: dict[int, set[int]] = {user_id: set() for user_id in user_ids}
        for row in locked_logs:
            if int(row.id) in expected_delete_ids:
                delete_ids_by_user.setdefault(int(row.user_id), set()).add(int(row.id))
        plans = _plans_for(user_ids, logs_by_user, balances, delete_ids_by_user, awards_by_user)
        by_id = {int(row.id): row for row in locked_logs}
        if expected_delete_ids:
            await session.exec(sql_delete(PointSyncOutbox).where(PointSyncOutbox.log_id.in_(expected_delete_ids)))
            for log_id in expected_delete_ids:
                await session.delete(by_id[log_id])
            # 同一幂等键会立刻插回。先把删除刷进事务, 避免插入撞上尚未删除的唯一键。
            await session.flush()
        for user_id, plan in plans.items():
            for log_id, balance_after in plan.balance_updates.items():
                by_id[log_id].balance_after = balance_after
            account = accounts[user_id]
            if int(account.lifetime_earned) + plan.lifetime_earned_delta < 0:
                raise RebuildRejected(f"user {user_id} lifetime_earned 将变为负数,已回滚")
            account.balance = int(account.balance) + plan.balance_delta
            account.lifetime_earned = int(account.lifetime_earned) + plan.lifetime_earned_delta
            account.version = int(account.version) + 1
            account.last_earned_at = plan.last_earned_at
            for award, balance_after in plan.new_balances:
                created = UserPointLog(
                    tenant_id=tenant_id,
                    user_id=award.user_id,
                    delta=award.delta,
                    balance_after=balance_after,
                    direction="earn",
                    rule_code=award.rule_code,
                    title=award.title[:64],
                    source=SOURCE_MONTHLY,
                    biz_type=SOURCE_MONTHLY,
                    biz_id=award.period_key,
                    idempotency_key=award.idempotency_key,
                    score_snapshot=award.delta,
                    beneficiary_role="subject",
                    occurred_at=award.occurred_at,
                )
                session.add(created)
                await session.flush()
                session.add(
                    PointSyncOutbox(
                        tenant_id=tenant_id,
                        log_id=int(created.id),
                        payload={"user_id": award.user_id, "delta": award.delta, "log_id": int(created.id)},
                    )
                )
        await session.commit()


async def _refresh_ranks(tenant_id: int, periods: tuple[str, ...]) -> None:
    from bisheng.points.domain.services.points_rank_service import PointsRankService

    service = PointsRankService()
    seen: set[tuple[int, int]] = set()
    for period in periods:
        occurred = award_occurred_at(period)
        marker = (occurred.year, occurred.month)
        if marker in seen:
            continue
        seen.add(marker)
        anchor = datetime(occurred.year, occurred.month, 15, tzinfo=SHANGHAI)
        await service.refresh_rank_snapshots(tenant_id, now=anchor)
    await service.refresh_rank_snapshots(tenant_id)


async def run(args: argparse.Namespace) -> int:
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.points.domain.constants.monthly_reward_rules import fixed_score

    periods = tuple(args.periods or DEFAULT_PERIODS)
    for period in periods:
        datetime.strptime(period, "%Y-%m")
    set_current_tenant_id(int(args.tenant_id))
    rules = await _load_rules(int(args.tenant_id))
    problems = validate_admin_reward_scores(
        [(rule.rule_code, rule.status, fixed_score(rule.score_expr)) for rule in rules]
    )
    if problems:
        print("规则分值不符合预期,未删除流水:")
        for problem in problems:
            print(f"- {problem}")
        return 2
    await _ensure_openfga()
    candidates = await _collect_candidates(rules)
    awards = _awards_for(candidates, rules, periods)
    monthly_rows = await _load_monthly_logs(int(args.tenant_id), periods)
    user_ids = sorted({int(row.user_id) for row in monthly_rows} | {award.user_id for award in awards})
    if not user_ids:
        print("没有待删除的月奖流水,也没有当前管理员可发。")
        return 0
    logs_by_user, balances = await _load_user_state(int(args.tenant_id), user_ids)
    delete_ids_by_user: dict[int, set[int]] = {user_id: set() for user_id in user_ids}
    for row in monthly_rows:
        delete_ids_by_user.setdefault(int(row.user_id), set()).add(int(row.id))
    awards_by_user: dict[int, list[NewAward]] = {user_id: [] for user_id in user_ids}
    for award in awards:
        awards_by_user.setdefault(award.user_id, []).append(award)
    plans = _plans_for(user_ids, logs_by_user, balances, delete_ids_by_user, awards_by_user)
    _print_preview(periods, monthly_rows, awards, plans)
    if not args.apply:
        print("dry-run,未写入。")
        return 0

    backup = {
        "tenant_id": int(args.tenant_id),
        "periods": list(periods),
        "deleted": [
            {
                "id": int(row.id),
                "user_id": int(row.user_id),
                "rule_code": row.rule_code,
                "delta": int(row.delta),
                "balance_after": int(row.balance_after),
                "biz_id": row.biz_id,
                "occurred_at": row.occurred_at,
                "idempotency_key": row.idempotency_key,
            }
            for row in monthly_rows
        ],
        "awards": [
            {
                "user_id": award.user_id,
                "period_key": award.period_key,
                "rule_code": award.rule_code,
                "delta": award.delta,
                "occurred_at": award.occurred_at,
                "idempotency_key": award.idempotency_key,
            }
            for award in awards
        ],
    }
    backup_path = save_backup(args.backup_dir, backup)
    print(f"backup={backup_path}")
    await _apply(
        int(args.tenant_id),
        periods,
        user_ids,
        {int(row.id) for row in monthly_rows},
        awards_by_user,
    )
    print("ledger=committed")
    try:
        await _refresh_ranks(int(args.tenant_id), periods)
    except Exception as exc:
        print(f"榜单刷新失败,流水已提交: {type(exc).__name__}: {exc}")
        return 4
    print("rank=refreshed")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.config:
        os.environ["config"] = args.config
    try:
        return asyncio.run(run(args))
    except RebuildRejected as exc:
        print(f"已停止,未写入: {exc}" if not args.apply else f"已停止: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
