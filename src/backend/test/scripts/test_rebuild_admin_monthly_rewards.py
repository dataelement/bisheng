"""管理员月奖重发的入账时间和余额链。不连接数据库。"""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rebuild_admin_monthly_rewards.py"
SPEC = importlib.util.spec_from_file_location("rebuild_admin_monthly_rewards", SCRIPT)
script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = script
SPEC.loader.exec_module(script)


def _log(log_id, occurred_at, delta, balance_after, *, direction="earn", key=None):
    return script.LedgerEntry(
        id=log_id,
        user_id=7,
        occurred_at=occurred_at,
        delta=delta,
        balance_after=balance_after,
        direction=direction,
        idempotency_key=key or f"other:{log_id}",
    )


def test_award_occurred_at_is_first_day_of_next_month():
    assert script.award_occurred_at("2026-09") == datetime(2026, 10, 1, 0, 5)
    assert script.award_occurred_at("2026-10") == datetime(2026, 11, 1, 0, 5)
    assert script.award_occurred_at("2026-12") == datetime(2027, 1, 1, 0, 5)


def test_validate_scores_accepts_only_expected_enabled_rules():
    assert (
        script.validate_admin_reward_scores([("M1", "enabled", 200), ("M4", "enabled", 100), ("M6", "enabled", 50)])
        == []
    )
    problems = script.validate_admin_reward_scores(
        [("M1", "enabled", 300), ("M4", "enabled", 100), ("M6", "disabled", 50)]
    )
    assert any("M1" in item for item in problems)
    assert any("M6" in item for item in problems)


def test_rebuild_shifts_later_balances_and_keeps_later_last_earned_at():
    logs = [
        _log(1, datetime(2026, 9, 2, 9, 0), 10, 10),
        _log(2, datetime(2026, 10, 1, 0, 5), 300, 310, key="reward:M1:7:2026-09"),
        _log(3, datetime(2026, 11, 3, 8, 0), 5, 315),
    ]
    award = script.NewAward(
        user_id=7,
        period_key="2026-09",
        rule_code="M1",
        delta=200,
        occurred_at=datetime(2026, 10, 1, 0, 5),
        title="公共库所有者月奖",
        idempotency_key="reward:M1:7:2026-09",
    )
    plan = script.plan_user_rebuild(
        logs,
        account_balance=315,
        delete_ids={2},
        new_awards=[award],
    )
    assert plan.balance_delta == -100
    assert plan.lifetime_earned_delta == -100
    assert 1 not in plan.balance_updates
    assert plan.balance_updates[3] == 15
    assert plan.new_balances[0][1] == 215
    assert plan.new_balances[0][0].occurred_at == datetime(2026, 10, 1, 0, 5)
    assert plan.last_earned_at == datetime(2026, 11, 3, 8, 0)


def test_two_months_insert_on_their_own_dates():
    logs = [
        _log(1, datetime(2026, 10, 1, 0, 5), 300, 300, key="reward:M1:7:2026-09"),
        _log(2, datetime(2026, 11, 1, 0, 5), 200, 500, key="reward:M4:7:2026-10"),
    ]
    awards = [
        script.NewAward(
            user_id=7,
            period_key="2026-09",
            rule_code="M1",
            delta=200,
            occurred_at=script.award_occurred_at("2026-09"),
            title="M1",
            idempotency_key="reward:M1:7:2026-09",
        ),
        script.NewAward(
            user_id=7,
            period_key="2026-10",
            rule_code="M4",
            delta=100,
            occurred_at=script.award_occurred_at("2026-10"),
            title="M4",
            idempotency_key="reward:M4:7:2026-10",
        ),
    ]
    plan = script.plan_user_rebuild(logs, account_balance=500, delete_ids={1, 2}, new_awards=awards)
    assert [item[1] for item in plan.new_balances] == [200, 300]
    assert [item[0].occurred_at for item in plan.new_balances] == [
        datetime(2026, 10, 1, 0, 5),
        datetime(2026, 11, 1, 0, 5),
    ]
    assert plan.balance_delta == -200
    assert plan.last_earned_at == datetime(2026, 11, 1, 0, 5)


def test_removed_admin_drops_award_and_recomputes_last_earned_at():
    logs = [
        _log(1, datetime(2026, 9, 2, 9, 0), 10, 10),
        _log(2, datetime(2026, 10, 1, 0, 5), 80, 90, key="reward:M6:7:2026-09"),
    ]
    plan = script.plan_user_rebuild(logs, account_balance=90, delete_ids={2}, new_awards=[])
    assert plan.balance_delta == -80
    assert plan.new_balances == ()
    assert plan.last_earned_at == datetime(2026, 9, 2, 9, 0)


def test_monthly_rows_outside_m1_m4_m6_are_left_alone():
    class Row:
        def __init__(self, user_id):
            self.user_id = user_id

    rows = [Row(1), Row(12620), Row(7)]
    kept = script.rows_for_candidates(rows, {1, 7})
    assert [row.user_id for row in kept] == [1, 7]


def test_backfill_balance_mismatch_does_not_block_monthly_delta():
    logs = [
        _log(10, datetime(2026, 11, 2, 9, 0), 2, 2),
        _log(20, datetime(2026, 8, 1, 0, 0), 142, 144),
        _log(30, datetime(2026, 10, 1, 0, 5), 300, 444, key="reward:M1:7:2026-09"),
    ]
    award = script.NewAward(
        user_id=7,
        period_key="2026-09",
        rule_code="M1",
        delta=200,
        occurred_at=datetime(2026, 10, 1, 0, 5),
        title="公共库所有者月奖",
        idempotency_key="reward:M1:7:2026-09",
    )
    plan = script.plan_user_rebuild(logs, account_balance=444, delete_ids={30}, new_awards=[award])
    assert plan.balance_delta == -100
    assert plan.balance_updates == {}
    assert plan.new_balances[0][1] == 344
