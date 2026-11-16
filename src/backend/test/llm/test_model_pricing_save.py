"""F016 prices decided when an LLM model is saved: fill, keep, judge source, compare-and-swap."""

import pytest

from bisheng.common.errcode.llm import ModelPricingConflictError, ModelPricingInvalidError
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.pricing.service import apply_pricing_on_save, resolve_model_pricing

QWEN_MAX = {"currency": "CNY", "input": "2.4", "cache_read": "0.48", "cache_write": "3", "output": "9.6"}


def stored(**changes):
    value = {
        **QWEN_MAX,
        "source": "CATALOG",
        "catalog_key": "qwen/qwen-max",
        "catalog_version": "2026-11-16",
        "ref_key": None,
        "revision": 3,
    }
    value.update(changes)
    return value


def test_new_model_without_price_takes_the_catalog_price():
    result = resolve_model_pricing("qwen", "qwen-max", incoming=None, existing=None)
    assert result == stored(revision=1)


def test_new_model_without_catalog_match_defaults_to_free():
    result = resolve_model_pricing("vllm", "my-qwen", incoming=None, existing=None)
    assert result["source"] == "DEFAULT"
    assert (result["input"], result["cache_read"], result["output"], result["revision"]) == ("0", "0", "0", 1)
    assert result["catalog_key"] is None


def test_saving_without_a_price_keeps_the_stored_one():
    current = stored(input="6", source="MANUAL")
    assert resolve_model_pricing("qwen", "qwen-max", incoming=None, existing=current) == current


def test_legacy_model_without_a_price_is_filled_on_its_next_save():
    assert resolve_model_pricing("qwen", "qwen-max", incoming=None, existing=None)["source"] == "CATALOG"


def test_client_supplied_source_is_ignored_and_judged_by_the_server():
    result = resolve_model_pricing(
        "qwen", "qwen-max", incoming={**QWEN_MAX, "input": "6", "source": "CATALOG", "revision": 3}, existing=stored()
    )
    assert (result["source"], result["catalog_key"], result["input"], result["revision"]) == (
        "MANUAL",
        "qwen/qwen-max",
        "6",
        4,
    )


def test_restoring_the_catalog_price_marks_it_catalog_again():
    result = resolve_model_pricing(
        "qwen",
        "qwen-max",
        incoming={**QWEN_MAX, "input": "2.400000", "revision": 4},
        existing=stored(input="6", source="MANUAL", revision=4),
    )
    assert (result["source"], result["revision"]) == ("CATALOG", 5)


def test_unmatched_model_with_explicit_price_is_manual_and_zero_is_default():
    priced = resolve_model_pricing("vllm", "my-qwen", incoming={**QWEN_MAX, "revision": 1}, existing=None)
    assert priced["source"] == "MANUAL"
    zero = {"currency": "CNY", "input": "0", "cache_read": "0", "output": "0"}
    assert resolve_model_pricing("vllm", "my-qwen", incoming=zero, existing=None)["source"] == "DEFAULT"


def test_stale_revision_conflicts():
    with pytest.raises(ModelPricingConflictError):
        resolve_model_pricing("qwen", "qwen-max", incoming={**QWEN_MAX, "input": "6", "revision": 2}, existing=stored())
    with pytest.raises(ModelPricingConflictError):
        resolve_model_pricing("qwen", "qwen-max", incoming={**QWEN_MAX, "input": "6"}, existing=stored())


def test_resending_the_same_price_does_not_bump_the_revision():
    current = stored()
    assert resolve_model_pricing("qwen", "qwen-max", incoming={**QWEN_MAX, "revision": 3}, existing=current) == current


def test_new_model_ignores_any_client_revision():
    result = resolve_model_pricing("vllm", "my-qwen", incoming={**QWEN_MAX, "revision": 9}, existing=None)
    assert result["revision"] == 1


@pytest.mark.parametrize(
    "incoming",
    [
        {**QWEN_MAX, "input": "-1"},
        {**QWEN_MAX, "input": 12},
        {**QWEN_MAX, "currency": "EUR"},
        {key: value for key, value in QWEN_MAX.items() if key != "output"},
        "12",
    ],
)
def test_invalid_input_is_rejected(incoming):
    with pytest.raises(ModelPricingInvalidError):
        resolve_model_pricing("qwen", "qwen-max", incoming=incoming, existing=None)


def test_corrupt_stored_price_is_treated_as_missing():
    result = resolve_model_pricing("qwen", "qwen-max", incoming=None, existing={"input": "oops"})
    assert result["source"] == "CATALOG" and result["revision"] == 1


def model(name, model_type="llm", config=None, model_id=None):
    return LLMModel(id=model_id, server_id=1, name=name, model_name=name, model_type=model_type, config=config)


def test_apply_on_save_only_touches_llm_models_and_keeps_other_config():
    new_llm = model("qwen-max", config={"max_tokens": 8192})
    edited = model("qwen-plus", config={"user_kwargs": {"x": 1}}, model_id=5)
    embedding = model("text-embedding-v4", model_type="embedding", config={"dims": 1024})
    old = {5: model("qwen-plus", config={"pricing": stored(input="3", source="MANUAL"), "user_kwargs": {}}, model_id=5)}
    apply_pricing_on_save("qwen", [new_llm, edited, embedding], old)
    assert new_llm.config["max_tokens"] == 8192 and new_llm.config["pricing"]["catalog_key"] == "qwen/qwen-max"
    assert edited.config["user_kwargs"] == {"x": 1} and edited.config["pricing"]["input"] == "3"
    assert embedding.config == {"dims": 1024}


def test_apply_on_save_handles_missing_config():
    fresh = model("qwen-max", config=None)
    apply_pricing_on_save("qwen", [fresh], {})
    assert fresh.config["pricing"]["source"] == "CATALOG"


def test_token_config_upgrade_preserves_the_price():
    from bisheng.llm.domain.services.model_token_config_upgrade import transform_token_config

    config = {"max_tokens": 4096, "user_kwargs": "{}", "pricing": stored()}
    assert transform_token_config(config, "openai")["pricing"] == stored()
