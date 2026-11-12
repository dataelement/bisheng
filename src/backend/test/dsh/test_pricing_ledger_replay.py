"""F015 ledger events with price snapshots: billing, legacy replay, identity hashes, overflow."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bisheng.dsh.domain.schemas.pricing import CreditSettingState, PricingSnapshot
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.domain.services.pricing import build_snapshot
from bisheng.dsh.infrastructure.quota_redis import QuotaRedis

DEEPSEEK = {
    "currency": "CNY",
    "input": "9",
    "cache_read": "0.3",
    "cache_write": None,
    "output": "27",
    "source": "CATALOG",
}
GPT41 = {"currency": "USD", "input": "2", "cache_read": "0.5", "cache_write": None, "output": "8", "source": "CATALOG"}


def event(**changes):
    values = {
        "request_id": "8c4f6a9e-1d2b-4c3d-9e8f-0a1b2c3d4e5f",
        "tenant_id": 2,
        "user_id": 20,
        "session_id": "8c4f6a9e-1d2b-4c3d-9e8f-0a1b2c3d4e5f",
        "model_id": 4,
        "usage_month": "2026-11",
        "billing_timezone": "Asia/Shanghai",
        "policy_version": 1,
        "event_version": 1,
        "quota_epoch": 1,
        "status": "RUNNING",
        "started_at": datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
    }
    values.update(changes)
    return UsageEvent(**values)


def settled(**changes):
    values = {
        "event_version": 2,
        "status": "SUCCEEDED",
        "usage_source": "PROVIDER",
        "input_tokens": 30_000,
        "output_tokens": 1_000,
        "total_tokens": 31_000,
        "cache_read_tokens": 24_000,
        "cache_creation_tokens": 0,
    }
    values.update(changes)
    return event(**values)


def test_priced_event_bills_by_snapshot():
    priced = settled(pricing=build_snapshot(DEEPSEEK, CreditSettingState()))
    assert priced.billed_tokens == 8_820_000
    assert priced.cost_micro == 88_200
    assert priced.currency == "CNY"


def test_unpriced_event_keeps_legacy_formula_for_replay():
    legacy = settled(credit_rate=150)
    assert legacy.pricing is None
    assert legacy.billed_tokens == (31_000 * 150 + 99) // 100
    assert legacy.cost_micro is None and legacy.currency is None


def test_unknown_usage_bills_nothing_with_or_without_snapshot():
    snapshot = build_snapshot(DEEPSEEK, CreditSettingState())
    for running in (event(), event(pricing=snapshot)):
        assert running.billed_tokens is None
        assert running.cost_micro is None


def test_priced_event_round_trips_through_redis_json():
    priced = settled(pricing=build_snapshot(GPT41, CreditSettingState()))
    restored = UsageEvent.model_validate_json(priced.model_dump_json())
    assert restored == priced
    assert restored.billed_tokens == priced.billed_tokens == 23_040_000
    # Recovery rebuilds events from SQL rows through json.dumps + model_validate_json.
    assert UsageEvent.model_validate_json(json.dumps(json.loads(priced.model_dump_json()))).billed_tokens == 23_040_000


def test_unpriced_event_json_has_no_pricing_key():
    assert "pricing" not in json.loads(settled().model_dump_json(exclude_none=True))
    assert json.loads(settled().model_dump_json())["pricing"] is None


def test_billing_overflow_is_rejected():
    huge = PricingSnapshot(
        currency="CNY",
        credit_value_micro=1,
        input_micro=10**15,
        cache_read_micro=0,
        cache_write_micro=0,
        output_micro=0,
    )
    with pytest.raises(ValidationError):
        settled(pricing=huge, input_tokens=10**7, cache_read_tokens=0, output_tokens=0, total_tokens=10**7)


def test_identity_hash_of_unpriced_events_is_unchanged():
    # Golden values computed on the pre-F015 tree (3254ab555); in-flight events must keep their hash.
    assert QuotaRedis._identity(event()) == "01d3c0828337f364fce71f8dde687304055571b7e0a2baa4261f39e0bbfe55f3"
    assert (
        QuotaRedis._identity(event(credit_rate=150))
        == "30efbe0c34871a5ea04f8ff9db9e0cee83a9275e3746580678849c5fa1fd2627"
    )


def test_identity_hash_fences_the_price_snapshot():
    snapshot = build_snapshot(DEEPSEEK, CreditSettingState())
    other = build_snapshot({**DEEPSEEK, "output": "54"}, CreditSettingState())
    base = QuotaRedis._identity(event())
    assert QuotaRedis._identity(event(pricing=snapshot)) != base
    assert QuotaRedis._identity(event(pricing=snapshot)) != QuotaRedis._identity(event(pricing=other))
    # Settlement fields are not part of the identity.
    assert QuotaRedis._identity(settled(pricing=snapshot)) == QuotaRedis._identity(event(pricing=snapshot))


# --- SQL projection and recovery (T10) ---------------------------------------------------------

from sqlalchemy import select  # noqa: E402
from sqlmodel import Session  # noqa: E402

from bisheng.dsh.domain.models.model_call import DshModelCall  # noqa: E402
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage  # noqa: E402
from bisheng.dsh.domain.repositories.usage import DshUsageRepository  # noqa: E402
from test.dsh.test_usage_repository import event as repo_event  # noqa: E402
from test.dsh.test_usage_repository import usage_db as usage_db  # noqa: E402

SETTLED = {
    "event_version": 2,
    "status": "SUCCEEDED",
    "usage_source": "PROVIDER",
    "input_tokens": 30_000,
    "output_tokens": 1_000,
    "total_tokens": 31_000,
    "cache_read_tokens": 24_000,
    "cache_creation_tokens": 0,
}


def test_projection_persists_snapshot_cost_and_currency(usage_db):
    snapshot = build_snapshot(GPT41, CreditSettingState())
    running = repo_event(pricing=snapshot)
    terminal = running.model_copy(update=SETTLED)
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([running, terminal])
    with Session(usage_db) as session:
        row = session.get(DshModelCall, running.request_id)
        assert row.pricing == json.loads(snapshot.model_dump_json())
        assert (row.billed_tokens, row.cost_micro, row.currency) == (23_040_000, 230_400, "CNY")
        assert next(iter(session.scalars(select(DshMonthlyUsage)))).used_tokens == 23_040_000


def test_projection_rejects_a_changed_snapshot_for_the_same_request(usage_db):
    running = repo_event(pricing=build_snapshot(DEEPSEEK, CreditSettingState()))
    tampered = running.model_copy(
        update={**SETTLED, "pricing": build_snapshot({**DEEPSEEK, "output": "1"}, CreditSettingState())}
    )
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([running])
    with pytest.raises(ValueError, match="price snapshot is immutable"):
        with Session(usage_db) as session, session.begin():
            DshUsageRepository(session).project_batch([tampered])


def test_unpriced_rows_project_without_cost(usage_db):
    legacy = repo_event(credit_rate=150, **SETTLED)
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([legacy])
    with Session(usage_db) as session:
        row = session.get(DshModelCall, legacy.request_id)
        assert row.pricing is None and row.cost_micro is None and row.currency is None
        assert row.billed_tokens == (31_000 * 150 + 99) // 100


def test_recovery_rebuilds_a_month_mixing_legacy_and_priced_calls(usage_db):
    # Recovery reads the user's home tenant (F009); the shared usage_db fixture predates that.
    from sqlmodel import SQLModel

    from bisheng.database.models.department import Department, UserDepartment
    from bisheng.database.models.tenant import UserTenant
    from bisheng.user.domain.models.user import User

    SQLModel.metadata.create_all(usage_db, tables=[User.__table__, UserTenant.__table__])
    with Session(usage_db) as session, session.begin():
        session.add(User(user_id=20, user_name="usage-user", password="unused"))
        session.add(UserTenant(user_id=20, tenant_id=2, is_default=1, is_active=1, status="active"))
        session.add(Department(id=10, dept_id="root", name="usage-root", tenant_id=2, path="/10/"))
        session.add(UserDepartment(id=1, user_id=20, department_id=10, is_primary=1))
    legacy = repo_event(credit_rate=150, **SETTLED)
    priced = repo_event(pricing=build_snapshot(DEEPSEEK, CreditSettingState()), **SETTLED)
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([legacy, priced])
    with Session(usage_db) as session, session.begin():
        events, _ = DshUsageRepository(session).recovery_snapshot(20, billing_timezone="Asia/Shanghai")
    billed = {item.request_id: item.billed_tokens for item in events}
    assert billed == {legacy.request_id: (31_000 * 150 + 99) // 100, priced.request_id: 8_820_000}
    assert next(e for e in events if e.request_id == priced.request_id).pricing == priced.pricing
