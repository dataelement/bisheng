"""Qwen embedding configuration and real SDK requests with offline transports."""

import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import numpy as np
import openai
import pytest
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.llm.domain import utils as model_utils
from bisheng.llm.domain.llm import embedding as embedding_module
from bisheng.llm.domain.llm.embedding import BishengEmbedding, _get_openai_params, _get_qwen_params
from bisheng.llm.domain.models import LLMModel, LLMServer

BASE_URL = "https://gateway.example.test/custom/compatible-mode/v1"
MODEL_BATCHES = [
    ("text-embedding-v1", 25),
    ("text-embedding-v2", 25),
    ("text-embedding-v3", 10),
    ("text-embedding-v4", 10),
    ("qwen3.7-text-embedding", 20),
    ("qwen3.7-text-embedding-flash", 20),
    ("gateway-embedding-alias", 10),
    ("text-embedding-v4-unrecognized-suffix", 10),
]


@pytest.mark.parametrize(
    "config,expected_url",
    [
        ({"openai_api_base": BASE_URL + "///", "base_url": "https://ignored.test/v1"}, BASE_URL),
        ({"base_url": BASE_URL + "/"}, BASE_URL),
        ({"openai_api_base": None, "base_url": BASE_URL}, BASE_URL),
        ({"openai_api_base": "", "base_url": BASE_URL}, BASE_URL),
        ({}, "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ({"openai_api_base": "", "base_url": None}, "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ({"openai_api_base": None, "base_url": ""}, "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        (None, "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ],
)
def test_base_url_priority_and_empty_values(config, expected_url):
    """AC-QE-03, AC-QE-04: provider URL precedence and missing-value handling."""
    params = _get_qwen_params({"model": "text-embedding-v4"}, config, {})
    assert params["base_url"] == expected_url


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("legacy_key", [False, True])
def test_provider_fields_win_and_advanced_config_is_not_mutated(as_json, legacy_key):
    """AC-QE-05, AC-QE-06: provider identity wins without changing stored config."""
    advanced = {
        "model": "ignored-model",
        "api_key": "ignored-key",
        "openai_api_key": "ignored-alias-key",
        "base_url": "https://ignored.test/v1",
        "openai_api_base": "https://ignored-alias.test/v1",
        "dimensions": 256,
        "request_timeout": 7,
        "max_retries": 2,
        "chunk_size": 3,
        "model_kwargs": {"extra_body": {"custom_option": True}},
    }
    model_config = {"user_kwargs": json.dumps(advanced) if as_json else advanced}
    server_config = {"openai_api_base": BASE_URL, "api_key" if legacy_key else "openai_api_key": "provider-key"}
    defaults = {"model": "text-embedding-v4"}
    before = deepcopy((defaults, server_config, model_config))

    result = _get_qwen_params(defaults, server_config, model_config)

    assert (defaults, server_config, model_config) == before
    assert result["model"] == "text-embedding-v4"
    assert result["api_key"] == "provider-key"
    assert result["base_url"] == BASE_URL
    assert not {"dashscope_api_key", "openai_api_key", "openai_api_base"} & result.keys()
    assert result["dimensions"] == 256
    assert result["request_timeout"] == 7
    assert result["max_retries"] == 2
    assert result["chunk_size"] == 3
    assert result["check_embedding_ctx_length"] is False
    assert result["model_kwargs"]["encoding_format"] == "float"
    result["model_kwargs"]["extra_body"]["custom_option"] = False
    assert (defaults, server_config, model_config) == before


def test_primary_api_key_wins_and_missing_key_keeps_existing_placeholder():
    defaults = {"model": "text-embedding-v4"}
    assert _get_qwen_params(defaults, {"openai_api_key": "primary", "api_key": "legacy"}, {})["api_key"] == "primary"
    assert _get_qwen_params(defaults, {}, {})["api_key"] == "empty"


@pytest.mark.parametrize("proxy", [" http://proxy.example.test:8080 ", "admin", "", None])
def test_proxy_uses_existing_validation(proxy):
    params = _get_qwen_params({"model": "text-embedding-v4"}, {"openai_proxy": proxy}, {})
    if proxy and proxy.startswith(" "):
        assert params["openai_proxy"] == proxy.strip()
    else:
        assert "openai_proxy" not in params


@pytest.mark.parametrize("model,batch_size", MODEL_BATCHES)
def test_default_batch_size_depends_on_exact_model_name(model, batch_size):
    """AC-QE-07, AC-QE-14: exact model names select limits; aliases default to ten."""
    assert _get_qwen_params({"model": model}, {}, {})["chunk_size"] == batch_size


@pytest.mark.parametrize("chunk_size", [True, False, "5", None, 0, -1, 1.5])
@pytest.mark.parametrize("model", ["text-embedding-v4", "gateway-embedding-alias"])
def test_invalid_batch_sizes_fail_before_sdk_construction(model, chunk_size):
    """AC-QE-13, AC-QE-14: invalid values never reach a provider request."""
    with pytest.raises(ValueError, match=r"chunk_size.*positive integer"):
        _get_qwen_params({"model": model}, {}, {"user_kwargs": {"chunk_size": chunk_size}})


@pytest.mark.parametrize("model,batch_size", MODEL_BATCHES[:6])
def test_known_models_reject_batches_above_limit(model, batch_size):
    with pytest.raises(ValueError, match=f"{model!r} must not exceed {batch_size}"):
        _get_qwen_params(
            {"model": model}, {"openai_api_base": BASE_URL}, {"user_kwargs": {"chunk_size": batch_size + 1}}
        )


@pytest.mark.parametrize(
    "advanced",
    [{"encoding_format": "base64"}, {"model_kwargs": {"encoding_format": "base64"}}],
)
async def test_explicit_encoding_format_is_preserved(advanced):
    params = _get_qwen_params({"model": "text-embedding-v4"}, {}, {"user_kwargs": advanced})
    with httpx.Client() as sync_http:
        async with httpx.AsyncClient() as async_http:
            client = OpenAIEmbeddings(**params, http_client=sync_http, http_async_client=async_http)
            assert client._invocation_params["encoding_format"] == "base64"


def test_client_mapping_and_other_openai_provider_defaults():
    """AC-QE-01, AC-QE-11: only Qwen changes provider-specific defaults."""
    assert BishengEmbedding._get_embedding_class("qwen") is OpenAIEmbeddings
    assert BishengEmbedding._get_embedding_class("azure_openai") is AzureOpenAIEmbeddings
    for provider in ["openai", "xinference", "llamacpp", "vllm", "qianfan", "minimax", "zhipu", "tencent", "silicon"]:
        assert BishengEmbedding._get_embedding_class(provider) is OpenAIEmbeddings
        assert embedding_module._node_type[provider]["params_handler"] is _get_openai_params
    params = _get_openai_params({"model": "other-model"}, {"base_url": BASE_URL, "api_key": "other-key"}, {})
    assert "chunk_size" not in params
    assert "model_kwargs" not in params


def raw_vector(text):
    return [float(text.split(":")[-1]) + 1, 1.0]


@pytest.fixture()
async def sdk_factory(monkeypatch):
    """Keep the real wrapper, LangChain and SDK; replace HTTP and external effects."""
    state = SimpleNamespace(requests=[], status=200, connection_error=False, constructions=0)

    def respond(request):
        state.requests.append(request)
        if state.connection_error:
            raise httpx.ConnectError("offline gateway", request=request)
        if state.status != 200:
            return httpx.Response(
                state.status, json={"error": {"message": "provider rejected request", "type": "error"}}
            )
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": body["model"],
                "data": [
                    {"object": "embedding", "index": i, "embedding": raw_vector(text)}
                    for i, text in enumerate(body["input"])
                ],
                "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])},
            },
        )

    monkeypatch.setattr(model_utils, "sync_bisheng_model_limit_check", lambda model: None)
    monkeypatch.setattr(model_utils, "upload_telemetry_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(BishengEmbedding, "sync_update_model_status", lambda *args: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as sync_http:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_http:

            def construct(**params):
                state.constructions += 1
                return OpenAIEmbeddings(**params, http_client=sync_http, http_async_client=async_http)

            monkeypatch.setitem(embedding_module._node_type["qwen"], "client", construct)

            def build(model_name="text-embedding-v4", advanced=None, server_config=None):
                server = LLMServer(
                    id=1,
                    name="Qwen fixture",
                    type="qwen",
                    config=server_config or {"openai_api_base": BASE_URL + "/", "openai_api_key": "fixture-key"},
                )
                model = LLMModel(
                    id=2,
                    server_id=1,
                    model_name=model_name,
                    model_type="embedding",
                    online=True,
                    config={"user_kwargs": {"max_retries": 0, **(advanced or {})}},
                )
                return BishengEmbedding(
                    model_id=2,
                    model_info=model,
                    server_info=server,
                    app_id="fixture",
                    app_type=ApplicationTypeEnum.MODEL_TEST,
                    app_name="fixture",
                    user_id=1,
                )

            yield build, state


@pytest.mark.parametrize("model,batch_size", MODEL_BATCHES)
@pytest.mark.parametrize("full_batches", [0, 1, 2])
@pytest.mark.parametrize("mode", ["sync", "wrapper_async", "sdk_async"])
async def test_real_sdk_splits_batches_and_preserves_input_order(sdk_factory, model, batch_size, full_batches, mode):
    """AC-QE-02, AC-QE-07, AC-QE-08, AC-QE-09, AC-QE-15: HTTP payload and splitting."""
    build, state = sdk_factory
    embedding = build(model, {"dimensions": 2})
    count = batch_size * full_batches + 1 if full_batches else batch_size
    texts = [f"sample:{i}" for i in range(count)]
    if mode == "sync":
        vectors = embedding.embed_documents(texts)
    elif mode == "wrapper_async":
        vectors = await embedding.aembed_documents(texts)
    else:
        vectors = await embedding.embeddings.aembed_documents(texts)

    bodies = [json.loads(request.content) for request in state.requests]
    expected_batches = [batch_size] * full_batches + [1] if full_batches else [batch_size]
    assert [len(body["input"]) for body in bodies] == expected_batches
    assert [text for body in bodies for text in body["input"]] == texts
    for request, body in zip(state.requests, bodies, strict=True):
        assert request.method == "POST"
        assert str(request.url) == BASE_URL + "/embeddings"
        assert request.headers["Authorization"] == "Bearer fixture-key"
        assert body == {"model": model, "input": body["input"], "dimensions": 2, "encoding_format": "float"}
    expected = np.array([raw_vector(text) for text in texts])
    if mode != "sdk_async":
        expected = expected / np.linalg.norm(expected, axis=1, keepdims=True)
    np.testing.assert_allclose(vectors, expected)


@pytest.mark.parametrize("mode", ["sync", "wrapper_async", "sdk_async"])
async def test_query_reaches_configured_endpoint_and_normalizes(sdk_factory, mode):
    build, state = sdk_factory
    embedding = build()
    if mode == "sync":
        vector = embedding.embed_query("sample:7")
    elif mode == "wrapper_async":
        vector = await embedding.aembed_query("sample:7")
    else:
        vector = await embedding.embeddings.aembed_query("sample:7")
    assert len(state.requests) == 1
    assert str(state.requests[0].url) == BASE_URL + "/embeddings"
    assert json.loads(state.requests[0].content)["input"] == ["sample:7"]
    expected = np.array(raw_vector("sample:7"))
    if mode != "sdk_async":
        expected = expected / np.linalg.norm(expected)
    np.testing.assert_allclose(vector, expected)


@pytest.mark.parametrize("model,chunk_size", [("text-embedding-v4", 3), ("gateway-embedding-alias", 30)])
async def test_explicit_batch_size_controls_real_requests(sdk_factory, model, chunk_size):
    build, state = sdk_factory
    embedding = build(model, {"chunk_size": chunk_size})
    await embedding.aembed_documents([f"sample:{i}" for i in range(chunk_size + 1)])
    assert [len(json.loads(request.content)["input"]) for request in state.requests] == [chunk_size, 1]


async def test_over_limit_fails_before_client_construction(sdk_factory):
    build, state = sdk_factory
    with pytest.raises(ValueError, match="must not exceed 10"):
        build(advanced={"chunk_size": 11})
    assert state.constructions == 0
    assert state.requests == []


async def test_provider_alias_conflicts_cannot_override_actual_request(sdk_factory):
    build, state = sdk_factory
    embedding = build(
        advanced={
            "model": "ignored-model",
            "api_key": "ignored-key",
            "openai_api_key": "ignored-alias-key",
            "base_url": "https://ignored.test/v1",
            "openai_api_base": "https://ignored-alias.test/v1",
        }
    )
    await embedding.aembed_query("sample:0")
    assert str(state.requests[0].url) == BASE_URL + "/embeddings"
    assert state.requests[0].headers["Authorization"] == "Bearer fixture-key"
    assert json.loads(state.requests[0].content)["model"] == "text-embedding-v4"


async def test_missing_url_uses_qwen_endpoint_in_actual_request(sdk_factory):
    build, state = sdk_factory
    embedding = build(server_config={"openai_api_key": "fixture-key", "openai_api_base": None})
    await embedding.aembed_query("sample:0")
    assert str(state.requests[0].url) == "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


@pytest.mark.parametrize("failure", [400, 401, 404, 429, 500, "connection"])
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_provider_failure_is_reported_without_endpoint_fallback_or_batch_retry(sdk_factory, failure, mode):
    """AC-QE-10, AC-QE-14: failures keep the configured endpoint and batch size."""
    build, state = sdk_factory
    if failure == "connection":
        state.connection_error = True
    else:
        state.status = failure
    embedding = build("gateway-embedding-alias", {"chunk_size": 30})
    texts = [f"sample:{i}" for i in range(31)]
    with pytest.raises(openai.APIError):
        if mode == "sync":
            embedding.embed_documents(texts)
        else:
            await embedding.aembed_documents(texts)
    assert len(state.requests) == 1
    assert str(state.requests[0].url) == BASE_URL + "/embeddings"
    assert len(json.loads(state.requests[0].content)["input"]) == 30
