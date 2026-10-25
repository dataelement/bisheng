"""AEAD-encrypted shared objects, bounded reads, and read-back integrity checks."""

import asyncio
import hmac
import io
import os
from dataclasses import dataclass
from hashlib import sha256

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking
from bisheng.dsh.infrastructure.model_audit_codec import AuditScope
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing


@dataclass(frozen=True, slots=True)
class StoredAuditBlock:
    object_key: str
    key_version: str
    digest: str
    byte_length: int
    scope_key: str
    encoding_version: int


class EncryptedAuditStorage:
    def __init__(self, objects, keys: AuditKeyRing, *, max_block_bytes=16384, timeout_seconds=5.0):
        self.objects, self.keys = objects, keys
        self.max_block_bytes, self.timeout_seconds = max_block_bytes, timeout_seconds

    @staticmethod
    def _digest(key: bytes, scope: AuditScope, body: bytes) -> str:
        scoped_key = hmac.digest(key, b"dsh-audit-digest-v1" + scope.associated_data, "sha256")
        return hmac.new(scoped_key, body, "sha256").hexdigest()

    @staticmethod
    def _name(scope: AuditScope, key_id: str, digest: str) -> str:
        # Private namespace deliberately cannot match F017's root-sharing fallback.
        key_path = sha256(key_id.encode()).hexdigest()
        return f"dsh/model-audit/{scope.tenant_id}/{scope.key}/{key_path}/{digest}"

    async def put_verified_block(self, scope: AuditScope, body: bytes, *, key_version=None) -> StoredAuditBlock:
        if len(body) > self.max_block_bytes:
            raise ValueError("Audit body block exceeds budget")
        key_id = key_version if key_version is not None else self.keys.active_id
        key = self.keys.resolve(key_id)
        digest = self._digest(key, scope, body)
        name = self._name(scope, key_id, digest)
        nonce = os.urandom(12)
        aad = scope.associated_data + digest.encode()
        cipher = b"DMA1" + nonce + AESGCM(key).encrypt(nonce, body, aad)
        reference = StoredAuditBlock(name, key_id, digest, len(body), scope.key, scope.encoding_version)
        async with asyncio.timeout(self.timeout_seconds):
            await self.objects.put(name, cipher)
        verified = await self.open_verified_block(scope, reference)
        if not hmac.compare_digest(verified, body):
            raise ValueError("Audit object read-back mismatch")
        return reference

    async def open_verified_block(self, scope: AuditScope, reference: StoredAuditBlock) -> bytes:
        if (reference.scope_key, reference.encoding_version) != (scope.key, scope.encoding_version):
            raise ValueError("Audit object scope mismatch")
        if reference.object_key != self._name(scope, reference.key_version, reference.digest):
            raise ValueError("Audit object path mismatch")
        # Encoding-v1's read ceiling must not shrink when operators tune new-write chunks.
        if not 0 <= reference.byte_length <= 65536:
            raise ValueError("Audit object length invalid")
        key = self.keys.resolve(reference.key_version)
        async with asyncio.timeout(self.timeout_seconds):
            cipher = await self.objects.get_bounded(reference.object_key, reference.byte_length + 32)
        if len(cipher) != reference.byte_length + 32 or cipher[:4] != b"DMA1":
            raise ValueError("Audit object envelope invalid")
        try:
            body = AESGCM(key).decrypt(cipher[4:16], cipher[16:], scope.associated_data + reference.digest.encode())
        except InvalidTag:
            raise ValueError("Audit object integrity failed") from None
        if self._digest(key, scope, body) != reference.digest:
            raise ValueError("Audit object digest mismatch")
        return body


class BishengMinioAuditObjects:
    """No root-sharing fallback, public URLs, or local-disk original bodies."""

    async def put(self, key, value):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        storage = await get_minio_storage()

        def write():
            storage.minio_client_sync.put_object(
                storage.bucket, key, io.BytesIO(value), len(value), content_type="application/octet-stream"
            )

        await run_audit_blocking(write)

    async def get_bounded(self, key, maximum):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage

        storage = await get_minio_storage()

        def read():
            response = storage.minio_client_sync.get_object(storage.bucket, key)
            try:
                body = response.read(maximum + 1)
                if len(body) > maximum:
                    raise ValueError("Audit object exceeds read budget")
                return body
            finally:
                response.close()
                response.release_conn()

        return await run_audit_blocking(read)
