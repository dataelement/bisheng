"""F048 single-model manager startup and readiness contracts.

覆盖 AC: AC-16, AC-34, AC-99, AC-100, AC-102, AC-108, AC-110,
AC-113, AC-115, AC-116
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
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


def _pinned_config(**updates) -> OpenFGAConf:
    model = build_authorization_model_f048()
    values = {
        "api_url": "http://openfga:8080",
        "store_id": "store-existing",
        "model_id": "model-f048",
        "model_checksum": authorization_model_checksum(model),
        "current_catalog_release_id": 12,
        "current_catalog_checksum": "c" * 64,
        "recent_consistency_window_seconds": 35,
    }
    values.update(updates)
    return OpenFGAConf(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_field",
    (
        "store_id",
        "model_id",
        "model_checksum",
        "current_catalog_release_id",
        "current_catalog_checksum",
    ),
)
async def test_production_rejects_incomplete_runtime_pin(
    missing_field: str,
) -> None:
    config = _pinned_config(**{missing_field: None})
    manager = FGAManager(config, environment="production")
    manager._fetch_authorization_model = AsyncMock()
    with pytest.raises(ValueError):
        await manager._async_initialize()
    manager._fetch_authorization_model.assert_not_awaited()


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
        _pinned_config(**invalid_flags),
        environment="production",
    )
    manager._fetch_authorization_model = AsyncMock()
    with pytest.raises(ValueError):
        await manager._async_initialize()
    manager._fetch_authorization_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_production_validates_remote_model_checksum() -> None:
    manager = FGAManager(_pinned_config(), environment="production")
    manager._fetch_authorization_model = AsyncMock(return_value={"schema_version": "1.1", "type_definitions": []})
    with pytest.raises(AuthorizationModelMismatchError):
        await manager._async_initialize()


@pytest.mark.asyncio
async def test_single_model_client_readiness_and_heartbeat() -> None:
    model = build_authorization_model_f048()
    config = _pinned_config()
    heartbeat_store = _HeartbeatStore()
    manager = FGAManager(
        config,
        environment={"name": "production"},
        instance_role="worker",
        heartbeat_store=heartbeat_store,
    )
    manager._fetch_authorization_model = AsyncMock(return_value=model)

    fake_client = MagicMock()
    fake_client.store_id = "store-existing"
    fake_client.model_id = "model-f048"
    fake_client.health = AsyncMock(return_value=True)
    fake_client.close = AsyncMock()
    with patch(
        "bisheng.core.openfga.manager.FGAClient",
        return_value=fake_client,
    ) as client_class:
        initialized = await manager._async_initialize()

    assert initialized is fake_client
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
    assert readiness["model_checksum"] == config.model_checksum
    assert readiness["catalog_release_id"] == 12
    assert readiness["catalog_checksum"] == "c" * 64
    assert readiness["consistency_window_seconds"] == 35
    assert readiness["instance_role"] == "worker"
    assert readiness["instance_id"]

    manager._instance = fake_client
    assert await manager.heartbeat()
    after_heartbeat = manager.readiness()
    assert after_heartbeat["last_heartbeat_at"] is not None
    assert after_heartbeat["ready"] is True
    assert len(heartbeat_store.published) == 1
    role, instance_id, payload = heartbeat_store.published[0]
    assert role == "worker"
    assert instance_id == readiness["instance_id"]
    assert payload == {
        "ready": True,
        "store_id": "store-existing",
        "model_id": "model-f048",
        "model_checksum": config.model_checksum,
        "catalog_release_id": 12,
        "catalog_checksum": "c" * 64,
        "dual_model_mode": False,
        "legacy_model_id": None,
    }


@pytest.mark.asyncio
async def test_runtime_catalog_pin_is_bound_once_then_refreshed_dynamically() -> None:
    config = _pinned_config()
    heartbeat_store = _HeartbeatStore()
    manager = FGAManager(
        config,
        environment="production",
        heartbeat_store=heartbeat_store,
    )
    manager._runtime_store_id = "store-existing"
    manager._runtime_model_id = "model-f048"
    manager._runtime_model_checksum = config.model_checksum
    manager._instance = SimpleNamespace(
        health=AsyncMock(return_value=True),
    )
    current = SimpleNamespace(
        release_id=12,
        checksum="c" * 64,
        store_id="store-existing",
        model_id="model-f048",
        model_checksum=config.model_checksum,
    )

    async def resolve_catalog():
        return current

    await manager.bind_catalog_runtime(
        resolve_catalog,
        require_config_match=True,
    )
    assert manager.readiness()["catalog_release_id"] == 12

    current = SimpleNamespace(
        release_id=13,
        checksum="d" * 64,
        store_id="store-existing",
        model_id="model-f048",
        model_checksum=config.model_checksum,
    )
    assert await manager.heartbeat()
    assert manager.readiness()["catalog_release_id"] == 13
    assert manager.readiness()["catalog_checksum"] == "d" * 64


@pytest.mark.asyncio
async def test_runtime_catalog_binding_rejects_startup_or_model_mismatch() -> None:
    config = _pinned_config()
    manager = FGAManager(config, environment="production")
    manager._runtime_store_id = "store-existing"
    manager._runtime_model_id = "model-f048"
    manager._runtime_model_checksum = config.model_checksum

    async def stale_catalog():
        return SimpleNamespace(
            release_id=13,
            checksum="d" * 64,
            store_id="store-existing",
            model_id="model-f048",
            model_checksum=config.model_checksum,
        )

    with pytest.raises(
        AuthorizationModelMismatchError,
        match="startup configuration",
    ):
        await manager.bind_catalog_runtime(
            stale_catalog,
            require_config_match=True,
        )

    async def wrong_model():
        return SimpleNamespace(
            release_id=12,
            checksum="c" * 64,
            store_id="store-existing",
            model_id="model-other",
            model_checksum=config.model_checksum,
        )

    with pytest.raises(
        AuthorizationModelMismatchError,
        match="OpenFGA runtime pin",
    ):
        await manager.bind_catalog_runtime(wrong_model)
