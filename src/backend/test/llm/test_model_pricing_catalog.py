"""F016 built-in price catalog: bundled data validity and exact matching."""

import copy

import pytest
from pydantic import ValidationError

from bisheng.llm.domain.pricing import ModelPricing
from bisheng.llm.domain.pricing.catalog import PriceCatalog, catalog_pricing, load_catalog, match


def test_bundled_catalog_is_valid_and_prices_convert():
    catalog = load_catalog()
    assert catalog.version == "2026-11-10"
    assert len(catalog.entries) >= 30
    for entry in catalog.entries:
        pricing = catalog_pricing(entry)
        assert isinstance(pricing, ModelPricing)
        assert (pricing.source, pricing.catalog_key, pricing.catalog_version) == ("CATALOG", entry.key, "2026-11-10")
        assert entry.source_url.startswith("https://")


def test_exact_native_match():
    found = match("qwen", "qwen-max")
    assert found.entry.key == "qwen/qwen-max"
    assert not found.via_name
    assert (found.entry.input, found.entry.cache_read, found.entry.cache_write, found.entry.output) == (
        "12",
        "1.2",
        "15",
        "36",
    )


def test_case_and_surrounding_spaces_are_ignored():
    assert match("qwen", "  QWEN-Max ").entry.key == "qwen/qwen-max"


def test_openai_compatible_matches_by_name_and_asks_for_review():
    found = match("openai_compatible", "gpt-4.1")
    assert found.entry.key == "openai/gpt-4.1"
    assert found.via_name


def test_explicit_dated_alias_matches():
    assert match("anthropic", "claude-haiku-4-5-20251001").entry.key == "anthropic/claude-haiku-4-5"


@pytest.mark.parametrize(
    ("server_type", "model_name"),
    [
        ("openai", "gpt-4.1-2025-04-14"),  # dated snapshots are never stripped to the base price
        ("anthropic", "claude-sonnet-4-5-20990101"),
        ("qwen", "gpt-4.1"),  # another vendor's model under a native provider
        ("zhipu", "glm-4.7"),  # domestic Zhipu may price differently in CNY; only the intl entry exists
        ("minimax", "minimax-m3"),
        ("vllm", "qwen-max"),  # self-hosted provider types never match
        ("ollama", "deepseek-v4-pro"),
        ("volcengine", "ep-20261110-abcde"),  # Ark endpoint IDs cannot be matched
        ("openai", ""),
    ],
)
def test_no_match_falls_back_to_default(server_type, model_name):
    assert match(server_type, model_name) is None


def test_free_catalog_entry():
    assert catalog_pricing(match("openai_compatible", "glm-4.7-flash").entry).free


def _raw():
    return copy.deepcopy(load_catalog().model_dump())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["entries"].append(copy.deepcopy(d["entries"][0])),  # duplicate key
        lambda d: d["entries"][1]["aliases"].append(d["entries"][0]["aliases"][0]),  # same provider + alias
        lambda d: d["entries"][0].update(input="-1"),
        lambda d: d["entries"][0].update(provider_types=["not-a-provider"]),
        lambda d: d["entries"][0].update(aliases=["DeepSeek-V4-Pro"]),  # aliases are stored normalized
        lambda d: d["entries"][0].update(off_peak={"input": "4.5"}),  # unused future fields are rejected
        lambda d: d["entries"][0].update(source_url="http://insecure.example"),
        lambda d: d["entries"][0].update(aliases=[]),
    ],
)
def test_catalog_validation_rejects_bad_data(mutate):
    raw = _raw()
    mutate(raw)
    with pytest.raises(ValidationError):
        PriceCatalog.model_validate(raw)
