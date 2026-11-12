"""F015 model price structure stored in llm_model.config["pricing"]."""

import pytest
from pydantic import ValidationError

from bisheng.llm.domain.pricing import ModelPricing, price_to_micro


def pricing(**changes):
    values = {
        "currency": "CNY",
        "input": "9",
        "cache_read": "0.3",
        "cache_write": None,
        "output": "27",
        "source": "CATALOG",
        "catalog_key": "deepseek/deepseek-v4-pro",
        "catalog_version": "2026-11-10",
    }
    values.update(changes)
    return ModelPricing.model_validate(values)


@pytest.mark.parametrize("value", ["0", "9", "0.3", "999999.999999", "12.5", "0.000001"])
def test_accepts_decimal_strings_up_to_six_places(value):
    assert pricing(input=value).input == value


@pytest.mark.parametrize("value", ["-1", "1.0000001", "1000000", "01", "1.", ".5", "1e3", " 1", "", "abc"])
def test_rejects_malformed_or_out_of_range_prices(value):
    with pytest.raises(ValidationError):
        pricing(input=value)


def test_rejects_numbers_and_unknown_fields():
    with pytest.raises(ValidationError):
        pricing(input=9)
    with pytest.raises(ValidationError):
        pricing(off_peak={"input": "4.5"})


def test_currency_and_source_are_closed_sets():
    with pytest.raises(ValidationError):
        pricing(currency="EUR")
    with pytest.raises(ValidationError):
        pricing(source="GUESS")


def test_revision_defaults_to_one_and_must_be_positive():
    assert pricing().revision == 1
    with pytest.raises(ValidationError):
        pricing(revision=0)


def test_cache_write_falls_back_to_input_price():
    assert pricing().effective_cache_write == "9"
    assert pricing(cache_write="11.25").effective_cache_write == "11.25"


def test_free_only_when_every_price_is_zero():
    assert pricing(input="0", cache_read="0", output="0", source="DEFAULT").free
    assert not pricing(input="0", cache_read="0", output="0.000001").free
    assert not pricing(input="0", cache_read="0", cache_write="1", output="0").free


@pytest.mark.parametrize(
    ("value", "micro"),
    [("0", 0), ("9", 9_000_000), ("0.3", 300_000), ("0.000001", 1), ("999999.999999", 999_999_999_999)],
)
def test_price_to_micro_is_exact(value, micro):
    assert price_to_micro(value) == micro
