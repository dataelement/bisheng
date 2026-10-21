"""Scoped storage cleanup after confirmed execution teardown; never deletes another app."""

from datetime import datetime

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeStorageBinding, RuntimeTransfer
from bisheng.app_runtime.domain.repositories.runtime_object_store import RuntimeObjectStore


class RuntimeCleanupService:
    def __init__(self, repository, objects=None):
        self.repo = repository
        self.objects = objects or RuntimeObjectStore()

    async def prefix(self, prefix):
        while True:
            rows = await self.objects.list(prefix, limit=1000)
            if not rows:
                return
            for row in rows:
                if not row["key"].startswith(prefix):
                    raise ValueError("storage cleanup scope mismatch")
                await self.objects.delete(row["key"])

    async def cleanup(self, op):
        if op.kind not in {"preview", "destroy"}:
            return
        bindings = await self.repo.find(RuntimeStorageBinding, app_id=op.app_id)
        for row in bindings:
            if op.kind == "preview" and row.operation_id != op.id:
                continue
            expected = f"tenants/{op.tenant_id}/apps/{op.app_id}/"
            if not (row.object_prefix.startswith(expected) or row.object_prefix == f"apps/{op.app_id}/attachments/"):
                raise ValueError("storage binding scope mismatch")
            row.state = "revoked"
            await self.repo.save(row)
            await self.prefix(row.object_prefix)
        if op.kind == "destroy" and op.payload.get("purge_volume"):
            for artifact in await self.repo.find(RuntimeArtifact, app_id=op.app_id, kind="snapshot"):
                if artifact.tenant_id != op.tenant_id:
                    raise ValueError("snapshot cleanup scope mismatch")
                transfers = await self.repo.find(RuntimeTransfer, artifact_id=artifact.id, action="upload")
                for transfer in transfers:
                    if (transfer.tenant_id, transfer.app_id) != (op.tenant_id, op.app_id):
                        raise ValueError("snapshot transfer scope mismatch")
                await self.objects.delete(artifact.object_key)
                for transfer in transfers:
                    await self.prefix(f"transfers/{transfer.id}/")
                    transfer.state = "purged"
                    await self.repo.save(transfer)
                artifact.state = "purged"
                artifact.retained_until = datetime.utcnow()
                await self.repo.save(artifact)
