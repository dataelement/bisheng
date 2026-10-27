"""SDK-compatible object behavior without anonymous MinIO URLs or admin tokens."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from test.app_runtime.test_runtime_artifacts import MemoryObjects
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


class StorageObjects(MemoryObjects):
    async def stat(self, key):
        if key not in self.data:
            return None
        return {
            "key": key,
            "size": len(self.data[key]),
            "etag": "fixture",
            "content_type": "application/octet-stream",
            "last_modified": datetime.utcnow().isoformat(),
        }

    async def list(self, prefix, *, start_after="", limit=1000):
        return [await self.stat(key) for key in sorted(self.data) if key.startswith(prefix) and key > start_after][
            :limit
        ]

    async def delete(self, key):
        del self.data[key]


@pytest.fixture
async def storage_api(runtime_repo, monkeypatch):
    from bisheng.app_runtime.api.endpoints import app_storage as api
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute, RuntimeStorageBinding
    from bisheng.app_runtime.domain.services.app_storage_service import AppStorageService

    svc = AppStorageService(runtime_repo, StorageObjects(), max_file_bytes=8)
    op = operation()
    op.version_id = "version-a"
    op = await runtime_repo.create_operation(op)
    issued = await svc.issue(op, base_url="http://platform")
    row = await runtime_repo.get(RuntimeStorageBinding, issued["binding_id"])
    row.state = "active"
    await runtime_repo.save(row)
    await runtime_repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id="app-a",
            route_key="app:app-a",
            operation_id=op.id,
            version_id="version-a",
            node_id="node-a",
            exec_ref="container",
            generation=1,
            owner_epoch=1,
            status="serving",
        )
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.service] = lambda: svc
    monkeypatch.setattr(api, "settings", SimpleNamespace(app_runtime=SimpleNamespace(enabled=True)))
    headers = {"Authorization": "Bearer " + issued["env"]["BISHENG_APP_STORAGE_TOKEN"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://platform", headers=headers
    ) as client:
        yield client, svc, runtime_repo


async def test_attachment_roundtrip_and_pagination(storage_api):
    """AC-05, AC-08: existing SDK JSON/raw-byte/relative-key contracts stay intact."""
    client, _, _ = storage_api
    base = "/api/v1/apps/app-a/storage"
    for key in ["a.txt", "b.txt"]:
        response = await client.put(base + "/objects/" + key, content=b"data")
        assert response.status_code == 200 and response.json()["key"] == key
    assert (await client.get(base + "/objects/a.txt")).content == b"data"
    page = (await client.get(base + "/objects?limit=1")).json()
    assert page["next_cursor"] == "a.txt" and page["objects"][0]["size"] == 4
    assert (await client.delete(base + "/objects/a.txt")).json() == {}
    assert (await client.get(base + "/objects/a.txt")).status_code == 404


async def test_scope_size_and_revocation(storage_api):
    """AC-08, AC-38, AC-39: foreign apps and old serving epochs cannot use a handle."""
    client, _, repo = storage_api
    assert (await client.get("/api/v1/apps/app-b/storage/objects")).status_code == 401
    over = await client.put("/api/v1/apps/app-a/storage/objects/big", content=b"123456789")
    assert over.status_code == 413 and over.json()["detail"]["code"] == "payload_too_large"
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

    row = (await repo.find(RuntimeRoute, route_key="app:app-a"))[0]
    row.status = "maintenance"
    await repo.save(row)
    assert (await client.get("/api/v1/apps/app-a/storage/objects")).status_code == 401


async def test_preview_namespace_cannot_read_production(storage_api):
    """AC-09: preview storage has its own prefix and lifetime."""
    client, svc, repo = storage_api
    assert (await client.put("/api/v1/apps/app-a/storage/objects/prod", content=b"prod")).status_code == 200
    op = operation("preview-op")
    op.kind = "preview"
    op.version_id = "version-a"
    op.deadline = datetime.utcnow() + timedelta(minutes=5)
    op = await repo.create_operation(op)
    preview = await svc.issue(op, base_url="http://platform", preview_session="session-a")
    response = await client.get(
        "/api/v1/apps/app-a/storage/objects",
        headers={"Authorization": "Bearer " + preview["env"]["BISHENG_APP_STORAGE_TOKEN"]},
    )
    assert response.status_code == 200 and response.json()["objects"] == []
