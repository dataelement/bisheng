"""T429: a native, pinned relation read never invents contextual evidence.

覆盖 AC: AC-68, AC-79, AC-83, AC-89
"""

import json

import httpx
import pytest

from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import FGAClientError, FGAModelError


@pytest.fixture
async def native_fga(monkeypatch):
    client = FGAClient("https://fga.invalid", "pinned-store", "pinned-model")
    observed = []
    response = {"objects": ["llm_server:11", "llm_server:12"]}

    def handle(request):
        observed.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=response)

    native_client = httpx.Client
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: native_client(transport=transport, **kwargs))
    try:
        yield client, observed, response
    finally:
        await client.close()


def query(client, **changes):
    return client.list_objects_sync(
        **{"user": "tenant:101", "relation": "shared_with", "type": "llm_server", **changes}
    )


def test_native_relation_query_uses_real_sync_transport_and_current_pins(native_fga):
    client, observed, _ = native_fga
    assert query(client) == ["llm_server:11", "llm_server:12"]
    assert observed == [
        (
            "/stores/pinned-store/list-objects",
            {
                "authorization_model_id": "pinned-model",
                "user": "tenant:101",
                "relation": "shared_with",
                "type": "llm_server",
                "consistency": "HIGHER_CONSISTENCY",
            },
        )
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"user": "user:7"},
        {"user": "tenant:101#member"},
        {"user": "tenant:0"},
        {"relation": "visible"},
        {"type": "workflow"},
    ],
)
def test_native_transport_only_accepts_the_declared_tenant_shared_server_query(native_fga, changes):
    client, observed, _ = native_fga
    with pytest.raises(FGAModelError):
        query(client, **changes)
    assert not observed


def test_native_query_cannot_skip_required_contextual_provider(native_fga):
    client, observed, _ = native_fga
    client.require_contextual_provider = True
    client._affected_relations = frozenset({("llm_server", "shared_with")})
    with pytest.raises(FGAModelError):
        query(client)
    assert not observed


@pytest.mark.parametrize("objects", [None, "not-a-list", [None], ["workflow:w"], ["llm_server:"]])
def test_incomplete_or_wrong_type_backend_response_is_not_an_empty_allow_list(native_fga, objects):
    client, _, response = native_fga
    response["objects"] = objects
    with pytest.raises(FGAClientError):
        query(client)
