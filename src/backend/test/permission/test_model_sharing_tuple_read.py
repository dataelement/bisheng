"""Read real OpenFGA response shapes through FGAClient and the sharing owner."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.openfga.client import FGAClient
from bisheng.permission.application.model_sharing_projection import ModelSharingProjectionApplication


def tuple_key(tenant=19, **extra):
    return {"user": f"tenant:{tenant}", "relation": "shared_with", "object": "llm_server:358", **extra}


@pytest.fixture
def sharing_reader(monkeypatch):
    original_client = httpx.AsyncClient

    @asynccontextmanager
    async def open_reader(pages):
        requests = []

        def handle(request):
            assert request.method == "POST" and request.url.path == "/stores/native-store/read"
            body = json.loads(request.content)
            assert body["tuple_key"] == {"object": "llm_server:358", "relation": "shared_with"}
            assert body["consistency"] == "HIGHER_CONSISTENCY"
            index = len(requests)
            assert body.get("continuation_token") == (f"page-{index}" if index else None)
            requests.append(request)
            response = {"tuples": [{"key": row, "timestamp": "2026-11-18T09:55:51Z"} for row in pages[index]]}
            if index + 1 < len(pages):
                response["continuation_token"] = f"page-{index + 1}"
            return httpx.Response(200, json=response)

        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle))
        )
        client = FGAClient("http://openfga", "native-store", "native-model")
        app = ModelSharingProjectionApplication(
            client=client, marker=None, scope=SimpleNamespace(check_request=lambda: None)
        )
        try:
            yield app, client, requests
        finally:
            await client.close()

    return open_reader


@pytest.mark.parametrize("explicit_null", [False, True])
async def test_reads_all_pages_of_unconditional_shares(sharing_reader, explicit_null):
    extra = {"condition": None} if explicit_null else {}
    async with sharing_reader([[tuple_key(60, **extra)], [tuple_key(19, **extra)]]) as (app, _, requests):
        snapshot = await app.aread(server_id=358)
        assert snapshot.subjects == (19, 60)
        assert (snapshot.store_id, snapshot.model_id) == ("native-store", "native-model")
        assert len(requests) == 2


@pytest.mark.parametrize("condition", [{}, {"name": "expires_at", "context": {}}, False, ""])
async def test_does_not_flatten_real_or_malformed_conditions(sharing_reader, condition):
    async with sharing_reader([[tuple_key(condition=condition)]]) as (app, _, _):
        with pytest.raises(PermissionPublishNotReadyError, match="invalid existing sharing tuple"):
            await app.aread(server_id=358)


@pytest.mark.parametrize(
    "row",
    [
        tuple_key(condition=None, extra=None),
        {"relation": "shared_with", "object": "llm_server:358", "condition": None},
        {**tuple_key(condition=None), "relation": "owner"},
        {**tuple_key(condition=None), "object": "llm_server:335"},
        {**tuple_key(condition=None), "user": "user:19"},
        {**tuple_key(condition=None), "user": "tenant:019"},
        {**tuple_key(condition=None), "user": "tenant:0"},
        {**tuple_key(condition=None), "user": "tenant:19#member"},
    ],
)
async def test_preserves_exact_tuple_and_tenant_validation(sharing_reader, row):
    async with sharing_reader([[row]]) as (app, _, _):
        with pytest.raises(PermissionPublishNotReadyError):
            await app.aread(server_id=358)


async def test_duplicate_subjects_still_block_across_null_and_absent_condition(sharing_reader):
    async with sharing_reader([[tuple_key()], [tuple_key(condition=None)]]) as (app, _, _):
        with pytest.raises(PermissionPublishNotReadyError, match="duplicate existing sharing tuple"):
            await app.aread(server_id=358)


async def test_model_pin_change_still_blocks_the_read(sharing_reader):
    async with sharing_reader([[tuple_key(condition=None)]]) as (app, client, _):
        original = client.iter_tuples

        async def changed(**kwargs):
            async for row in original(**kwargs):
                client._model_id = "another-model"
                yield row

        client.iter_tuples = changed
        with pytest.raises(PermissionPublishNotReadyError, match="authorization pin changed"):
            await app.aread(server_id=358)
