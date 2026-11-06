"""Actual original FGA Store pagination without a tenant/resource product."""

import json
from dataclasses import FrozenInstanceError

import httpx
import pytest

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.openfga.client import FGAClient
from test.knowledge_unification import test_migration_permission_read as fixtures

module = fixtures.module
setup = fixtures.setup
reader = fixtures.reader


async def transport_reader(module, setup, handler):
    client = FGAClient("http://offline", "source-store", "source-model")
    await client._http.aclose()
    client._http = httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(handler))
    setup.factory.return_value = client
    return reader(module, setup), client


async def test_actual_transport_pages_whole_store_once_and_preserves_all_namespaces(module, setup):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert request.url.path == "/stores/source-store/read"
        assert request.method == "POST"
        assert "tuple_key" not in payload
        assert payload["consistency"] == "HIGHER_CONSISTENCY"
        offset = int(payload.get("continuation_token", "0"))
        rows = [
            {"key": {"user": "user:7", "relation": "viewer", "object": f"workflow:{n}"}}
            for n in range(offset, min(offset + 100, 205))
        ]
        return httpx.Response(
            200, json={"tuples": rows, "continuation_token": str(offset + 100) if offset < 200 else ""}
        )

    instance, client = await transport_reader(module, setup, handler)
    async with instance:
        stream = instance.aiter_original_tuples()
        first = await anext(stream)
        assert len(seen) == 1
        assert (first.user, first.relation, first.object) == ("user:7", "viewer", "workflow:0")
        with pytest.raises(FrozenInstanceError):
            first.user = "user:99"
        rest = [row async for row in stream]
        assert len(rest) == 204 and rest[-1].object == "workflow:204"
        assert len(seen) == 3
        with pytest.raises(PermissionMigrationBlockedError):
            _ = [row async for row in instance.aiter_original_tuples()]
        assert len(seen) == 3
    assert client._http.is_closed


@pytest.mark.parametrize(
    "key",
    [
        {"user": "user:7", "relation": "viewer", "object": "tool:8", "condition": {"name": "future"}},
        {"user": "user:7", "relation": "viewer", "object": "tool:8", "future": True},
        {"user": "", "relation": "viewer", "object": "tool:8"},
        {"user": "user:7", "relation": None, "object": "tool:8"},
        {"user": "user:7", "relation": "viewer", "object": " "},
        {"user": "user:7", "relation": "viewer", "object": "tool:\x00"},
        {"user": "user:7", "relation": "viewer", "object": "x" * 4097},
        {"user": "user:7", "relation": "viewer"},
        ["user:7", "viewer", "tool:8"],
    ],
)
async def test_unknown_condition_or_malformed_key_never_becomes_a_valid_baseline(module, setup, key):
    instance, client = await transport_reader(
        module, setup, lambda _: httpx.Response(200, json={"tuples": [{"key": key}]})
    )
    with pytest.raises(PermissionMigrationBlockedError):
        async with instance:
            _ = [row async for row in instance.aiter_original_tuples()]
    assert client._http.is_closed


async def test_empty_store_is_real_success_not_a_missing_reader(module, setup):
    calls = []
    instance, client = await transport_reader(
        module, setup, lambda request: calls.append(request) or httpx.Response(200, json={"tuples": []})
    )
    with pytest.raises(PermissionMigrationBlockedError):
        _ = [row async for row in instance.aiter_original_tuples()]
    assert calls == []
    async with instance:
        assert [row async for row in instance.aiter_original_tuples()] == []
    with pytest.raises(PermissionMigrationBlockedError):
        _ = [row async for row in instance.aiter_original_tuples()]
    assert len(calls) == 1 and client._http.is_closed


async def test_transport_failure_after_a_prefix_keeps_cause_and_cannot_restart(module, setup):
    error = httpx.ReadError("interrupted")
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 2:
            raise error
        return httpx.Response(
            200,
            json={
                "tuples": [{"key": {"user": "user:7", "relation": "viewer", "object": "app:a"}}],
                "continuation_token": "next",
            },
        )

    instance, client = await transport_reader(module, setup, handler)
    async with instance:
        stream = instance.aiter_original_tuples()
        assert (await anext(stream)).object == "app:a"
        with pytest.raises(PermissionMigrationBlockedError) as failure:
            await anext(stream)
        assert failure.value.__cause__.__cause__ is error
        with pytest.raises(PermissionMigrationBlockedError):
            _ = [row async for row in instance.aiter_original_tuples()]
    assert count == 2 and client._http.is_closed


@pytest.mark.parametrize("changed", ["store_id", "model_id", "closed"])
async def test_changed_or_closed_transport_is_rejected_at_next_yield(module, setup, changed):
    async def rows(**kwargs):
        assert kwargs == {"consistency": "HIGHER_CONSISTENCY"}
        yield {"user": "user:7", "relation": "viewer", "object": "knowledge_library:8"}
        yield {"user": "user:7", "relation": "viewer", "object": "knowledge_space:8"}

    setup.client.iter_tuples = rows
    instance = reader(module, setup)
    async with instance:
        stream = instance.aiter_original_tuples()
        assert (await anext(stream)).object == "knowledge_library:8"
        if changed == "closed":
            await instance.__aexit__(None, None, None)
        else:
            setattr(setup.client, changed, "wrong")
        with pytest.raises(PermissionMigrationBlockedError):
            await anext(stream)
