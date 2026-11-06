"""T712: the operational reader pins the original model without online gates."""

import importlib
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.tenant import bypass_tenant_filter, management_tenant_scope
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import OpenFGARuntimePin
from bisheng.permission.migration.f118_plan import (
    AuthorizationPinBaseline,
    CatalogReleaseBaseline,
    PermissionCatalogBaseline,
)


@pytest.fixture
def module():
    return importlib.import_module("bisheng.permission.application.migration_read")


@pytest.fixture
def setup():
    catalog = PermissionCatalogBaseline(
        CatalogReleaseBaseline(1, "original", 1, "c" * 64, 10),
        AuthorizationPinBaseline(10, "test", "source-store", "source-model", "a" * 64, "b" * 64),
        (),
        (),
    )
    client = SimpleNamespace(
        store_id="source-store",
        model_id="source-model",
        stream_list_objects=AsyncMock(return_value=("llm_server:2", "llm_server:3")),
        close=AsyncMock(),
    )
    discovery = AsyncMock(return_value=OpenFGARuntimePin("source-store", "source-model", "a" * 64))
    return SimpleNamespace(catalog=catalog, client=client, discovery=discovery, factory=Mock(return_value=client))


def reader(module, setup):
    return module.PinnedMigrationPermissionReader(
        OpenFGAConf(), setup.catalog, discovery=setup.discovery, client_factory=setup.factory
    )


async def test_original_pin_is_sent_to_discovery_and_transport_and_connection_is_owned(module, setup):
    instance = reader(module, setup)
    async with AsyncSession() as session, session.begin(), instance:
        with management_tenant_scope(101):
            assert await instance.aget_shared_server_ids(session, 101) == frozenset({2, 3})
        with management_tenant_scope(1):
            assert await instance.aget_shared_server_ids(session, 1) == frozenset()
        setup.client.stream_list_objects.assert_awaited_once_with(
            user="tenant:101", relation="shared_with", type="llm_server", consistency="HIGHER_CONSISTENCY"
        )
    kwargs = setup.discovery.call_args.kwargs
    assert kwargs == {
        "expected_model": None,
        "allow_bootstrap": False,
        "required_store_id": "source-store",
        "required_model_id": "source-model",
    }
    assert setup.factory.call_args.kwargs["model_id"] == "source-model"
    setup.client.close.assert_awaited_once()
    with pytest.raises(PermissionMigrationBlockedError):
        async with instance:
            pytest.fail("reader must not reopen a stale snapshot")


@pytest.mark.parametrize("change", ["store", "model", "checksum"])
async def test_live_pin_mismatch_never_constructs_a_transport(module, setup, change):
    values = {"store_id": "source-store", "model_id": "source-model", "model_checksum": "a" * 64}
    values[{"store": "store_id", "model": "model_id", "checksum": "model_checksum"}[change]] = "bad"
    setup.discovery.return_value = OpenFGARuntimePin(**values)
    with pytest.raises(PermissionMigrationBlockedError):
        async with reader(module, setup):
            pytest.fail("live pin mismatch")
    setup.factory.assert_not_called()


@pytest.mark.parametrize("change", ["catalog_status", "fence", "authorization_status", "authorization_id"])
async def test_invalid_original_sql_pin_is_rejected_before_any_transport(module, setup, change):
    release, auth = setup.catalog.release, setup.catalog.authorization
    if change == "catalog_status":
        release = replace(release, status="RETIRED")
    elif change == "fence":
        release = replace(release, write_fenced=True)
    elif change == "authorization_status":
        auth = replace(auth, status="RETIRED")
    else:
        auth = replace(auth, id=11)
    setup.catalog = replace(setup.catalog, release=release, authorization=auth)
    with pytest.raises(PermissionMigrationBlockedError):
        async with reader(module, setup):
            pytest.fail("invalid source release")
    setup.discovery.assert_not_awaited()
    setup.factory.assert_not_called()


async def test_factory_cannot_repin_the_model_and_its_client_is_closed(module, setup):
    setup.client.model_id = "new-model"
    with pytest.raises(PermissionMigrationBlockedError):
        async with reader(module, setup):
            pytest.fail("factory repin")
    setup.client.close.assert_awaited_once()


@pytest.mark.parametrize("bad", ["llm_model:2", "llm_server:0", "llm_server:01", "llm_server:true", "", None])
async def test_invalid_shared_identity_is_not_a_partial_or_empty_success(module, setup, bad):
    setup.client.stream_list_objects.return_value = ("llm_server:2", bad)
    with pytest.raises(PermissionMigrationBlockedError):
        async with AsyncSession() as session, session.begin(), reader(module, setup) as instance:
            with management_tenant_scope(101):
                await instance.aget_shared_server_ids(session, 101)
    setup.client.close.assert_awaited_once()


async def test_transport_failure_preserves_cause_and_closes(module, setup):
    original = httpx.ReadError("stream interrupted")
    setup.client.stream_list_objects.side_effect = original
    with pytest.raises(PermissionMigrationBlockedError) as failure:
        async with AsyncSession() as session, session.begin(), reader(module, setup) as instance:
            with management_tenant_scope(101):
                await instance.aget_shared_server_ids(session, 101)
    assert failure.value.__cause__ is original
    setup.client.close.assert_awaited_once()


async def test_native_current_tenant_and_open_context_are_mandatory(module, setup):
    instance = reader(module, setup)
    async with AsyncSession() as session, session.begin():
        with management_tenant_scope(101):
            with pytest.raises(PermissionMigrationBlockedError):
                await instance.aget_shared_server_ids(session, 101)
            async with instance:
                for invalid in (True, 0, 202, "101"):
                    with pytest.raises(PermissionMigrationBlockedError):
                        await instance.aget_shared_server_ids(session, invalid)
                with bypass_tenant_filter(), pytest.raises(PermissionMigrationBlockedError):
                    await instance.aget_shared_server_ids(session, 101)
                with pytest.raises(PermissionMigrationBlockedError):
                    await instance.aget_shared_server_ids(object(), 101)
            with pytest.raises(PermissionMigrationBlockedError):
                await instance.aget_shared_server_ids(session, 101)
    setup.client.stream_list_objects.assert_not_awaited()


@pytest.mark.parametrize("malformed_tail", [False, True])
async def test_actual_fga_stream_parser_consumes_2000_or_rejects_the_entire_result(module, setup, malformed_tail):
    requests = []

    def transport(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["authorization_model_id"] == "source-model"
        lines = [json.dumps({"result": {"object": f"llm_server:{number}"}}) for number in range(1, 2001)]
        if malformed_tail:
            lines.append(json.dumps({"error": {"message": "interrupted"}}))
        return httpx.Response(200, text="\n".join(lines) + "\n")

    client = FGAClient("http://offline", "source-store", "source-model")
    await client._http.aclose()
    client._http = httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(transport))
    setup.factory.return_value = client
    async with AsyncSession() as session, session.begin(), reader(module, setup) as instance:
        with management_tenant_scope(101):
            if malformed_tail:
                with pytest.raises(PermissionMigrationBlockedError):
                    await instance.aget_shared_server_ids(session, 101)
            else:
                assert await instance.aget_shared_server_ids(session, 101) == frozenset(range(1, 2001))
    assert len(requests) == 1
    assert requests[0].url.path == "/stores/source-store/streamed-list-objects"
    assert client._http.is_closed
