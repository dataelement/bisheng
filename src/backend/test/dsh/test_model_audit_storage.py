"""覆盖 AC: AC-06, AC-10, AC-14, AC-17, AC-20, AC-26."""

from dataclasses import replace

import pytest

from bisheng.dsh.infrastructure.model_audit_codec import AuditScope
from bisheng.dsh.infrastructure.model_audit_keys import AuditKeyRing
from bisheng.dsh.infrastructure.model_audit_storage import EncryptedAuditStorage


class MemoryObjects:
    def __init__(self):
        self.data = {}

    async def put(self, key, value):
        self.data[key] = value

    async def get_bounded(self, key, maximum):
        value = self.data[key]
        if len(value) > maximum:
            raise ValueError("oversized object")
        return value


async def test_ciphertext_scope_bound_cross_node_read_and_reuse():
    objects = MemoryObjects()
    keys = AuditKeyRing({"v1": bytes(range(32))}, active_id="v1")
    writer = EncryptedAuditStorage(objects, keys, max_block_bytes=1024)
    scope = AuditScope(2, 20, "CONVERSATION", "session")
    body = b"synthetic plaintext"
    reference = await writer.put_verified_block(scope, body)
    assert body not in objects.data[reference.object_key]
    reader = EncryptedAuditStorage(objects, keys, max_block_bytes=1024)
    assert await reader.open_verified_block(scope, reference) == body
    with pytest.raises(ValueError):
        await reader.open_verified_block(scope, replace(reference, object_key="another-object"))
    assert (await writer.put_verified_block(scope, body)).object_key == reference.object_key
    rotated = AuditKeyRing({"v1": bytes(range(32)), "v2": bytes(reversed(range(32)))}, active_id="v2")
    rotating = EncryptedAuditStorage(objects, rotated, max_block_bytes=1024)
    assert await rotating.open_verified_block(scope, reference) == body
    assert (await rotating.put_verified_block(scope, body)).object_key != reference.object_key
    with pytest.raises(ValueError):
        await reader.open_verified_block(AuditScope(2, 21, "CONVERSATION", "session"), reference)
    wrong = AuditKeyRing({"v1": bytes(reversed(range(32)))}, active_id="v1")
    with pytest.raises(ValueError):
        await EncryptedAuditStorage(objects, wrong, max_block_bytes=1024).open_verified_block(scope, reference)


async def test_absent_key_oversize_corrupt_object_and_store_timeout():
    objects = MemoryObjects()
    scope = AuditScope(2, 20, "REQUEST", "request")
    missing = EncryptedAuditStorage(objects, AuditKeyRing({}, active_id=None), max_block_bytes=1024)
    with pytest.raises(ValueError):
        await missing.put_verified_block(scope, b"synthetic")
    assert objects.data == {}
    keys = AuditKeyRing({"v1": bytes(range(32))}, active_id="v1")
    storage = EncryptedAuditStorage(objects, keys, max_block_bytes=1024, timeout_seconds=0.01)
    with pytest.raises(ValueError):
        await storage.put_verified_block(scope, b"x" * 1025)
    ref = await storage.put_verified_block(scope, b"synthetic")
    objects.data[ref.object_key] += b"corrupt"
    with pytest.raises(ValueError):
        await storage.open_verified_block(scope, ref)

    async def stall(key, value):
        import asyncio

        await asyncio.sleep(1)

    objects.put = stall
    with pytest.raises(TimeoutError):
        await storage.put_verified_block(scope, b"synthetic")


async def test_reducing_new_write_chunk_size_keeps_historical_blocks_readable():
    objects = MemoryObjects()
    keys = AuditKeyRing({"v1": bytes(range(32))}, active_id="v1")
    scope = AuditScope(2, 20, "REQUEST", "old-request")
    old = EncryptedAuditStorage(objects, keys, max_block_bytes=16384)
    reference = await old.put_verified_block(scope, b"x" * 8192)
    reduced = EncryptedAuditStorage(objects, keys, max_block_bytes=1024)
    assert await reduced.open_verified_block(scope, reference) == b"x" * 8192
    with pytest.raises(ValueError):
        await reduced.open_verified_block(scope, replace(reference, byte_length=65537))
