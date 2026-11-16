"""F016 built-in price catalog: bundled data validity, exact matching and gateway prefixes."""

import copy

import pytest
from pydantic import ValidationError

from bisheng.llm.domain.pricing import ModelPricing
from bisheng.llm.domain.pricing.catalog import PriceCatalog, catalog_pricing, load_catalog, match


def test_bundled_catalog_is_valid_and_prices_convert():
    catalog = load_catalog()
    assert catalog.version == "2026-11-16"
    assert len(catalog.entries) >= 80
    for entry in catalog.entries:
        pricing = catalog_pricing(entry)
        assert isinstance(pricing, ModelPricing)
        assert (pricing.source, pricing.catalog_key, pricing.catalog_version) == ("CATALOG", entry.key, "2026-11-16")
        assert entry.source_url.startswith("https://")


def test_every_entry_can_be_picked_for_a_gateway_and_vendors_stay_grouped():
    entries = load_catalog().entries
    assert all("openai_compatible" in entry.provider_types for entry in entries)
    # The model picker groups rows by vendor in catalog order, so a vendor's entries are contiguous.
    order = [entry.vendor for entry in entries]
    vendors = list(dict.fromkeys(order))
    assert order == sorted(order, key=vendors.index)
    assert len(vendors) >= 13


def test_exact_native_match():
    found = match("qwen", "qwen-max")
    assert found.entry.key == "qwen/qwen-max"
    assert not found.via_name
    assert (found.entry.input, found.entry.cache_read, found.entry.cache_write, found.entry.output) == (
        "2.4",
        "0.48",
        "3",
        "9.6",
    )


def test_domestic_vendor_types_match_their_cny_prices():
    assert match("zhipu", "glm-5.3").entry.currency == "CNY"
    assert match("moonshot", "kimi-k3.1-pro").entry.key == "moonshot/kimi-k3.1-pro"
    assert match("tencent", "hy4").entry.key == "tencent/hy4"
    assert not match("qianfan", "ernie-5.1").via_name


def test_case_and_surrounding_spaces_are_ignored():
    assert match("qwen", "  QWEN-Max ").entry.key == "qwen/qwen-max"


def test_openai_compatible_matches_by_name_and_asks_for_review():
    found = match("openai_compatible", "gpt-4.1")
    assert found.entry.key == "openai/gpt-4.1"
    assert found.via_name


def test_explicit_dated_alias_matches():
    assert match("anthropic", "claude-haiku-4-5-20251001").entry.key == "anthropic/claude-haiku-4-5"
    # Ark model IDs are dashed and dated.
    found = match("volcengine", "doubao-seed-2-1-pro-260915")
    assert found.entry.key == "volcengine/doubao-seed-2.1-pro" and not found.via_name


@pytest.mark.parametrize(
    ("server_type", "model_name", "key"),
    [
        ("openai_compatible", "openai/gpt-5.5", "openai/gpt-5.5"),
        ("openai_compatible", "deepseek-ai/DeepSeek-V4-Pro", "deepseek/deepseek-v4-pro"),
        ("openai_compatible", "anthropic/claude-opus-4.5", "anthropic/claude-opus-4-5"),
        ("deepseek", "deepseek-ai/deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
        ("silicon", "Pro/deepseek-ai/DeepSeek-V4-Pro", "deepseek/deepseek-v4-pro"),
    ],
)
def test_gateway_vendor_prefix_is_dropped_and_asks_for_review(server_type, model_name, key):
    found = match(server_type, model_name)
    assert found.entry.key == key
    assert found.via_name


@pytest.mark.parametrize(
    ("server_type", "model_name"),
    [
        ("openai", "gpt-4.1-2025-04-14"),  # dated snapshots are never stripped to the base price
        ("anthropic", "claude-sonnet-4-5-20990101"),
        ("deepseek", "gpt-4.1"),  # a single-vendor API never serves another vendor's model
        ("moonshot", "deepseek-v4-pro"),
        ("anthropic", "openai/gpt-5.5"),
        ("openai_compatible", "openai/gpt-4.1-2025-04-14"),  # a dropped prefix never strips the date
        ("openai_compatible", "openai/"),
        ("vllm", "qwen-max"),  # self-hosted provider types never match
        ("ollama", "deepseek-v4-pro"),
        ("volcengine", "ep-20261110-abcde"),  # Ark endpoint IDs cannot be matched
        ("openai", ""),
    ],
)
def test_no_match_falls_back_to_default(server_type, model_name):
    assert match(server_type, model_name) is None


@pytest.mark.parametrize(
    ("server_type", "model_name", "key"),
    [
        ("qwen", "deepseek-v4-pro", "deepseek/deepseek-v4-pro"),  # 百炼 resells DeepSeek
        ("volcengine", "kimi-k3", "moonshot/kimi-k3"),
        ("qianfan", "qwen3.7-plus", "qwen/qwen3.7-plus"),
        ("tencent", "glm-5.3", "zhipu/glm-5.3"),
    ],
)
def test_multi_vendor_platforms_match_other_vendors_at_list_price_for_review(server_type, model_name, key):
    found = match(server_type, model_name)
    assert found.entry.key == key
    assert found.via_name


def test_multi_vendor_platform_own_models_stay_exact():
    assert not match("qwen", "qwen-max").via_name
    assert not match("volcengine", "doubao-seed-2.1-pro").via_name


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
