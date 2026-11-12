"""F015 call-start pricing on the web path: fresh reads, free models, missing prices, settlement."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, create_engine

from bisheng.common.errcode.dsh import DshModelPricingMissingError
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.pricing import CreditSettingState, PricingSnapshot
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.domain.services import chat_credits
from bisheng.dsh.domain.services.model import DshModelService
from bisheng.dsh.domain.services.pricing import build_snapshot

DEEPSEEK = {"currency": "CNY", "input": "9", "cache_read": "0.3", "output": "27", "source": "CATALOG"}
FREE = {"currency": "CNY", "input": "0", "cache_read": "0", "output": "0", "source": "DEFAULT"}


@pytest.fixture
def chat_env(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import tenant
    from bisheng.dsh import runtime
    from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords

    monkeypatch.setattr(tenant, "get_current_tenant_id", lambda: 1)
    monkeypatch.setattr(
        CurrentIdentityRecords,
        "get",
        AsyncMock(return_value=SimpleNamespace(active=True, tenant_active=True, natural_person=True)),
    )
    monkeypatch.setattr(
        runtime,
        "read_policy",
        AsyncMock(
            return_value=SimpleNamespace(
                allowed_model_ids=[7],
                rows=[SimpleNamespace(model_id=7, credit_rate=100)],
                version=1,
                quota_epoch=1,
                monthly_token_limit=1_000_000,
            )
        ),
    )
    admission = AsyncMock(side_effect=lambda event, **kwargs: event)
    service = SimpleNamespace(activate=AsyncMock(), usage=SimpleNamespace(check_and_start=admission), model=object())
    monkeypatch.setattr(runtime, "get_model_runtime", AsyncMock(return_value=service))
    prices = {"value": dict(DEEPSEEK)}
    monkeypatch.setattr(runtime, "read_model_pricing", AsyncMock(side_effect=lambda model_id: prices["value"]))
    monkeypatch.setattr(runtime, "read_credit_setting", AsyncMock(return_value=CreditSettingState()))
    monkeypatch.setitem(settings.__dict__, "dsh", settings.dsh.model_copy(update={"billing_timezone": "Asia/Shanghai"}))
    return SimpleNamespace(admission=admission, prices=prices)


def chat_model(stale_pricing=None):
    # model_info mimics the 60s in-process cache: its config may hold an older price.
    config = {"pricing": stale_pricing} if stale_pricing else {}
    return SimpleNamespace(user_id=2, model_id=7, model_info=SimpleNamespace(id=7, config=config))


async def test_price_saved_elsewhere_applies_to_the_next_call_despite_stale_cache(chat_env):
    model = chat_model(stale_pricing=DEEPSEEK)
    chat_env.prices["value"] = {**DEEPSEEK, "output": "54"}  # saved by another process
    _, event, _ = await chat_credits.start(model)
    assert event.pricing.output_micro == 54_000_000


async def test_call_in_flight_keeps_its_start_price(chat_env):
    _, event, _ = await chat_credits.start(chat_model())
    chat_env.prices["value"] = {**DEEPSEEK, "output": "54"}
    _, later, _ = await chat_credits.start(chat_model())
    assert event.pricing.output_micro == 27_000_000
    assert later.pricing.output_micro == 54_000_000


async def test_free_model_is_admitted_unmetered(chat_env):
    chat_env.prices["value"] = dict(FREE)
    _, event, _ = await chat_credits.start(chat_model())
    assert event.pricing.free
    assert chat_env.admission.await_args.kwargs["mode"] == "unmetered"


async def test_paid_model_keeps_the_requested_mode(chat_env):
    await chat_credits.start(chat_model(), mode="unmetered")
    assert chat_env.admission.await_args.kwargs["mode"] == "unmetered"
    await chat_credits.start(chat_model())
    assert chat_env.admission.await_args.kwargs["mode"] == ""


async def test_round_probe_for_a_free_model_skips_the_allowance_check(chat_env):
    chat_env.prices["value"] = dict(FREE)
    _, event, execution = await chat_credits.start(chat_model(), mode="probe")
    assert (event, execution) == (None, None)
    chat_env.admission.assert_not_awaited()


async def test_round_probe_for_a_paid_model_still_checks_the_allowance(chat_env):
    await chat_credits.start(chat_model(), mode="probe")
    assert chat_env.admission.await_args.kwargs["mode"] == "probe"


async def test_model_without_price_is_refused_before_admission(chat_env):
    chat_env.prices["value"] = None
    with pytest.raises(DshModelPricingMissingError):
        await chat_credits.start(chat_model(stale_pricing=DEEPSEEK))
    chat_env.admission.assert_not_awaited()


# --- settlement on the shared service ---------------------------------------------------------


def running_event(pricing: PricingSnapshot) -> UsageEvent:
    return UsageEvent(
        request_id="chat-ledger",
        tenant_id=1,
        user_id=2,
        session_id="chat",
        model_id=7,
        usage_month="2026-11",
        billing_timezone="Asia/Shanghai",
        policy_version=1,
        event_version=1,
        quota_epoch=1,
        status="RUNNING",
        started_at=datetime(2026, 11, 12, tzinfo=UTC),
        pricing=pricing,
    )


def settlement_service():
    ledger = SimpleNamespace(record_usage=AsyncMock())
    now = datetime(2026, 11, 12, 0, 1, tzinfo=UTC)
    service = DshModelService(
        policy_reader=None, model_loader=None, llm_builder=None, capabilities_for=None, usage=ledger, now=lambda: now
    )
    return service, ledger


async def test_settlement_reads_exclusive_cache_back_into_input():
    service, ledger = settlement_service()
    snapshot = build_snapshot(DEEPSEEK, CreditSettingState())
    usage = DshTokenUsage(
        input_tokens=100, output_tokens=10, total_tokens=110, cache_read_tokens=80, cache_creation_tokens=40
    )
    terminal = await service.settle_usage(running_event(snapshot), usage, "SUCCEEDED")
    assert (terminal.input_tokens, terminal.total_tokens) == (220, 230)
    # miss 100 x 9 + read 80 x 0.3 + write 40 x 9 + output 10 x 27
    assert terminal.cost_micro == 900 + 24 + 360 + 270
    ledger.record_usage.assert_awaited_once()


async def test_settlement_outside_the_accounting_range_is_recorded_as_unknown():
    service, ledger = settlement_service()
    ledger.record_usage.assert_not_awaited()
    huge = PricingSnapshot(
        currency="CNY",
        credit_value_micro=1,
        input_micro=10**15,
        cache_read_micro=0,
        cache_write_micro=0,
        output_micro=0,
    )
    usage = DshTokenUsage(input_tokens=10**7, output_tokens=0, total_tokens=10**7)
    terminal = await service.settle_usage(running_event(huge), usage, "SUCCEEDED")
    assert terminal.status == "USAGE_UNKNOWN"
    assert terminal.billed_tokens is None
    assert terminal.error_code == "usage_out_of_range"


# --- the uncached read itself -----------------------------------------------------------------


def test_repository_reads_the_stored_price_of_any_tenant(tmp_path):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
    from bisheng.llm.domain.models.llm_server import LLMModel
    from bisheng.llm.domain.repositories.model_pricing_repository import ModelPricingRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'pricing.db'}")
    LLMModel.__table__.create(engine)
    with Session(engine) as session, session.begin():
        session.add(
            LLMModel(
                id=7,
                tenant_id=1,
                server_id=1,
                name="m",
                model_name="m",
                model_type="llm",
                config={"pricing": DEEPSEEK, "max_tokens": 1},
                user_id=1,
            )
        )
        session.add(
            LLMModel(
                id=8,
                tenant_id=1,
                server_id=1,
                name="n",
                model_name="n",
                model_type="llm",
                config={"max_tokens": 1},
                user_id=1,
            )
        )
    token = set_current_tenant_id(2)  # a child tenant reading a Root-shared model it was authorized for
    try:
        with Session(engine) as session:
            repo = ModelPricingRepository(session)
            assert repo.read(7) == DEEPSEEK
            assert repo.read(8) is None
            assert repo.read(9) is None
    finally:
        current_tenant_id.reset(token)
