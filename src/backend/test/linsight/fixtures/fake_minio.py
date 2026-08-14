"""In-memory stand-in for ``MinioStorage``, shared by every object-store test.

Lifted out of ``test_workspace_backend.py`` when the skill store moved from local
disk to object storage: both suites now need the same fake, and the skill store
additionally needs ``object_exists_sync`` / ``remove_object_sync``.

Call counters (``get_calls`` / ``put_calls`` / ``exists_calls``) let a test assert
that a local cache hit performs **zero** network round-trips — the property that
makes per-task skill materialization cheap.
"""

from __future__ import annotations

import pytest


class FakeMinioStorage:
    """Minimal in-memory stand-in for ``MinioStorage`` (sync + async surface)."""

    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        # store[(bucket, object_name)] = bytes
        self.store: dict[tuple[str, str], bytes] = {}
        self.minio_client_sync = _FakeRawClient(self.store, self.bucket)
        self.get_calls = 0
        self.put_calls = 0
        self.exists_calls = 0

    # async surface ----------------------------------------------------------
    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        self.put_object_sync(bucket_name=bucket_name, object_name=object_name, file=file, **kwargs)

    async def get_object(self, bucket_name=None, object_name=None):
        return self.get_object_sync(bucket_name=bucket_name, object_name=object_name)

    async def object_exists(self, bucket_name=None, object_name=None):
        return self.object_exists_sync(bucket_name=bucket_name, object_name=object_name)

    async def remove_object(self, bucket_name=None, object_name=None):
        self.remove_object_sync(bucket_name=bucket_name, object_name=object_name)

    # sync surface -----------------------------------------------------------
    def put_object_sync(self, *, bucket_name=None, object_name, file, **kwargs):
        bucket = bucket_name or self.bucket
        data = file if isinstance(file, bytes) else bytes(file)
        self.store[(bucket, object_name)] = data
        self.put_calls += 1

    def get_object_sync(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        self.get_calls += 1
        return self.store.get((bucket, object_name))

    def object_exists_sync(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        self.exists_calls += 1
        return (bucket, object_name) in self.store

    def remove_object_sync(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        self.store.pop((bucket, object_name), None)

    # test helpers -----------------------------------------------------------
    def reset_counters(self) -> None:
        self.get_calls = self.put_calls = self.exists_calls = 0

    def keys(self, prefix: str = "") -> list[str]:
        """Object names in the formal bucket, optionally filtered by prefix."""
        return sorted(name for (bucket, name) in self.store if bucket == self.bucket and name.startswith(prefix))


class _FakeRawClient:
    """Stands in for ``minio.Minio`` (only ``list_objects`` is used)."""

    def __init__(self, store: dict[tuple[str, str], bytes], bucket: str) -> None:
        self._store = store
        self._bucket = bucket

    def list_objects(self, bucket_name, prefix="", recursive=True):
        for (bucket, name), data in sorted(self._store.items()):
            if bucket != bucket_name:
                continue
            if prefix and not name.startswith(prefix):
                continue
            yield _FakeObject(name, len(data))


class _FakeObject:
    def __init__(self, object_name: str, size: int) -> None:
        self.object_name = object_name
        self.size = size
        self.is_dir = False
        self.last_modified = None
        self.etag = "abc"


@pytest.fixture()
def fake_minio():
    return FakeMinioStorage()
