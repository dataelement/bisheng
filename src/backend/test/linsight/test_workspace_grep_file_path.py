"""Workspace ``grep`` with ``path`` naming one file searches that file.

On 106 (2026-11-16) a task-mode session called ``grep(pattern, path="/uploads/x.md")``
29 times and got "No matches found" every time, although the keywords were in
the file. ``grep`` lists ``path`` first, and ``ls`` ends the prefix at a
directory boundary (``uploads/x.md/``), so a file path listed nothing. The model
then read an 8489-line file 200 lines at a time, filled its context and lost
the task across four compressions.

These tests run the real ``ls`` against a fake bucket so the prefix rule is
exercised, not mocked away. ``asyncio_mode = auto``.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

SVID = "sv-grep-file"
REPORT = "公司受限资产账面价值118.62亿元。\n无关的一行\n对外担保余额7.09亿元。\n"


class _FakeBucket:
    """``list_objects`` with MinIO's prefix and recursive semantics."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def list_objects(self, bucket, prefix="", recursive=False):
        for name, data in sorted(self.objects.items()):
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            if not recursive and "/" in rest:
                continue
            yield SimpleNamespace(object_name=name, is_dir=False, size=len(data))


def _backend(tmp_path, files: dict[str, str]) -> WorkspaceBackend:
    objects = {f"workspace/{SVID}/{rel}": text.encode() for rel, text in files.items()}
    minio = MagicMock()
    minio.bucket = "bisheng"
    minio.minio_client_sync = _FakeBucket(objects)
    minio.get_object_sync.side_effect = lambda bucket_name, object_name: objects[object_name]
    return WorkspaceBackend(svid=SVID, minio=minio, file_dir=str(tmp_path))


def _hits(res) -> list[tuple[str, int]]:
    assert res.error is None
    return [(m["path"], m["line"]) for m in res.matches]


def test_grep_file_path_searches_that_file(tmp_path):
    be = _backend(tmp_path, {"uploads/report.md": REPORT})
    assert _hits(be.grep("受限资产", path="/uploads/report.md")) == [("/uploads/report.md", 1)]
    assert _hits(be.grep("对外担保", path="uploads/report.md")) == [("/uploads/report.md", 3)]


def test_grep_file_path_ignores_sibling_with_same_prefix(tmp_path):
    be = _backend(
        tmp_path,
        {"uploads/report.md": REPORT, "uploads/report.md.bak": REPORT, "uploads/report.md2": REPORT},
    )
    assert _hits(be.grep("受限资产", path="/uploads/report.md")) == [("/uploads/report.md", 1)]


def test_grep_directory_path_unchanged(tmp_path):
    be = _backend(tmp_path, {"uploads/report.md": REPORT, "uploads_old/report.md": REPORT})
    assert _hits(be.grep("受限资产", path="/uploads")) == [("/uploads/report.md", 1)]
    assert _hits(be.grep("受限资产", path="/uploads/")) == [("/uploads/report.md", 1)]


def test_grep_missing_path_no_match(tmp_path):
    be = _backend(tmp_path, {"uploads/report.md": REPORT})
    assert _hits(be.grep("受限资产", path="/uploads/missing.md")) == []


async def test_agrep_file_path(tmp_path):
    be = _backend(tmp_path, {"uploads/report.md": REPORT})
    assert _hits(await be.agrep("受限资产", path="/uploads/report.md")) == [("/uploads/report.md", 1)]
