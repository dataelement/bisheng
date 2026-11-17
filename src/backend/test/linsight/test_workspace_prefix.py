"""F004 T023: ``WorkspaceBackend`` addressed by an arbitrary workspace prefix.

The unified runtime keeps one workspace per conversation
(``workspace/{conversation_id}``) instead of one per session version. These tests
pin three properties (AC-26, AC-40):

  1. a backend built with ``workspace_prefix=`` reads, writes and lists only under
     that prefix;
  2. ``copy_workspace_prefix`` copies ``output/`` and ``uploads/`` from one prefix
     to another;
  3. a backend built with ``svid=`` keeps today's object keys
     (``workspace/{svid}/...``), so legacy sessions read the same objects.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from bisheng.linsight.domain.services.workspace_backend import (
    WorkspaceBackend,
    copy_workspace_prefix,
    seed_workspace_from_previous,
)


class _MemoryObjectStore:
    """The slice of ``MinioStorage`` that ``WorkspaceBackend`` and the copy use."""

    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    def put_object_sync(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file

    async def get_object(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def get_object_sync(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False)
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]

    def copy_object_sync(self, source_bucket, source_object, dest_bucket, dest_object):
        if source_object not in self.objects:
            from minio.error import S3Error

            exc = S3Error.__new__(S3Error)
            object.__setattr__(exc, "code", "NoSuchKey")
            raise exc
        self.objects[dest_object] = self.objects[source_object]


CONV_PREFIX = "workspace/conv-123"


def test_backend_scoped_to_prefix(tmp_path):
    store = _MemoryObjectStore()
    store.objects["workspace/other/output/secret.md"] = b"not yours"
    be = WorkspaceBackend(workspace_prefix=CONV_PREFIX, minio=store, file_dir=str(tmp_path))

    assert be.write("/output/report.md", "hello").error is None
    assert store.objects[f"{CONV_PREFIX}/output/report.md"] == b"hello"

    # read goes through MinIO even with a cold cache
    cold = WorkspaceBackend(workspace_prefix=CONV_PREFIX + "/", minio=store, file_dir=str(tmp_path / "cold"))
    res = cold.read("/output/report.md")
    assert res.error is None
    assert "hello" in res.file_data["content"]

    listed = cold.ls("/output")
    assert listed.error is None
    assert [e["path"] for e in listed.entries] == ["/output/report.md"]

    # nothing outside the prefix leaks into a root listing
    root = cold.ls("")
    assert [e["path"] for e in root.entries] == ["/output/report.md"]
    assert cold.workspace_prefix == CONV_PREFIX


async def test_copy_prefix_to_prefix():
    store = _MemoryObjectStore()
    src = "workspace/sv-old"
    store.objects[f"{src}/output/report.md"] = b"r"
    store.objects[f"{src}/uploads/doc/index.md"] = b"u"
    store.objects[f"{src}/scratch/notes.txt"] = b"s"

    copied = await copy_workspace_prefix(store, src_prefix=src, dst_prefix=CONV_PREFIX)

    assert copied == 2
    assert store.objects[f"{CONV_PREFIX}/output/report.md"] == b"r"
    assert store.objects[f"{CONV_PREFIX}/uploads/doc/index.md"] == b"u"
    assert f"{CONV_PREFIX}/scratch/notes.txt" not in store.objects

    # idempotent: a non-empty destination is left alone by default
    store.objects[f"{src}/output/second.md"] = b"2"
    assert await copy_workspace_prefix(store, src_prefix=src, dst_prefix=CONV_PREFIX) == 0

    # same prefix or empty prefix is a no-op
    assert await copy_workspace_prefix(store, src_prefix=src, dst_prefix=src + "/") == 0
    assert await copy_workspace_prefix(store, src_prefix="", dst_prefix=CONV_PREFIX) == 0


async def test_copy_prefix_merge_does_not_clobber():
    store = _MemoryObjectStore()
    src = "workspace/sv-old"
    store.objects[f"{src}/output/report.md"] = b"old"
    store.objects[f"{src}/uploads/a.md"] = b"a"
    store.objects[f"{CONV_PREFIX}/output/report.md"] = b"new"

    copied = await copy_workspace_prefix(store, src_prefix=src, dst_prefix=CONV_PREFIX, only_if_empty=False)

    assert copied == 1
    assert store.objects[f"{CONV_PREFIX}/output/report.md"] == b"new"
    assert store.objects[f"{CONV_PREFIX}/uploads/a.md"] == b"a"


async def test_svid_prefix_backward_compatible(tmp_path):
    store = _MemoryObjectStore()
    by_kw = WorkspaceBackend(svid="sv-1", minio=store, file_dir=str(tmp_path / "a"))
    positional = WorkspaceBackend("sv-1", store, str(tmp_path / "b"))
    explicit = WorkspaceBackend(workspace_prefix="workspace/sv-1", minio=store, file_dir=str(tmp_path / "c"))

    assert by_kw.svid == "sv-1"
    assert by_kw.workspace_prefix == positional.workspace_prefix == explicit.workspace_prefix == "workspace/sv-1"
    assert by_kw._object_key("output/x.md") == "workspace/sv-1/output/x.md"

    by_kw.write("/output/x.md", "x")
    assert store.objects["workspace/sv-1/output/x.md"] == b"x"
    assert [e["path"] for e in explicit.ls("").entries] == ["/output/x.md"]
    assert [m["path"] for m in positional.glob("**/*.md").matches] == ["/output/x.md"]

    # the svid-based seed wrapper keeps its keys
    assert await seed_workspace_from_previous(store, src_svid="sv-1", dst_svid="sv-2") == 1
    assert store.objects["workspace/sv-2/output/x.md"] == b"x"


def test_backend_requires_svid_or_prefix(tmp_path):
    with pytest.raises(ValueError):
        WorkspaceBackend(minio=_MemoryObjectStore(), file_dir=str(tmp_path))
