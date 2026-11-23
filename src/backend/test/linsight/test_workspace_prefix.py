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


# ---------------------------------------------------------------------------
# Same-named attachments of a later run replace the earlier run's file
# ---------------------------------------------------------------------------


class _ClockedObjectStore(_MemoryObjectStore):
    """Reports ``last_modified`` like the object store: every write and copy gets a later time."""

    def __init__(self) -> None:
        super().__init__()
        self.modified: dict[str, int] = {}
        self._tick = 0

    def _stamp(self, name: str) -> None:
        self._tick += 1
        self.modified[name] = self._tick

    def write(self, name: str, data: bytes) -> None:
        self.objects[name] = data
        self._stamp(name)

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False, last_modified=self.modified.get(name))
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]

    def copy_object_sync(self, source_bucket, source_object, dest_bucket, dest_object):
        super().copy_object_sync(source_bucket, source_object, dest_bucket, dest_object)
        self._stamp(dest_object)


async def test_copy_prefix_replace_older_takes_the_newer_source():
    store = _ClockedObjectStore()
    conv = f"{CONV_PREFIX}/uploads/合同.md"
    store.write("workspace/sv-1/uploads/合同.md", b"v1")
    assert (
        await copy_workspace_prefix(
            store, src_prefix="workspace/sv-1", dst_prefix=CONV_PREFIX, only_if_empty=False, replace_older=True
        )
        == 1
    )

    # Run 2 ingests an edited file of the same name after run 1's copy.
    store.write("workspace/sv-2/uploads/合同.md", b"v2")
    store.write("workspace/sv-2/uploads/附件.md", b"new file")
    copied = await copy_workspace_prefix(
        store, src_prefix="workspace/sv-2", dst_prefix=CONV_PREFIX, only_if_empty=False, replace_older=True
    )

    assert copied == 2
    assert store.objects[conv] == b"v2"
    assert store.objects[f"{CONV_PREFIX}/uploads/附件.md"] == b"new file"


async def test_copy_prefix_replace_older_keeps_what_the_destination_got_later():
    store = _ClockedObjectStore()
    conv = f"{CONV_PREFIX}/uploads/合同.md"
    store.write("workspace/sv-1/uploads/合同.md", b"v1")
    kwargs = {"dst_prefix": CONV_PREFIX, "only_if_empty": False, "replace_older": True}
    await copy_workspace_prefix(store, src_prefix="workspace/sv-1", **kwargs)

    # The same source merged again (resume / continue of the run): nothing to do.
    assert await copy_workspace_prefix(store, src_prefix="workspace/sv-1", **kwargs) == 0

    # A later write to the conversation workspace (the agent, or run 2's upload) stays
    # when run 1 is continued and its own prefix is merged once more.
    store.write(conv, b"v2")
    assert await copy_workspace_prefix(store, src_prefix="workspace/sv-1", **kwargs) == 0
    assert store.objects[conv] == b"v2"


async def test_copy_prefix_merge_without_replace_older_never_overwrites():
    """The previous version's workspace is older than the destination: its files never win."""
    store = _ClockedObjectStore()
    store.write(f"{CONV_PREFIX}/uploads/合同.md", b"current")
    store.write("workspace/sv-old/uploads/合同.md", b"modified later, still the older version's file")

    copied = await copy_workspace_prefix(
        store, src_prefix="workspace/sv-old", dst_prefix=CONV_PREFIX, only_if_empty=False
    )

    assert copied == 0
    assert store.objects[f"{CONV_PREFIX}/uploads/合同.md"] == b"current"


async def test_run_uploads_replace_the_same_named_file_of_an_earlier_run(monkeypatch: pytest.MonkeyPatch):
    """Run 1 uploaded 合同.docx; run 2 uploads an edited 合同.docx. Run 2 must read its own file."""
    from unittest.mock import AsyncMock

    from bisheng.linsight.domain import task_exec
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask, set_run_thread_id

    store = _ClockedObjectStore()
    monkeypatch.setattr(task_exec, "get_minio_storage", AsyncMock(return_value=store))
    conv_id = "conv-123"

    def version(svid: str) -> LinsightSessionVersion:
        one = LinsightSessionVersion(id=svid, session_id=conv_id, user_id=1, tenant_id=1, question="q")
        set_run_thread_id(one, conv_id)
        return one

    first, second = version("sv-1"), version("sv-2")
    task = LinsightWorkflowTask()
    assert task._workspace_prefix(first) == task._workspace_prefix(second) == CONV_PREFIX

    # Attachment ingest writes under the run's own prefix (workbench_impl).
    store.write("workspace/sv-1/uploads/合同.md", b"v1")
    store.write("workspace/sv-1/uploads/合同.docx", b"docx v1")
    await task._merge_run_uploads(first)
    store.write(f"{CONV_PREFIX}/output/report.md", b"run 1 report")

    store.write("workspace/sv-2/uploads/合同.md", b"v2")
    store.write("workspace/sv-2/uploads/合同.docx", b"docx v2")
    await task._merge_run_uploads(second)

    # The file pointer block of run 2 names /uploads/合同.md: it is run 2's file.
    assert store.objects[f"{CONV_PREFIX}/uploads/合同.md"] == b"v2"
    assert store.objects[f"{CONV_PREFIX}/uploads/合同.docx"] == b"docx v2"
    assert store.objects[f"{CONV_PREFIX}/output/report.md"] == b"run 1 report"

    # Run 1 is continued afterwards (same svid, merged again): run 2's file stays.
    await task._merge_run_uploads(first)
    assert store.objects[f"{CONV_PREFIX}/uploads/合同.md"] == b"v2"

    # Taking over the previous version's workspace still never overwrites.
    store.write("workspace/sv-0/uploads/合同.md", b"v0")
    store.write("workspace/sv-0/uploads/旧附件.md", b"old only")
    await task._merge_into_workspace(second, "workspace/sv-0")
    assert store.objects[f"{CONV_PREFIX}/uploads/合同.md"] == b"v2"
    assert store.objects[f"{CONV_PREFIX}/uploads/旧附件.md"] == b"old only"
