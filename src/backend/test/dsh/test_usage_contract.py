"""F015 token-usage contract: every source maps to input-including-cache (design §4.4)."""

import pytest
from anthropic.types import Usage
from anthropic.types.cache_creation import CacheCreation
from langchain_anthropic.chat_models import _create_usage_metadata
from langchain_core.messages import AIMessage, AIMessageChunk

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.infrastructure import usage_contract
from bisheng.dsh.infrastructure.chat_adapter import accumulate_usage, normalize_usage
from bisheng.dsh.infrastructure.responses_adapter import normalize_responses_usage


def usage(input_tokens, output_tokens, read=None, write=None):
    return DshTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=read,
        cache_creation_tokens=write,
    )


def test_openai_style_usage_metadata_is_used_as_is():
    message = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": 30_000,
            "output_tokens": 1_000,
            "total_tokens": 31_000,
            "input_token_details": {"cache_read": 24_000},
        },
    )
    assert normalize_usage(message) == usage(30_000, 1_000, read=24_000)


def test_anthropic_bucketed_cache_writes_are_summed():
    # Real langchain-anthropic 1.4.7 output: the generic cache_creation is 0 when buckets are reported.
    metadata = _create_usage_metadata(
        Usage(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=300,
            cache_creation=CacheCreation(ephemeral_5m_input_tokens=200, ephemeral_1h_input_tokens=100),
        )
    )
    assert metadata["input_token_details"]["cache_creation"] == 0
    assert normalize_usage(AIMessage(content="", usage_metadata=metadata)) == usage(900, 20, read=500, write=300)


def test_anthropic_generic_cache_writes_are_not_double_counted():
    metadata = _create_usage_metadata(
        Usage(input_tokens=100, output_tokens=20, cache_read_input_tokens=500, cache_creation_input_tokens=300)
    )
    assert normalize_usage(AIMessage(content="", usage_metadata=metadata)) == usage(900, 20, read=500, write=300)


def test_qwen_raw_usage_reads_explicit_cache_creation():
    message = AIMessage(
        content="",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 12_000,
                "completion_tokens": 800,
                "total_tokens": 12_800,
                "prompt_tokens_details": {"cached_tokens": 8_000, "cache_creation_input_tokens": 1_000},
            }
        },
    )
    assert normalize_usage(message) == usage(12_000, 800, read=8_000, write=1_000)


def test_qwen_raw_usage_without_hits_reports_zero_reads():
    message = AIMessage(
        content="",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 1_200,
                "completion_tokens": 30,
                "total_tokens": 1_230,
                "prompt_tokens_details": {"cached_tokens": 0},
            }
        },
    )
    assert normalize_usage(message) == usage(1_200, 30, read=0)


def test_deepseek_raw_hit_tokens():
    message = AIMessage(
        content="",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 5_000,
                "completion_tokens": 200,
                "total_tokens": 5_200,
                "prompt_cache_hit_tokens": 4_096,
                "prompt_cache_miss_tokens": 904,
            }
        },
    )
    assert normalize_usage(message) == usage(5_000, 200, read=4_096)


def test_openai_raw_usage_without_details_has_no_cache_fields():
    message = AIMessage(
        content="",
        response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
    )
    assert normalize_usage(message) == usage(10, 2)


def test_responses_api_usage():
    raw = {
        "input_tokens": 9_000,
        "output_tokens": 300,
        "total_tokens": 9_300,
        "input_tokens_details": {"cached_tokens": 6_000},
        "output_tokens_details": {"reasoning_tokens": 120},
    }
    assert normalize_responses_usage(raw) == usage(9_000, 300, read=6_000)


def test_streaming_chunks_accumulate_to_one_inclusive_total():
    start = AIMessageChunk(
        content="",
        usage_metadata={
            "input_tokens": 900,
            "output_tokens": 1,
            "total_tokens": 901,
            "input_token_details": {"cache_read": 500, "cache_creation": 300},
        },
    )
    delta = AIMessageChunk(content="", usage_metadata={"input_tokens": 0, "output_tokens": 19, "total_tokens": 19})
    total = accumulate_usage(accumulate_usage(DshTokenUsage(), start), delta)
    assert total == usage(900, 20, read=500, write=300)


def test_consistent_usage_passes_through_unchanged(monkeypatch):
    emitted = []
    monkeypatch.setattr(usage_contract, "emit_metric", lambda *args, **kwargs: emitted.append(kwargs))
    value = usage(1_000, 10, read=600, write=400)
    assert usage_contract.enforce_inclusive(value, model_id=4, request_id="r") is value
    assert usage_contract.enforce_inclusive(DshTokenUsage(), model_id=4, request_id="r") == DshTokenUsage()
    assert emitted == []


def test_cache_exceeding_input_is_read_as_exclusive_and_reported(monkeypatch):
    emitted = []
    monkeypatch.setattr(usage_contract, "emit_metric", lambda domain, **kwargs: emitted.append((domain, kwargs)))
    corrected = usage_contract.enforce_inclusive(usage(100, 10, read=80, write=40), model_id=4, request_id="r")
    assert corrected == usage(220, 10, read=80, write=40)
    assert emitted == [("dsh_usage_contract", {"model_id": 4, "request_id": "r", "corrected": True})]


@pytest.mark.parametrize("read,write", [(100, 0), (0, 100), (60, 40)])
def test_cache_equal_to_input_is_valid(read, write):
    value = usage(100, 0, read=read, write=write)
    assert usage_contract.enforce_inclusive(value, model_id=4, request_id="r") is value
