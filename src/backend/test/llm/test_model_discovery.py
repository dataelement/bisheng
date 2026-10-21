"""Isolated catalog tests; run with --confcutdir=test/llm."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from test.llm.discovery_test_loader import catalog, providers

REAL_CLIENT = httpx.AsyncClient

path = Path(__file__).parents[2] / "bisheng/llm/domain/services/model_discovery.py"


@pytest.mark.parametrize(
    "item,kind,source",
    [
        ({"id": "private-alias", "model_type": "ASR"}, "asr", "metadata"),
        ({"id": "gpt-4o", "model_info": {"mode": "embedding"}}, "embedding", "metadata"),
        ({"id": "whisper-1"}, "asr", "registry"),
        ({"id": "Qwen/Qwen3-Reranker-8B"}, "rerank", "registry"),
        ({"id": "Qwen/Qwen3-Embedding-8B"}, "embedding", "registry"),
        ({"id": "qwen3.7-plus"}, "llm", "registry"),
        ({"id": "gpt-4o-mini-tts"}, "tts", "registry"),
        ({"id": "gpt-image-1"}, None, "unsupported"),
        ({"id": "private-gpt", "task": "image_generation"}, None, "unsupported"),
        ({"id": "deployment-abc"}, None, "unknown"),
        ({"id": "deepseek-v4-flash-260425"}, "llm", "registry"),
        ({"id": "deepseek-flash"}, "llm", "registry"),
        ({"id": "doubao-1-5-pro-256k-250115"}, "llm", "registry"),
        ({"id": "doubao-seed-2.0-pro"}, "llm", "registry"),
        ({"id": "doubao-seedream-5-0-pro"}, None, "unsupported"),
        ({"id": "doubao-seedance-2-0-pro"}, None, "unsupported"),
        ({"id": "doubao-embedding-large-text-240915"}, "embedding", "registry"),
        ({"id": "gemini-3.8-flash-tts"}, "tts", "registry"),
        ({"id": "gemini-3.7-pro"}, "llm", "registry"),
    ],
)
def test_capabilities_precede_model_family(item, kind, source):
    assert catalog.identify_type(item) == (kind, source)


@pytest.mark.parametrize(
    "provider,config,url",
    [
        ("openai", {}, "https://api.openai.com/v1/models"),
        ("vllm", {"openai_api_base": "http://inference.internal:8000/v1/"}, "http://inference.internal:8000/v1/models"),
        ("ollama", {"base_url": "http://inference.internal:11434/v1"}, "http://inference.internal:11434/api/tags"),
        ("ollama", {"base_url": "http://inference.internal:11434/api/"}, "http://inference.internal:11434/api/tags"),
    ],
)
def test_provider_address_normalization(provider, config, url):
    assert providers.connection(provider, config)[0] == url


@pytest.mark.parametrize(
    "address",
    [
        "",
        "file:///etc/passwd",
        "https://user:pass@example.com",
        "https://example.com?key=value",
        "http://169.254.169.254",
    ],
)
def test_invalid_addresses_are_rejected(address):
    with pytest.raises(catalog.ModelDiscoveryError):
        providers.connection("vllm", {"openai_api_base": address})


def test_masked_key_requires_saved_connection_resolution():
    with pytest.raises(catalog.ModelDiscoveryError):
        providers.connection("openai", {"openai_api_key": "********"})


def test_native_and_compatible_shapes_and_deduplication():
    result = catalog.normalize_catalog({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o"}, {"id": "whisper-1"}]}, "openai")
    assert [item["model_name"] for item in result] == ["gpt-4o", "whisper-1"]
    result = catalog.normalize_catalog({"my-alias": {"model_type": "embedding"}}, "xinference")
    assert result[0]["model_name"] == "my-alias"
    assert result[0]["model_type"] == "embedding"
    assert (
        catalog.normalize_catalog({"models": [{"name": "nomic-embed-text:latest"}]}, "ollama")[0]["model_type"]
        == "embedding"
    )


def mock_transport(monkeypatch, handler):
    client = REAL_CLIENT
    monkeypatch.setattr(
        catalog.httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs)
    )


async def test_pagination_keeps_authenticated_origin_and_merges_pages(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"data": [{"id": "claude-a"}], "has_more": True, "last_id": "claude-a"})
        return httpx.Response(200, json={"data": [{"id": "claude-b"}], "has_more": False})

    mock_transport(monkeypatch, handler)
    result = await catalog.ModelDiscoveryService.discover("anthropic", {"anthropic_api_key": "test"})
    assert [item["model_name"] for item in result["models"]] == ["claude-a", "claude-b"]
    assert requests[1].url.params["after_id"] == "claude-a"
    assert requests[1].headers["x-api-key"] == "test"
    assert requests[1].url.host == "api.anthropic.com"


@pytest.mark.parametrize(
    "status,reason", [(401, "auth"), (403, "auth"), (404, "unsupported"), (302, "failure"), (503, "failure")]
)
async def test_provider_errors_redact_body_and_redirects(monkeypatch, status, reason):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, text="private upstream credentials", headers={"Location": "http://untrusted.example"}
        )

    mock_transport(monkeypatch, handler)
    with pytest.raises(catalog.ModelDiscoveryError) as caught:
        await catalog.ModelDiscoveryService.discover("openai", {})
    assert caught.value.kwargs["reason"] == reason
    assert "private upstream" not in str(caught.value)
    assert len(requests) == 1


async def test_timeout_and_invalid_response_are_business_failures(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("secret", request=request)

    mock_transport(monkeypatch, timeout)
    with pytest.raises(catalog.ModelDiscoveryError) as caught:
        await catalog.ModelDiscoveryService.discover("openai", {})
    assert caught.value.kwargs["reason"] == "timeout"
    assert "secret" not in str(caught.value)


async def test_empty_and_invalid_json(monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))
    assert await catalog.ModelDiscoveryService.discover("openai", {}) == {
        "models": [],
        "source": "live",
        "scope": "catalog",
    }
    mock_transport(monkeypatch, lambda request: httpx.Response(200, text="<html>invalid</html>"))
    with pytest.raises(catalog.ModelDiscoveryError) as caught:
        await catalog.ModelDiscoveryService.discover("openai", {})
    assert caught.value.kwargs["reason"] == "format"


async def test_repeated_cursor_is_rejected(monkeypatch):
    mock_transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": [{"id": "claude-a"}], "has_more": True, "last_id": "claude-a"}
        ),
    )
    with pytest.raises(catalog.ModelDiscoveryError):
        await catalog.ModelDiscoveryService.discover("anthropic", {})


def saved_connection_service():
    """Compile the real coordinator in isolation from unrelated runtime imports."""
    source = (path.parent / "llm.py").read_text()
    service_node = next(
        node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "LLMService"
    )
    method = next(
        node for node in service_node.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "discover_models"
    )
    module = ast.Module(
        body=[ast.ClassDef(name="Coordinator", bases=[], keywords=[], body=[method], decorator_list=[])],
        type_ignores=[],
    )
    from bisheng.utils.mask_data import JsonFieldMasker

    namespace = {
        "ModelDiscoveryRequest": catalog.ModelDiscoveryRequest,
        "UserPayload": object,
        "ModelDiscoveryError": catalog.ModelDiscoveryError,
        "LLMSystemConfigForbiddenError": PermissionError,
        "JsonFieldMasker": JsonFieldMasker,
        "LLMDao": SimpleNamespace(aget_server_by_id=AsyncMock()),
        "ModelDiscoveryService": SimpleNamespace(discover=AsyncMock(return_value={"models": []})),
    }
    exec(compile(ast.fix_missing_locations(module), "saved-connection-coordinator", "exec"), namespace)
    coordinator = namespace["Coordinator"]
    coordinator.get_one_llm = AsyncMock()
    coordinator.strip_config_whitespace = lambda value: value
    return coordinator, namespace


async def test_shared_readonly_connection_rejects_before_using_credentials():
    coordinator, namespace = saved_connection_service()
    coordinator.get_one_llm.return_value = SimpleNamespace(is_root_shared_readonly=True)
    with pytest.raises(PermissionError):
        await coordinator.discover_models(catalog.ModelDiscoveryRequest(provider="openai", server_id=1), object())
    namespace["LLMDao"].aget_server_by_id.assert_not_called()
    namespace["ModelDiscoveryService"].discover.assert_not_called()


async def test_provider_change_rejects_saved_credentials():
    coordinator, namespace = saved_connection_service()
    coordinator.get_one_llm.return_value = SimpleNamespace(is_root_shared_readonly=False, type="openai")
    with pytest.raises(catalog.ModelDiscoveryError):
        await coordinator.discover_models(catalog.ModelDiscoveryRequest(provider="qwen", server_id=1), object())
    namespace["LLMDao"].aget_server_by_id.assert_not_called()


async def test_masked_key_reuses_saved_key_and_honors_new_address():
    coordinator, namespace = saved_connection_service()
    coordinator.get_one_llm.return_value = SimpleNamespace(is_root_shared_readonly=False, type="openai")
    namespace["LLMDao"].aget_server_by_id.return_value = SimpleNamespace(
        config={"openai_api_key": "fixture", "openai_api_base": "http://old.internal/v1"}
    )
    await coordinator.discover_models(
        catalog.ModelDiscoveryRequest(
            provider="openai",
            server_id=1,
            config={"openai_api_key": "********", "openai_api_base": "http://new.internal/v1"},
        ),
        object(),
    )
    namespace["ModelDiscoveryService"].discover.assert_awaited_once_with(
        "openai", {"openai_api_key": "fixture", "openai_api_base": "http://new.internal/v1"}, source="auto", options={}
    )


async def test_new_connection_uses_input_without_reading_saved_secrets():
    coordinator, namespace = saved_connection_service()
    await coordinator.discover_models(
        catalog.ModelDiscoveryRequest(provider="openai", config={"openai_api_key": "fixture"}), object()
    )
    coordinator.get_one_llm.assert_not_called()
    namespace["LLMDao"].aget_server_by_id.assert_not_called()
    namespace["ModelDiscoveryService"].discover.assert_awaited_once_with(
        "openai", {"openai_api_key": "fixture"}, source="auto", options={}
    )


def test_anthropic_key_is_masked_and_preserved_on_unchanged_edit():
    from bisheng.utils.mask_data import JsonFieldMasker

    masker = JsonFieldMasker()
    original = {"anthropic_api_key": "fixture"}
    masked = masker.mask_json(original)
    assert masked == {"anthropic_api_key": "********"}
    assert masker.update_json_with_masked(original, masked) == original
