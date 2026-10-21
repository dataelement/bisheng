"""F087: each provider probe against recorded response shapes (httpx.MockTransport).

Response bodies follow each provider's documented / source-verified shape; see the
survey table in features/v3.0.0/087-context-window-budget/plan.md §3.1.
"""

import httpx
import pytest

from bisheng.llm.domain.services.context_window import ModelSnapshot
from bisheng.llm.domain.services.context_window_probes import ProbeResult, probe_context_window


def _snapshot(server_type: str, client_params: dict, model_name: str = "qwen3-32b") -> ModelSnapshot:
    return ModelSnapshot(
        model_id=1,
        model_name=model_name,
        server_type=server_type,
        model_config={},
        client_params=client_params,
    )


def _client(routes: dict) -> httpx.AsyncClient:
    """``routes`` maps "METHOD url" to a JSON body, or to an int status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(f"{request.method} {request.url}")
        if body is None:
            return httpx.Response(404, json={"error": "not found"})
        if isinstance(body, int):
            return httpx.Response(body, json={"error": "boom"})
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


VLLM_MODELS = {
    "object": "list",
    "data": [
        {"id": "other-model", "object": "model", "max_model_len": 8192},
        {"id": "qwen3-32b", "object": "model", "root": "/models/qwen3", "parent": None, "max_model_len": 133120},
        {"id": "qwen3-lora", "object": "model", "root": "/lora/a", "parent": "qwen3-32b", "max_model_len": None},
    ],
}


async def test_vllm_picks_the_configured_model():
    snapshot = _snapshot("vllm", {"base_url": "http://vllm:8000/v1", "api_key": "k"})
    result = await probe_context_window(snapshot, _client({"GET http://vllm:8000/v1/models": VLLM_MODELS}))

    assert result == ProbeResult(window=133120, kind="total", source="deployed")


async def test_vllm_lora_adapter_uses_its_base_model():
    snapshot = _snapshot("vllm", {"base_url": "http://vllm:8000/v1"}, model_name="qwen3-lora")
    result = await probe_context_window(snapshot, _client({"GET http://vllm:8000/v1/models": VLLM_MODELS}))

    assert result.window == 133120


async def test_vllm_unknown_model_gives_none():
    snapshot = _snapshot("vllm", {"base_url": "http://vllm:8000/v1"}, model_name="missing")
    assert await probe_context_window(snapshot, _client({"GET http://vllm:8000/v1/models": VLLM_MODELS})) is None


async def test_openai_type_reads_vllm_field_as_deployed():
    snapshot = _snapshot("openai", {"base_url": "http://gateway.local/v1"})
    result = await probe_context_window(snapshot, _client({"GET http://gateway.local/v1/models": VLLM_MODELS}))

    assert result.source == "deployed"


async def test_openai_type_reads_context_length_as_published():
    body = {"data": [{"id": "qwen3-32b", "context_length": 131072}]}
    snapshot = _snapshot("openai", {"base_url": "https://openrouter.ai/api/v1"})
    result = await probe_context_window(snapshot, _client({"GET https://openrouter.ai/api/v1/models": body}))

    assert result == ProbeResult(window=131072, kind="total", source="published")


async def test_official_openai_is_not_probed():
    snapshot = _snapshot("openai", {"base_url": "https://api.openai.com/v1"})
    # Any request would 404 through the mock; None must come without calling it.
    assert await probe_context_window(snapshot, _client({})) is None


async def test_llamacpp_props():
    body = {"default_generation_settings": {"n_ctx": 32768}}
    snapshot = _snapshot("llamacpp", {"base_url": "http://llama:8080/v1"})
    result = await probe_context_window(snapshot, _client({"GET http://llama:8080/props": body}))

    assert result == ProbeResult(window=32768, kind="total", source="deployed")


async def test_llamacpp_falls_back_to_models_meta():
    models = {"data": [{"id": "qwen3-32b", "meta": {"n_ctx": 16384, "n_ctx_train": 131072}}]}
    snapshot = _snapshot("llamacpp", {"base_url": "http://llama:8080/v1"})
    result = await probe_context_window(
        snapshot, _client({"GET http://llama:8080/props": 500, "GET http://llama:8080/v1/models": models})
    )

    assert result.window == 16384


async def test_ollama_loaded_model_reports_deployed_window():
    ps = {"models": [{"name": "qwen3:latest", "model": "qwen3:latest", "context_length": 8192}]}
    snapshot = _snapshot("ollama", {"base_url": "http://ollama:11434"}, model_name="qwen3")
    result = await probe_context_window(snapshot, _client({"GET http://ollama:11434/api/ps": ps}))

    assert result == ProbeResult(window=8192, kind="total", source="deployed")


async def test_ollama_unloaded_model_uses_modelfile_num_ctx():
    show = {"parameters": "stop <|im_end|>\nnum_ctx 16384", "model_info": {"qwen3.context_length": 40960}}
    snapshot = _snapshot("ollama", {"base_url": "http://ollama:11434"}, model_name="qwen3")
    result = await probe_context_window(
        snapshot,
        _client({"GET http://ollama:11434/api/ps": {"models": []}, "POST http://ollama:11434/api/show": show}),
    )

    assert result == ProbeResult(window=16384, kind="total", source="deployed")


async def test_ollama_unloaded_model_falls_back_to_trained_length():
    show = {"parameters": "stop <|im_end|>", "model_info": {"qwen3.context_length": 40960}}
    snapshot = _snapshot("ollama", {"base_url": "http://ollama:11434"}, model_name="qwen3")
    result = await probe_context_window(
        snapshot,
        _client({"GET http://ollama:11434/api/ps": {"models": []}, "POST http://ollama:11434/api/show": show}),
    )

    assert result == ProbeResult(window=40960, kind="total", source="published")


async def test_xinference_is_published():
    body = {"object": "list", "data": [{"id": "qwen3-32b", "context_length": 32768}]}
    snapshot = _snapshot("xinference", {"base_url": "http://xinf:9997/v1"})
    result = await probe_context_window(snapshot, _client({"GET http://xinf:9997/v1/models": body}))

    assert result == ProbeResult(window=32768, kind="total", source="published")


async def test_anthropic_returns_an_input_only_limit():
    body = {"id": "claude-sonnet-5-5", "max_input_tokens": 200000, "max_tokens": 64000}
    snapshot = _snapshot(
        "anthropic",
        {"anthropic_api_url": "https://api.anthropic.com", "anthropic_api_key": "k"},
        model_name="claude-sonnet-5-5",
    )
    result = await probe_context_window(
        snapshot, _client({"GET https://api.anthropic.com/v1/models/claude-sonnet-5-5": body})
    )

    assert result == ProbeResult(window=200000, kind="input", source="published")


async def test_deepseek_context_window():
    body = {"object": "list", "data": [{"id": "deepseek-chat", "context_window": 131072, "max_output_tokens": 8192}]}
    snapshot = _snapshot("deepseek", {"api_base": "https://api.deepseek.com", "api_key": "k"}, "deepseek-chat")
    result = await probe_context_window(snapshot, _client({"GET https://api.deepseek.com/models": body}))

    assert result == ProbeResult(window=131072, kind="total", source="published")


async def test_moonshot_context_length():
    body = {"data": [{"id": "kimi-k2", "context_length": 262144}]}
    snapshot = _snapshot("moonshot", {"base_url": "https://api.moonshot.cn/v1", "api_key": "k"}, "kimi-k2")
    result = await probe_context_window(snapshot, _client({"GET https://api.moonshot.cn/v1/models": body}))

    assert result == ProbeResult(window=262144, kind="total", source="published")


@pytest.mark.parametrize(
    "server_type,params,routes",
    [
        (
            "vllm",
            {"base_url": "http://vllm:8000/v1"},
            {"GET http://vllm:8000/v1/models": {"data": [{"id": "qwen3-32b"}]}},
        ),
        ("deepseek", {"api_base": "https://api.deepseek.com"}, {"GET https://api.deepseek.com/models": {"data": []}}),
        ("vllm", {"base_url": "http://vllm:8000/v1"}, {"GET http://vllm:8000/v1/models": 503}),
    ],
)
async def test_missing_field_or_http_error_gives_none(server_type, params, routes):
    assert await probe_context_window(_snapshot(server_type, params), _client(routes)) is None


async def test_timeout_gives_none():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapshot = _snapshot("vllm", {"base_url": "http://vllm:8000/v1"})
    assert await probe_context_window(snapshot, client) is None


async def test_unsupported_server_type_gives_none():
    assert await probe_context_window(_snapshot("zhipu", {"base_url": "x"}), _client({})) is None
