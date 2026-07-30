"""F048 OpenFGA discovery, startup, and readiness contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.discovery import (
    OpenFGARuntimePin,
    discover_openfga_runtime,
)
from bisheng.core.openfga.manager import FGAManager


class _HeartbeatStore:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict]] = []
        self.removed: list[tuple[str, str]] = []

    async def publish(self, *, role, instance_id, payload) -> None:
        self.published.append((role, instance_id, payload))

    async def remove(self, *, role, instance_id) -> None:
        self.removed.append((role, instance_id))


def _config(**updates) -> OpenFGAConf:
    values = {
        "api_url": "http://openfga:8080",
        "store_name": "bisheng",
        "recent_consistency_window_seconds": 35,
    }
    values.update(updates)
    return OpenFGAConf(**values)


@pytest.mark.asyncio
async def test_discovery_selects_unique_named_store_and_latest_model() -> None:
    model = build_authorization_model_f048()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/stores":
            return httpx.Response(
                200,
                json={
                    "stores": [{"id": "store-live", "name": "bisheng"}],
                },
            )
        if request.url.path == "/stores/store-live/authorization-models":
            return httpx.Response(
                200,
                json={
                    "authorization_models": [
                        {"id": "01-old"},
                        {"id": "02-f048"},
                    ],
                },
            )
        if request.url.path.endswith("/authorization-models/02-f048"):
            return httpx.Response(
                200,
                json={"authorization_model": model},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://openfga:8080",
        transport=httpx.MockTransport(handler),
    ) as client:
        pin = await discover_openfga_runtime(
            _config(),
            expected_model=model,
            allow_bootstrap=False,
            http_client=client,
        )

    assert pin == OpenFGARuntimePin(
        store_id="store-live",
        model_id="02-f048",
        model_checksum=authorization_model_checksum(model),
    )
    assert all(request.startswith("http://openfga:8080/") for request in requests)


@pytest.mark.asyncio
async def test_discovery_fails_closed_for_duplicate_store_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "stores": [
                    {"id": "store-a", "name": "bisheng"},
                    {"id": "store-b", "name": "bisheng"},
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="http://openfga:8080",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            AuthorizationModelMismatchError,
            match="Multiple OpenFGA Stores",
        ):
            await discover_openfga_runtime(
                _config(),
                expected_model=build_authorization_model_f048(),
                allow_bootstrap=False,
                http_client=client,
            )


@pytest.mark.asyncio
async def test_discovery_rejects_latest_model_with_wrong_checksum() -> None:
    wrong_model = {
        "schema_version": "1.1",
        "type_definitions": [{"type": "user", "relations": {}}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stores":
            return httpx.Response(
                200,
                json={"stores": [{"id": "store-live", "name": "bisheng"}]},
            )
        if request.url.path == "/stores/store-live/authorization-models":
            return httpx.Response(
                200,
                json={"authorization_model_ids": ["latest-wrong"]},
            )
        return httpx.Response(
            200,
            json={"authorization_model": wrong_model},
        )

    async with httpx.AsyncClient(
        base_url="http://openfga:8080",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            AuthorizationModelMismatchError,
            match="does not match F048",
        ):
            await discover_openfga_runtime(
                _config(),
                expected_model=build_authorization_model_f048(),
                allow_bootstrap=False,
                http_client=client,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_flags",
    (
        {"force_write_model": True},
        {"dual_model_mode": True},
        {"legacy_model_id": "model-old"},
    ),
)
async def test_production_rejects_bootstrap_dual_and_legacy(
    invalid_flags: dict,
) -> None:
    manager = FGAManager(
        _config(**invalid_flags),
        environment="production",
    )
    with patch(
        "bisheng.core.openfga.manager.discover_openfga_runtime",
        new_callable=AsyncMock,
    ) as discover:
        with pytest.raises(ValueError):
            await manager._async_initialize()
    discover.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_model_client_readiness_and_heartbeat() -> None:
    model = build_authorization_model_f048()
    checksum = authorization_model_checksum(model)
    config = _config()
    heartbeat_store = _HeartbeatStore()
    manager = FGAManager(
        config,
        environment={"name": "production"},
        instance_role="worker",
        heartbeat_store=heartbeat_store,
    )
    pin = OpenFGARuntimePin(
        store_id="store-existing",
        model_id="model-f048",
        model_checksum=checksum,
    )
    fake_client = MagicMock()
    fake_client.store_id = pin.store_id
    fake_client.model_id = pin.model_id
    fake_client.health = AsyncMock(return_value=True)
    fake_client.close = AsyncMock()
    with (
        patch(
            "bisheng.core.openfga.manager.discover_openfga_runtime",
            new=AsyncMock(return_value=pin),
        ) as discover,
        patch(
            "bisheng.core.openfga.manager.FGAClient",
            return_value=fake_client,
        ) as client_class,
    ):
        initialized = await manager._async_initialize()

    assert initialized is fake_client
    discover.assert_awaited_once()
    assert discover.await_args.kwargs["allow_bootstrap"] is False
    client_class.assert_called_once_with(
        api_url="http://openfga:8080",
        store_id="store-existing",
        model_id="model-f048",
        timeout=5,
    )
    readiness = manager.readiness()
    assert readiness["ready"] is True
    assert readiness["store_id"] == "store-existing"
    assert readiness["model_id"] == "model-f048"
    assert readiness["model_checksum"] == checksum
    assert readiness["catalog_release_id"] is None
    assert readiness["catalog_checksum"] is None
    assert readiness["consistency_window_seconds"] == 35
    assert readiness["instance_role"] == "worker"

    manager._instance = fake_client
    assert await manager.heartbeat()
    assert len(heartbeat_store.published) == 1
    _, _, payload = heartbeat_store.published[0]
    assert payload["store_id"] == "store-existing"
    assert payload["model_id"] == "model-f048"


@pytest.mark.asyncio
async def test_runtime_catalog_is_bound_then_refreshed_dynamically() -> None:
    checksum = authorization_model_checksum(build_authorization_model_f048())
    manager = FGAManager(
        _config(),
        environment="production",
        heartbeat_store=_HeartbeatStore(),
    )
    manager._runtime_store_id = "store-existing"
    manager._runtime_model_id = "model-f048"
    manager._runtime_model_checksum = checksum
    manager._instance = SimpleNamespace(health=AsyncMock(return_value=True))
    current = SimpleNamespace(
        release_id=12,
        checksum="c" * 64,
        store_id="store-existing",
        model_id="model-f048",
        model_checksum=checksum,
    )

    async def resolve_catalog():
        return current

    await manager.bind_catalog_runtime(resolve_catalog)
    assert manager.readiness()["catalog_release_id"] == 12

    current = SimpleNamespace(
        release_id=13,
        checksum="d" * 64,
        store_id="store-existing",
        model_id="model-f048",
        model_checksum=checksum,
    )
    assert await manager.heartbeat()
    assert manager.readiness()["catalog_release_id"] == 13
    assert manager.readiness()["catalog_checksum"] == "d" * 64


@pytest.mark.asyncio
async def test_runtime_catalog_binding_rejects_discovered_model_mismatch() -> None:
    checksum = authorization_model_checksum(build_authorization_model_f048())
    manager = FGAManager(_config(), environment="production")
    manager._runtime_store_id = "store-existing"
    manager._runtime_model_id = "model-f048"
    manager._runtime_model_checksum = checksum

    async def wrong_model():
        return SimpleNamespace(
            release_id=12,
            checksum="c" * 64,
            store_id="store-existing",
            model_id="model-other",
            model_checksum=checksum,
        )

    with pytest.raises(
        AuthorizationModelMismatchError,
        match="OpenFGA runtime pin",
    ):
        await manager.bind_catalog_runtime(wrong_model)
