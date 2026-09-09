"""Bounded reads of immutable MinIO evidence versions; never arbitrary URLs."""

import asyncio
from typing import Protocol


class EvidenceStore(Protocol):
    async def read(self, reference: str, tenant_id: int) -> bytes: ...


class MinioEvidenceStore:
    def __init__(self, client, *, bucket: str, max_bytes: int = 1024 * 1024):
        if not bucket or not 1 <= max_bytes <= 4 * 1024 * 1024:
            raise ValueError("Evidence requires a configured bucket and bounded size")
        self.client, self.bucket, self.max_bytes = client, bucket, max_bytes

    async def read(self, reference: str, tenant_id: int) -> bytes:
        return await asyncio.to_thread(self._read, reference, tenant_id)

    def _read(self, reference: str, tenant_id: int) -> bytes:
        key, separator, version = reference.rpartition("@")
        if (
            not separator
            or not version
            or version == "null"
            or not key.startswith(f"dsh/reconciliation/{tenant_id}/")
            or ".." in key.split("/")
            or "://" in reference
        ):
            raise ValueError("Evidence must name an immutable tenant-scoped MinIO object version")
        metadata = self.client.stat_object(self.bucket, key, version_id=version)
        if metadata.version_id != version or metadata.size > self.max_bytes:
            raise ValueError("Evidence version or size is invalid")
        response = self.client.get_object(self.bucket, key, version_id=version)
        try:
            content = response.read(self.max_bytes + 1)
            if len(content) > self.max_bytes:
                raise ValueError("Evidence exceeds the configured limit")
            return content
        finally:
            response.close()
            response.release_conn()
