"""TC-1: Unit tests for the real ``WorkspaceBackend`` (F035 Track C, Wave 2).

The backend's truth source is MinIO (``workspace/{svid}/``) with a local
write-through cache. These tests mock ``get_minio_storage()`` so no real MinIO
is required: a tiny in-memory ``FakeMinioStorage`` stands in for the object
store and lets us assert both cache and write-through behavior.

Coverage:
  1. write -> cache + write-through to MinIO
  2. read cache-hit / cache-miss lazy load from MinIO
  3. ls authoritative from MinIO (not cache)
  4. edit on cache then write-through
  5. multi-tenant isolation (two svids never cross)
  6. ``..`` traversal raises ValueError
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bisheng.linsight.domain.services.workspace_backend import (
    WORKSPACE_PREFIX,
    WorkspaceBackend,
)


# ---------------------------------------------------------------------------
# Fake MinIO: in-memory object store keyed by (bucket, object_name)
# ---------------------------------------------------------------------------
class FakeMinioStorage:
    """Minimal in-memory stand-in for ``MinioStorage`` (sync + async surface)."""

    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        # store[(bucket, object_name)] = bytes
        self.store: dict[tuple[str, str], bytes] = {}
        self.minio_client_sync = _FakeRawClient(self.store, self.bucket)

    # async surface used by WorkspaceBackend's a* methods --------------------
    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        bucket = bucket_name or self.bucket
        data = file if isinstance(file, bytes) else bytes(file)
        self.store[(bucket, object_name)] = data

    async def get_object(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        return self.store.get((bucket, object_name))

    # sync surface ----------------------------------------------------------
    def put_object_sync(self, *, bucket_name=None, object_name, file, **kwargs):
        bucket = bucket_name or self.bucket
        data = file if isinstance(file, bytes) else bytes(file)
        self.store[(bucket, object_name)] = data

    def get_object_sync(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        return self.store.get((bucket, object_name))

    async def object_exists(self, bucket_name=None, object_name=None):
        bucket = bucket_name or self.bucket
        return (bucket, object_name) in self.store


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def fake_minio():
    return FakeMinioStorage()


@pytest.fixture()
def file_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_backend(svid, minio, file_dir):
    return WorkspaceBackend(svid=svid, minio=minio, file_dir=file_dir)


# ---------------------------------------------------------------------------
# 1. write -> cache + write-through to MinIO
# ---------------------------------------------------------------------------
def test_write_caches_and_writes_through(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    res = be.write("/output/report.md", "hello world")
    assert res.error is None

    # write-through: object landed in MinIO under workspace/{svid}/
    key = f"{WORKSPACE_PREFIX}/sv1/output/report.md"
    assert (fake_minio.bucket, key) in fake_minio.store
    assert fake_minio.store[(fake_minio.bucket, key)] == b"hello world"

    # cache: local file_dir holds a copy
    cached = Path(file_dir) / "output" / "report.md"
    assert cached.exists()
    assert cached.read_bytes() == b"hello world"


# ---------------------------------------------------------------------------
# 2a. read cache-hit
# ---------------------------------------------------------------------------
def test_read_cache_hit(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    be.write("/scratch/a.txt", "line1\nline2\nline3")
    res = be.read("/scratch/a.txt")
    assert res.error is None
    assert "line1" in res.file_data["content"]
    assert "line3" in res.file_data["content"]


# 2b. read cache-miss -> lazy load from MinIO
def test_read_cache_miss_lazy_load(fake_minio, file_dir):
    # seed MinIO directly, bypassing the backend cache
    key = f"{WORKSPACE_PREFIX}/sv1/uploads/doc/index.md"
    fake_minio.store[(fake_minio.bucket, key)] = b"alpha\nbeta\ngamma"

    be = make_backend("sv1", fake_minio, file_dir)
    # not in cache yet
    assert not (Path(file_dir) / "uploads" / "doc" / "index.md").exists()

    res = be.read("/uploads/doc/index.md")
    assert res.error is None
    assert "beta" in res.file_data["content"]
    # lazy load materialized the cache
    assert (Path(file_dir) / "uploads" / "doc" / "index.md").exists()


def test_read_offset_limit(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    be.write("/scratch/big.txt", "\n".join(f"line{i}" for i in range(10)))
    res = be.read("/scratch/big.txt", offset=2, limit=3)
    assert res.error is None
    content = res.file_data["content"]
    assert "line2" in content
    assert "line4" in content
    assert "line0" not in content
    assert "line5" not in content


def test_read_missing_returns_error(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    res = be.read("/scratch/nope.txt")
    assert res.error is not None


# ---------------------------------------------------------------------------
# 3. ls authoritative from MinIO
# ---------------------------------------------------------------------------
def test_ls_authoritative_from_minio(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    be.write("/output/a.md", "a")
    be.write("/output/b.md", "b")
    be.write("/scratch/c.md", "c")

    res = be.ls("/output")
    assert res.error is None
    paths = {e["path"] for e in res.entries}
    assert any(p.endswith("output/a.md") for p in paths)
    assert any(p.endswith("output/b.md") for p in paths)
    assert not any(p.endswith("scratch/c.md") for p in paths)


def test_ls_reflects_minio_not_just_cache(fake_minio, file_dir):
    # object exists only in MinIO (not written via backend cache)
    key = f"{WORKSPACE_PREFIX}/sv1/output/remote.md"
    fake_minio.store[(fake_minio.bucket, key)] = b"remote"

    be = make_backend("sv1", fake_minio, file_dir)
    res = be.ls("/output")
    assert res.error is None
    assert any(e["path"].endswith("output/remote.md") for e in res.entries)


# ---------------------------------------------------------------------------
# 4. edit on cache then write-through
# ---------------------------------------------------------------------------
def test_edit_writes_through(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    be.write("/scratch/e.txt", "foo bar baz")
    res = be.edit("/scratch/e.txt", "bar", "qux")
    assert res.error is None

    key = f"{WORKSPACE_PREFIX}/sv1/scratch/e.txt"
    assert fake_minio.store[(fake_minio.bucket, key)] == b"foo qux baz"
    # cache updated too
    cached = Path(file_dir) / "scratch" / "e.txt"
    assert cached.read_bytes() == b"foo qux baz"


def test_edit_replace_all(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    be.write("/scratch/e.txt", "x x x")
    res = be.edit("/scratch/e.txt", "x", "y", replace_all=True)
    assert res.error is None
    key = f"{WORKSPACE_PREFIX}/sv1/scratch/e.txt"
    assert fake_minio.store[(fake_minio.bucket, key)] == b"y y y"


# ---------------------------------------------------------------------------
# 5. multi-tenant isolation
# ---------------------------------------------------------------------------
def test_multi_tenant_isolation(fake_minio):
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        be1 = make_backend("svA", fake_minio, d1)
        be2 = make_backend("svB", fake_minio, d2)

        be1.write("/output/shared.md", "from A")
        be2.write("/output/shared.md", "from B")

        # each reads its own
        assert "from A" in be1.read("/output/shared.md").file_data["content"]
        assert "from B" in be2.read("/output/shared.md").file_data["content"]

        # ls does not leak across svid. Paths are workspace-relative (the
        # ``workspace/{svid}/`` object-key prefix is stripped so the agent can
        # read them back without double-prefixing), so isolation is verified by
        # scope: svA's ls must surface its own file but never an svB-only file.
        be2.write("/output/only_b.md", "B only")
        a_paths = {e["path"] for e in be1.ls("/output").entries}
        assert any("shared.md" in p for p in a_paths)
        assert not any("only_b.md" in p for p in a_paths)


# ---------------------------------------------------------------------------
# 6. path traversal rejected
# ---------------------------------------------------------------------------
def test_traversal_rejected_on_write(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    with pytest.raises(ValueError):
        be.write("/output/../../etc/passwd", "x")


def test_traversal_rejected_on_read(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    with pytest.raises(ValueError):
        be.read("../secret")


# ---------------------------------------------------------------------------
# async surface smoke
# ---------------------------------------------------------------------------
async def test_async_read_write(fake_minio, file_dir):
    be = make_backend("sv1", fake_minio, file_dir)
    await be.awrite("/output/async.md", "async-data")
    res = await be.aread("/output/async.md")
    assert "async-data" in res.file_data["content"]
