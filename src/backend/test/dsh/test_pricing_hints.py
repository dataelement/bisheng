"""F016 credit ratio hints (3:1 against the base model) and the admin pricing endpoints."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.dsh.domain.services import pricing as service
from bisheng.dsh.domain.services.pricing import HintContext, build_snapshot, format_ratio, pricing_hint

DEEPSEEK = {"currency": "CNY", "input": "9", "cache_read": "0.3", "output": "27", "source": "CATALOG"}
GPT41 = {"currency": "USD", "input": "2", "cache_read": "0.5", "output": "8", "source": "CATALOG"}
QWEN_FLASH = {"currency": "CNY", "input": "0.2", "cache_read": "0.02", "output": "0.8", "source": "CATALOG"}
FREE = {"currency": "CNY", "input": "0", "cache_read": "0", "output": "0", "source": "DEFAULT"}
# Valid and not free, yet 3 x input + output is zero: it cannot be the ratio's denominator.
CACHE_ONLY = {"currency": "CNY", "input": "0", "cache_read": "0.5", "output": "0", "source": "MANUAL"}
# The design examples convert at 7.2 CNY per USD; the default rate is tested in test_credit_settings.
SETTING = CreditSettingState(usd_cny_rate_micro=7_200_000)


def context(base=DEEPSEEK, base_id=7):
    return HintContext(SETTING, base_id, build_snapshot(base, SETTING) if base else None)


@pytest.mark.parametrize(
    ("value", "base", "text"),
    [(54, 54, "1.00"), (100_800_000, 54_000_000, "1.87"), (1_400_000, 54_000_000, "0.03"), (1, 1_000, "<0.01")],
)
def test_format_ratio(value, base, text):
    assert format_ratio(value, base) == text


def test_ratios_follow_the_design_examples():
    ctx = context()
    assert pricing_hint(7, DEEPSEEK, ctx) == {"ratio": "1.00", "base": True, "free": False}
    assert pricing_hint(8, GPT41, ctx) == {"ratio": "1.87", "base": False, "free": False}
    assert pricing_hint(9, QWEN_FLASH, ctx) == {"ratio": "0.03", "base": False, "free": False}


def test_free_missing_and_baseless_models_show_no_ratio():
    assert pricing_hint(9, FREE, context()) == {"ratio": None, "base": False, "free": True}
    assert pricing_hint(9, None, context()) == {"ratio": None, "base": False, "free": False}
    assert pricing_hint(8, GPT41, context(base=None)) == {"ratio": None, "base": False, "free": False}


def test_a_base_without_input_or_output_price_shows_no_ratio_instead_of_dividing_by_zero():
    assert pricing_hint(8, GPT41, context(base=CACHE_ONLY, base_id=10)) == {"ratio": None, "base": False, "free": False}
    assert pricing_hint(10, CACHE_ONLY, context(base=CACHE_ONLY, base_id=10)) == {
        "ratio": None,
        "base": True,
        "free": False,
    }


def test_changing_the_base_changes_only_the_ratio():
    assert pricing_hint(8, GPT41, context(base=QWEN_FLASH, base_id=9))["ratio"] == "72.00"
    assert build_snapshot(GPT41, SETTING) == build_snapshot(GPT41, SETTING)  # billing is unaffected


@pytest.fixture
def llm(monkeypatch):
    from bisheng.dsh import runtime
    from bisheng.llm.domain.services.llm import LLMService

    models = {7: DEEPSEEK, 8: GPT41, 9: FREE, 10: CACHE_ONLY}
    offline = set()

    async def snapshot(model_id):
        if model_id not in models or model_id in offline:
            raise DshModelNotAllowedError()
        return SimpleNamespace(id=model_id, config={"pricing": models[model_id]}), SimpleNamespace()

    monkeypatch.setattr(LLMService, "get_dsh_model_snapshot", AsyncMock(side_effect=snapshot))
    monkeypatch.setattr(LLMService, "get_dsh_model_metadata_snapshot", AsyncMock(side_effect=snapshot))
    monkeypatch.setattr(LLMService, "get_dsh_model_ids", AsyncMock(return_value=[7, 8, 9]))
    monkeypatch.setattr(
        LLMService, "get_workbench_llm", AsyncMock(return_value=SimpleNamespace(chat_default_model_id="7"))
    )
    monkeypatch.setattr(runtime, "read_credit_setting", AsyncMock(return_value=SETTING))
    monkeypatch.setattr(runtime, "read_model_pricing", AsyncMock(side_effect=lambda model_id: models.get(model_id)))
    return SimpleNamespace(models=models, offline=offline, runtime=runtime)


async def test_base_defaults_to_the_daily_chat_default_model(llm):
    ctx = await service.read_hint_context()
    assert ctx.base_model_id == 7 and ctx.base == build_snapshot(DEEPSEEK, SETTING)


async def test_configured_base_wins_and_unusable_bases_hide_ratios(llm):
    llm.runtime.read_credit_setting.return_value = CreditSettingState(base_model_id=8, usd_cny_rate_micro=7_200_000)
    assert (await service.read_hint_context()).base_model_id == 8
    llm.offline.add(8)
    assert (await service.read_hint_context()).base is None  # offline or deleted
    llm.runtime.read_credit_setting.return_value = CreditSettingState(base_model_id=9, usd_cny_rate_micro=7_200_000)
    assert (await service.read_hint_context()).base is None  # free base
    llm.runtime.read_credit_setting.return_value = CreditSettingState(base_model_id=10, usd_cny_rate_micro=7_200_000)
    assert (await service.read_hint_context()).base is None  # cache-only price: no denominator
    hints = await service.workbench_pricing_hints(["7", "8", "10"])
    assert all(hint["ratio"] is None for hint in hints.values())


async def test_workbench_hints_are_keyed_by_picker_ids(llm):
    hints = await service.workbench_pricing_hints(["7", "8", "9", "not-a-number"])
    assert hints == {
        "7": {"ratio": "1.00", "base": True, "free": False},
        "8": {"ratio": "1.87", "base": False, "free": False},
        "9": {"ratio": None, "base": False, "free": True},
    }


async def test_admin_model_pricing_summary(llm):
    llm.models[10] = None
    llm.runtime.read_model_pricing.side_effect = lambda model_id: llm.models.get(model_id)
    from bisheng.llm.domain.services.llm import LLMService

    LLMService.get_dsh_model_ids.return_value = [7, 8, 10]
    rows = {row["model_id"]: row for row in await service.admin_model_pricing()}
    assert rows[8]["effective"] == {
        "currency": "CNY",
        "input": "14.4",
        "cache_read": "3.6",
        "cache_write": "14.4",
        "output": "57.6",
    }
    assert rows[8]["hint"]["ratio"] == "1.87" and not rows[8]["missing"]
    assert rows[10]["missing"] and rows[10]["pricing"] is None and rows[10]["effective"] is None


def test_pricing_hint_is_never_stored_in_the_workbench_config():
    from bisheng.api.v1.schemas import WSModel

    model = WSModel.model_validate({"id": "7", "pricing_hint": {"ratio": "1.00", "base": True, "free": False}})
    assert "pricing_hint" not in model.model_dump()


async def test_desktop_model_list_carries_hints():
    from bisheng.dsh.domain.services.model import DshModelService
    from bisheng.dsh.infrastructure.chat_adapter import ChatCapabilities

    async def load(model_id):
        return SimpleNamespace(
            id=model_id, name="m", model_name="m", create_time=datetime(2026, 11, 12), config={"pricing": GPT41}
        ), SimpleNamespace(name="OpenAI", type="openai")

    service_ = DshModelService(
        policy_reader=AsyncMock(return_value=SimpleNamespace(allowed_model_ids=[8])),
        model_loader=load,
        llm_builder=None,
        capabilities_for=lambda *args: ChatCapabilities(),
        usage=None,
        now=datetime.now,
        hint_context_reader=AsyncMock(return_value=context()),
    )
    data = (await service_.list_models(SimpleNamespace(user_id="2", tenant_id="1", session_id="s")))["data"]
    assert data[0]["pricing_hint"] == {"ratio": "1.87", "base": False, "free": False}


# --- endpoints ---------------------------------------------------------------------------------


@pytest.fixture
async def client(monkeypatch):
    from bisheng.dsh.api.endpoints import credit_pricing as endpoints

    app = FastAPI()
    app.include_router(endpoints.router, prefix="/api/v1")
    management = SimpleNamespace(authorize=AsyncMock(return_value=(None, 2)))
    app.dependency_overrides[endpoints.admin_user] = lambda: SimpleNamespace(user_id=90)
    app.dependency_overrides[endpoints.get_management] = lambda: management
    view = {"version": 1, "currency": "CNY", "credit_value": "0.01", "usd_cny_rate": "7.2", "base_model_id": None}
    monkeypatch.setattr(endpoints, "credit_settings_view", AsyncMock(return_value=view))
    monkeypatch.setattr(endpoints, "save_credit_settings", AsyncMock(return_value=view))
    monkeypatch.setattr(endpoints, "admin_model_pricing", AsyncMock(return_value=[]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield SimpleNamespace(http=http, endpoints=endpoints, management=management)


async def test_endpoints_authorize_and_route(client):
    base = "/api/v1/dsh/admin"
    assert (await client.http.get(base + "/credit-settings")).json()["data"]["credit_value"] == "0.01"
    assert (await client.http.get(base + "/model-pricing")).json()["data"] == []
    body = {"version": 1, "currency": "USD", "credit_value": "0.001389", "usd_cny_rate": "7.2", "base_model_id": 7}
    assert (await client.http.put(base + "/credit-settings", json=body)).status_code == 200
    actor, value = client.endpoints.save_credit_settings.await_args.args
    assert actor == 90 and value.credit_value_micro == 1_389
    assert client.management.authorize.await_count == 3


async def test_settings_endpoint_rejects_unknown_fields(client):
    body = {"version": 1, "currency": "CNY", "credit_value": "0.01", "usd_cny_rate": "7.2", "credit_multiplier": "1"}
    response = await client.http.put("/api/v1/dsh/admin/credit-settings", json=body)
    assert response.status_code == 422
    client.endpoints.save_credit_settings.assert_not_awaited()


def test_routes_avoid_the_word_config():
    from bisheng.dsh.api.endpoints import credit_pricing

    assert all("config" not in route.path.lower() for route in credit_pricing.router.routes)
