"""Provider contracts using synthetic payloads and an isolated HTTP transport."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from bisheng.common.errcode.llm import ModelDiscoveryError
from test.llm.discovery_test_loader import catalog, presets, providers

ModelDiscoveryService = catalog.ModelDiscoveryService
identify_type = catalog.identify_type
PRESETS = presets.PRESETS
PROVIDERS = providers.PROVIDERS
build_plan, connection, sign_ark = providers.build_plan, providers.connection, providers.sign_ark

REAL_CLIENT = httpx.AsyncClient


def transport(monkeypatch, handler):
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)
    )


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
async def test_every_form_provider_has_a_catalog_path(monkeypatch, provider):
    requests = []

    def handler(request):
        requests.append(request)
        if provider == "ollama":
            return httpx.Response(200, json={"models": [{"name": "alias", "capabilities": ["embedding"]}]})
        if provider == "xinference":
            return httpx.Response(200, json={"alias": {"model_type": "embedding"}})
        return httpx.Response(200, json={"data": [{"id": "alias", "sub_type": "embedding"}]})

    transport(monkeypatch, handler)
    config = {
        "base_url": "https://gateway.example/v1",
        "azure_endpoint": "https://gateway.example",
        "anthropic_api_url": "https://gateway.example/v1",
    }
    result = await ModelDiscoveryService.discover(provider, config, source="live")
    assert result["source"] == "live"
    assert result["models"][0]["model_type"] == "embedding"
    assert len(requests) == 1


@pytest.mark.parametrize("provider", sorted(PRESETS))
async def test_native_presets_are_explicit_and_make_no_network_calls(monkeypatch, provider):
    def unexpected(request):
        pytest.fail("A preset catalog must use its bundled snapshot")

    transport(monkeypatch, unexpected)
    result = await ModelDiscoveryService.discover(provider, {}, source="preset")
    assert result["source"] == "preset"
    assert result["catalog_date"] == "2026-10-21"
    assert result["docs_url"].startswith("https://")
    assert result["models"]


async def test_custom_gateway_failures_never_turn_into_vendor_presets(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(401, text="private failure"))
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("zhipu", {"openai_api_base": "https://gateway.example/v1"})
    assert error.value.kwargs["reason"] == "auth"


async def test_native_bailian_pages_and_capabilities(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        page = int(request.url.params["page_no"])
        row = (
            {"model": "private-speech", "name": "Speech", "capabilities": ["ASR"]}
            if page == 1
            else {"model": "private-vector", "capabilities": ["TR", "ME"]}
        )
        return httpx.Response(200, json={"output": {"total": 2, "models": [row]}})

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover(
        "qwen", {"openai_api_key": "fixture"}, options={"workspace_id": "workspace-test"}
    )
    assert requests[0].url.host == "workspace-test.cn-beijing.maas.aliyuncs.com"
    assert [r.url.params["page_no"] for r in requests] == ["1", "2"]
    assert requests[1].headers["authorization"] == "Bearer fixture"
    assert [m["model_type"] for m in result["models"]] == ["asr", "embedding"]


async def test_bailian_compatible_mode_and_workspace_validation(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))
    result = await ModelDiscoveryService.discover("qwen", {})
    assert result["models"] == []
    result = await ModelDiscoveryService.discover("qwen", {}, source="live")
    assert result["models"] == []
    with pytest.raises(ModelDiscoveryError):
        build_plan("qwen", {}, "auto", {"workspace_id": "foo.example/path"})


async def test_ark_lists_running_endpoint_ids_with_signed_pagination(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        page = json.loads(request.content)["PageNumber"]
        return httpx.Response(
            200,
            json={
                "Result": {
                    "TotalCount": 2,
                    "Items": [
                        {
                            "Id": f"ep-{page}",
                            "Name": "alias",
                            "Status": "Running",
                            "ModelReference": {"FoundationModel": {"Name": "doubao-seed-2.0-pro"}},
                        }
                    ],
                }
            },
        )

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover(
        "volcengine",
        {"api_key": "inference-fixture"},
        options={"access_key_id": "ak-fixture", "secret_access_key": "sk-fixture"},
    )
    assert [m["model_name"] for m in result["models"]] == ["ep-1", "ep-2"]
    assert result["models"][0]["model_type"] == "llm"
    assert result["scope"] == "deployments"
    assert requests[1].url.host == "ark.cn-beijing.volcengineapi.com"
    assert requests[0].headers["authorization"].startswith("HMAC-SHA256 Credential=ak-fixture/")
    assert "inference-fixture" not in str(requests[0].headers)
    assert requests[0].headers["authorization"] != requests[1].headers["authorization"]


def test_signing_is_deterministic_and_covers_body_and_session_token():
    url = "https://ark.cn-beijing.volcengineapi.com/?Action=ListEndpoints&Version=2024-01-01"
    options = {"access_key_id": "example-ak", "secret_access_key": "example-sk", "session_token": "example-token"}
    now = datetime(2026, 10, 21, tzinfo=UTC)
    result = sign_ark(url, '{"PageNumber":1}', options, now)
    assert result == sign_ark(url, '{"PageNumber":1}', options, now)
    assert result["x-date"] == "20261021T000000Z"
    assert result["x-security-token"] == "example-token"
    assert "x-security-token" in result["Authorization"]
    assert result["Authorization"] != sign_ark(url, '{"PageNumber":2}', options, now)["Authorization"]


async def test_ark_management_credentials_are_required(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("volcengine", {"api_key": "inference-fixture"})
    assert error.value.kwargs["reason"] == "credentials"


async def test_azure_catalog_marks_model_ids_and_uses_api_key(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover(
        "azure_openai", {"azure_endpoint": "https://account.openai.azure.com", "openai_api_key": "fixture"}
    )
    assert requests[0].url.path == "/openai/v1/models"
    assert requests[0].headers["api-key"] == "fixture"
    assert result["scope"] == "azure_models"


async def test_azure_arm_imports_deployment_name_and_follows_same_resource(monkeypatch):
    requests = []
    resource = "/subscriptions/sub-test/resourceGroups/group/providers/Microsoft.CognitiveServices/accounts/account"
    url = f"https://management.azure.com{resource}/deployments"

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "name": "production",
                            "properties": {"provisioningState": "Succeeded", "model": {"name": "gpt-4o"}},
                        }
                    ],
                    "nextLink": url + "?api-version=2024-10-01&$skiptoken=page2",
                },
            )
        return httpx.Response(200, json={"value": []})

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover(
        "azure_openai",
        {"azure_endpoint": "https://account.openai.azure.com"},
        options={"resource_id": resource, "management_token": "fixture-token"},
    )
    assert result["models"][0]["model_name"] == "production"
    assert result["models"][0]["model_type"] == "llm"
    assert result["scope"] == "deployments"
    assert requests[1].url.params["$skiptoken"] == "page2"
    assert requests[1].headers["authorization"] == "Bearer fixture-token"


async def test_arm_pagination_cannot_redirect_credentials(monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(200, json={"value": [], "nextLink": "https://evil.example/deployments"}),
    )
    with pytest.raises(ModelDiscoveryError):
        await ModelDiscoveryService.discover(
            "azure_openai",
            {"azure_endpoint": "https://account.openai.azure.com"},
            options={
                "resource_id": "/subscriptions/sub/resourceGroups/group/providers/Microsoft.CognitiveServices/accounts/account",
                "management_token": "fixture",
            },
        )


@pytest.mark.parametrize(
    "capabilities,expected",
    [
        (["TG", "Reasoning"], ("llm", "metadata")),
        (["TR", "ME"], ("embedding", "metadata")),
        (["ASR", "TTS"], (None, "unknown")),
        (["IG"], (None, "unsupported")),
        ([{"bad": True}], (None, "unknown")),
    ],
)
def test_metadata_handles_multimodal_and_malformed_capabilities(capabilities, expected):
    assert identify_type({"id": "private", "capabilities": capabilities}) == expected


def test_anthropic_custom_api_field_is_respected():
    assert connection(
        "anthropic", {"anthropic_api_url": "https://proxy.example/prefix/v1", "anthropic_api_key": "fixture"}
    ) == ("https://proxy.example/prefix/v1/models", {"x-api-key": "fixture", "anthropic-version": "2023-06-01"})


async def test_truncated_native_pagination_fails_instead_of_returning_partial_list(monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"output": {"total": 2, "models": [{"model": "repeated", "capabilities": ["TG"]}]}}
        ),
    )
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("qwen", {}, options={"workspace_id": "test"})
    assert error.value.kwargs["reason"] == "format"


async def test_silicon_classifies_aliases_using_native_subtype_filters(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        subtype = request.url.params.get("sub_type")
        rows = (
            [{"id": "private-a"}, {"id": "private-b"}]
            if subtype is None
            else [{"id": "private-a"}]
            if subtype == "embedding"
            else [{"id": "private-b"}]
            if subtype == "reranker"
            else []
        )
        return httpx.Response(200, json={"data": rows})

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover("silicon", {"api_key": "fixture"})
    assert [m["model_type"] for m in result["models"]] == ["embedding", "rerank"]
    assert all(m["type_source"] == "metadata" for m in result["models"])
    assert len(requests) == 8


@pytest.mark.parametrize("payload", [{"ResponseMetadata": "bad"}, {"data": [], "error": "private-body"}])
async def test_malformed_vendor_errors_are_sanitized(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("openai", {})
    assert "private-body" not in str(error.value)


@pytest.mark.parametrize(
    "name,kind", [("glm-asr-2512", "asr"), ("glm-tts", "tts"), ("hunyuan-embedding", "embedding"), ("glm-image", None)]
)
def test_specialized_models_precede_chat_family_names(name, kind):
    assert identify_type({"id": name})[0] == kind


@pytest.mark.parametrize("provider", ["qwen", "volcengine", *sorted(PRESETS)])
async def test_auto_uses_existing_key_before_requesting_extra_information(monkeypatch, provider):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "qwen-max"}]})

    transport(monkeypatch, handler)
    result = await ModelDiscoveryService.discover(provider, {"api_key": "fixture"})
    assert result["source"] == "live"
    assert result["models"][0]["model_name"] == "qwen-max"
    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer fixture"


@pytest.mark.parametrize("provider,reason", [("qwen", "workspace"), ("volcengine", "credentials")])
async def test_requests_extra_information_only_after_unsupported_list(monkeypatch, provider, reason):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(404)

    transport(monkeypatch, handler)
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover(provider, {"api_key": "fixture"})
    assert error.value.kwargs["reason"] == reason
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["qwen", "volcengine", "zhipu"])
@pytest.mark.parametrize("status,reason", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "failure")])
async def test_auto_preserves_operational_errors(monkeypatch, provider, status, reason):
    transport(monkeypatch, lambda request: httpx.Response(status))
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover(provider, {"api_key": "fixture"})
    assert error.value.kwargs["reason"] == reason


@pytest.mark.parametrize("provider", sorted(PRESETS))
async def test_unsupported_official_catalog_uses_labeled_preset(monkeypatch, provider):
    transport(monkeypatch, lambda request: httpx.Response(404))
    result = await ModelDiscoveryService.discover(provider, {"api_key": "fixture"})
    assert result["source"] == "preset"
    assert result["catalog_date"]


async def test_auto_preserves_timeout_and_invalid_payload(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("fixture", request=request)

    transport(monkeypatch, timeout)
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("qwen", {"api_key": "fixture"})
    assert error.value.kwargs["reason"] == "timeout"
    transport(monkeypatch, lambda request: httpx.Response(200, json={"unexpected": []}))
    with pytest.raises(ModelDiscoveryError) as error:
        await ModelDiscoveryService.discover("qwen", {"api_key": "fixture"})
    assert error.value.kwargs["reason"] == "format"
