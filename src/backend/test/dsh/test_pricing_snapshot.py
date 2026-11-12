"""F016 price snapshots and per-call pricing in integer micro-units."""

import json

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshModelPricingMissingError
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.schemas.pricing import CreditSettingState, PricingSnapshot, price_usage
from bisheng.dsh.domain.services.pricing import build_snapshot

DEEPSEEK = {
    "currency": "CNY",
    "input": "9",
    "cache_read": "0.3",
    "cache_write": None,
    "output": "27",
    "source": "CATALOG",
}
GPT41 = {"currency": "USD", "input": "2", "cache_read": "0.5", "cache_write": None, "output": "8", "source": "CATALOG"}
FREE = {"currency": "CNY", "input": "0", "cache_read": "0", "cache_write": None, "output": "0", "source": "DEFAULT"}
CNY = CreditSettingState()
USD = CreditSettingState(currency="USD", credit_value_micro=1_389)


def usage(input_tokens, output_tokens, read=None, write=None):
    return DshTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=read,
        cache_creation_tokens=write,
    )


def test_ac01_deepseek_example_is_exact():
    snapshot = build_snapshot(DEEPSEEK, CNY)
    assert snapshot == PricingSnapshot(
        currency="CNY",
        credit_value_micro=10_000,
        input_micro=9_000_000,
        cache_read_micro=300_000,
        cache_write_micro=9_000_000,
        output_micro=27_000_000,
    )
    result = price_usage(usage(30_000, 1_000, read=24_000), snapshot)
    # 6,000 x 9 + 24,000 x 0.3 + 1,000 x 27 = 88,200 micro-yuan = 8.82 credits at 0.01 yuan
    assert (result.cost_micro, result.billed) == (88_200, 8_820_000)


def test_usd_model_converts_to_cny_and_records_rate():
    snapshot = build_snapshot(GPT41, CNY)
    assert (snapshot.input_micro, snapshot.cache_read_micro, snapshot.output_micro) == (
        14_400_000,
        3_600_000,
        57_600_000,
    )
    assert snapshot.usd_cny_rate_micro == 7_200_000
    result = price_usage(usage(30_000, 1_000, read=24_000), snapshot)
    assert (result.cost_micro, result.billed) == (230_400, 23_040_000)


def test_cny_model_converts_to_usd_rounding_up():
    snapshot = build_snapshot(DEEPSEEK, USD)
    assert snapshot.currency == "USD" and snapshot.credit_value_micro == 1_389
    # 9 / 7.2 = 1.25 exactly; 0.3 / 7.2 = 0.041666... -> 0.041667
    assert (snapshot.input_micro, snapshot.cache_read_micro, snapshot.output_micro) == (1_250_000, 41_667, 3_750_000)
    assert snapshot.usd_cny_rate_micro == 7_200_000


def test_same_currency_omits_rate_from_serialized_snapshot():
    data = json.loads(build_snapshot(DEEPSEEK, CNY).model_dump_json())
    assert "usd_cny_rate_micro" not in data
    assert set(data) == {
        "currency",
        "credit_value_micro",
        "input_micro",
        "cache_read_micro",
        "cache_write_micro",
        "output_micro",
    }
    assert json.loads(build_snapshot(GPT41, CNY).model_dump_json())["usd_cny_rate_micro"] == 7_200_000


def test_cache_write_uses_its_own_price_or_falls_back_to_input():
    explicit = build_snapshot({**DEEPSEEK, "cache_write": "11.25"}, CNY)
    assert explicit.cache_write_micro == 11_250_000
    result = price_usage(usage(10_000, 0, read=2_000, write=3_000), explicit)
    # miss 5,000 x 9 + read 2,000 x 0.3 + write 3,000 x 11.25
    assert result.cost_micro == 45_000 + 600 + 33_750


def test_every_partial_microcredit_rounds_up():
    tiny = build_snapshot({**DEEPSEEK, "input": "0.000001", "cache_read": "0", "output": "0"}, CNY)
    result = price_usage(usage(1, 0), tiny)
    assert (result.cost_micro, result.billed) == (1, 1)
    result = price_usage(usage(0, 1), build_snapshot(DEEPSEEK, CNY))
    assert (result.cost_micro, result.billed) == (27, 2_700)


def test_missing_cache_detail_bills_all_input_as_miss():
    result = price_usage(usage(1_000, 0), build_snapshot(DEEPSEEK, CNY))
    assert result.cost_micro == 9_000


def test_cache_exceeding_input_is_treated_as_exclusive_input():
    snapshot = build_snapshot(DEEPSEEK, CNY)
    result = price_usage(usage(1_000, 0, read=800, write=400), snapshot)
    # Input cannot include 1,200 cached tokens, so all 1,000 reported input tokens are misses.
    assert result.cost_micro == 9_000 + 240 + 3_600


def test_free_snapshot_bills_nothing():
    snapshot = build_snapshot(FREE, CNY)
    assert snapshot.free
    assert not build_snapshot(DEEPSEEK, CNY).free
    result = price_usage(usage(50_000, 5_000, read=10_000), snapshot)
    assert (result.cost_micro, result.billed) == (0, 0)


def test_unknown_usage_has_no_price():
    assert price_usage(DshTokenUsage(), build_snapshot(DEEPSEEK, CNY)) is None


@pytest.mark.parametrize("config", [None, {}, {**DEEPSEEK, "input": "-1"}, {**DEEPSEEK, "source": "GUESS"}, "9"])
def test_missing_or_corrupt_pricing_fails_closed(config):
    with pytest.raises(DshModelPricingMissingError):
        build_snapshot(config, CNY)


def test_snapshot_contract_is_strict():
    with pytest.raises(ValidationError):
        PricingSnapshot(
            currency="CNY",
            credit_value_micro=0,
            input_micro=1,
            cache_read_micro=1,
            cache_write_micro=1,
            output_micro=1,
        )
    with pytest.raises(ValidationError):
        PricingSnapshot(
            currency="CNY",
            credit_value_micro=1,
            input_micro=-1,
            cache_read_micro=1,
            cache_write_micro=1,
            output_micro=1,
        )
    with pytest.raises(ValidationError):
        PricingSnapshot.model_validate(
            {
                "currency": "CNY",
                "credit_value_micro": 1,
                "input_micro": 1,
                "cache_read_micro": 1,
                "cache_write_micro": 1,
                "output_micro": 1,
                "source": "CATALOG",
            }
        )


def test_snapshot_round_trips_through_json():
    snapshot = build_snapshot(GPT41, CNY)
    assert PricingSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert PricingSnapshot.model_validate(json.loads(snapshot.model_dump_json())) == snapshot


def test_missing_pricing_error_is_registered():
    from bisheng.common.errcode.dsh import ERROR_BY_CLIENT_CODE

    assert DshModelPricingMissingError.Code == 26176
    assert ERROR_BY_CLIENT_CODE["model_pricing_missing"] is DshModelPricingMissingError
