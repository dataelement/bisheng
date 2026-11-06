"""F086 content confirmation is a durable barrier before SQLite DDL."""

import hashlib

import pytest

from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


class MemoryObjects:
    def __init__(self):
        self.data = {}

    async def put(self, key, path, content_type="application/octet-stream"):
        self.data[key] = path.read_bytes()

    async def iter_content(self, key):
        yield self.data[key]


async def chunks(data):
    yield data


async def test_upload_requires_content_and_metadata_confirmation(runtime_repo):
    """AC-05, AC-42, AC-43: incomplete uploads never become restoreable."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService

    service = RuntimeArtifactService(runtime_repo, MemoryObjects())
    op = await runtime_repo.create_operation(operation())
    body = b"consistent-snapshot"
    session = await service.create_upload(
        op.id, kind="snapshot", sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body)
    )
    with pytest.raises(RuntimeConflict, match="incomplete"):
        await service.finalize(session["transfer_id"], session["ticket"])
    await service.append(session["transfer_id"], session["ticket"], 0, chunks(body))
    confirmed = await service.finalize(session["transfer_id"], session["ticket"])
    assert confirmed["state"] == "verified"
    assert confirmed["confirmed_at"]
    assert (await service.finalize(session["transfer_id"], session["ticket"]))["artifact_id"] == confirmed[
        "artifact_id"
    ]


async def test_hash_and_ticket_scope_rejected(runtime_repo):
    """AC-06, AC-07: wrong content or another transfer ticket cannot publish data."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService

    service = RuntimeArtifactService(runtime_repo, MemoryObjects())
    op = await runtime_repo.create_operation(operation())
    session = await service.create_upload(op.id, kind="dependencies", sha256="a" * 64, size_bytes=3)
    with pytest.raises(RuntimeConflict, match="ticket"):
        await service.append(session["transfer_id"], "wrong-ticket", 0, chunks(b"bad"))
    await service.append(session["transfer_id"], session["ticket"], 0, chunks(b"bad"))
    with pytest.raises(RuntimeConflict, match="digest"):
        await service.finalize(session["transfer_id"], session["ticket"])


async def test_chunk_response_loss_is_idempotent(runtime_repo):
    """AC-36: resending one confirmed chunk does not duplicate snapshot bytes."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_artifact_service import RuntimeArtifactService

    service = RuntimeArtifactService(runtime_repo, MemoryObjects())
    op = await runtime_repo.create_operation(operation())
    body = b"abcdef"
    session = await service.create_upload(op.id, kind="snapshot", sha256=hashlib.sha256(body).hexdigest(), size_bytes=6)
    for _ in range(2):
        assert (await service.append(session["transfer_id"], session["ticket"], 0, chunks(b"abc")))["offset"] == 3
    with pytest.raises(RuntimeConflict, match="chunk"):
        await service.append(session["transfer_id"], session["ticket"], 0, chunks(b"def"))
    await service.append(session["transfer_id"], session["ticket"], 3, chunks(b"def"))
    assert (await service.finalize(session["transfer_id"], session["ticket"]))["state"] == "verified"


async def test_delete_removes_snapshot_transfer_replicas_only_for_target_app(runtime_repo):
    """AC-10: deleting a registered snapshot also removes its upload chunk copies."""
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeTransfer
    from bisheng.app_runtime.domain.services.runtime_cleanup_service import RuntimeCleanupService
    from test.app_runtime.test_runtime_storage_api import StorageObjects

    op = operation("delete", "app-a")
    op.kind = "destroy"
    op.payload = {"purge_volume": True}
    op = await runtime_repo.create_operation(op)
    artifact = await runtime_repo.save(
        RuntimeArtifact(
            tenant_id=1,
            app_id="app-a",
            scope_key="1/app-a",
            kind="snapshot",
            sha256="b" * 64,
            object_key="tenants/1/apps/app-a/snapshots/one.sqlite",
            state="verified",
        )
    )
    transfer = await runtime_repo.save(
        RuntimeTransfer(
            tenant_id=1,
            app_id="app-a",
            operation_id=op.id,
            artifact_id=artifact.id,
            action="upload",
            node_id="node-a",
            ticket_hash="h",
            expires_at=op.deadline,
            state="confirmed",
        )
    )
    objects = StorageObjects()
    objects.data = {
        artifact.object_key: b"snapshot",
        f"transfers/{transfer.id}/0-content": b"snapshot",
        "transfers/other-app/0-content": b"other",
    }
    await RuntimeCleanupService(runtime_repo, objects).cleanup(op)
    assert objects.data == {"transfers/other-app/0-content": b"other"}
    assert (await runtime_repo.get(RuntimeArtifact, artifact.id)).state == "purged"
