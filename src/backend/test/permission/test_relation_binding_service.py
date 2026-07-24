from __future__ import annotations

import asyncio

import pytest

from bisheng.permission.domain.services.permission_relation_binding_service import (
    PermissionRelationBindingService,
)


@pytest.mark.asyncio
async def test_concurrent_mutations_reread_inside_lock_without_lost_updates():
    stored: list[dict] = []
    lock = asyncio.Lock()

    async def load() -> list[dict]:
        await asyncio.sleep(0)
        return [dict(item) for item in stored]

    async def save(bindings: list[dict]) -> None:
        await asyncio.sleep(0)
        stored[:] = [dict(item) for item in bindings]

    service = PermissionRelationBindingService(
        load_callback=load,
        save_callback=save,
        lock_factory=lambda: lock,
    )

    await asyncio.gather(
        service.upsert_bindings([{"key": "a", "model_id": "viewer"}]),
        service.upsert_bindings([{"key": "b", "model_id": "editor"}]),
        service.upsert_bindings([{"key": "c", "model_id": "manager"}]),
    )

    assert {item["key"] for item in stored} == {"a", "b", "c"}

    await asyncio.gather(
        service.remove_binding_if_matches("a", model_id="viewer"),
        service.upsert_bindings([{"key": "b", "model_id": "manager"}]),
    )

    assert stored == [
        {"key": "b", "model_id": "manager"},
        {"key": "c", "model_id": "manager"},
    ]


@pytest.mark.asyncio
async def test_remove_binding_preserves_concurrent_model_rebind():
    stored = [{"key": "same", "model_id": "new-model"}]
    lock = asyncio.Lock()

    async def load() -> list[dict]:
        return [dict(item) for item in stored]

    async def save(bindings: list[dict]) -> None:
        stored[:] = [dict(item) for item in bindings]

    service = PermissionRelationBindingService(
        load_callback=load,
        save_callback=save,
        lock_factory=lambda: lock,
    )

    removed = await service.remove_binding_if_matches("same", model_id="old-model")

    assert removed is False
    assert stored == [{"key": "same", "model_id": "new-model"}]
