"""Cross-turn originals must reach the LOCAL task dir, not just the workspace.

``_init_file_directory`` prefetches originals from THIS turn's ``files``, which is
empty on a follow-up ("把刚才那个表再算一下") — there, the original only exists in
the workspace, put there by ``seed_workspace_from_previous``. But the code
interpreter's file list is built from ``os.walk(file_dir)`` / ``local_sync_path``:
it never talks to MinIO. Without the sync step the model sees ``uploads/x.xlsx``
in ``ls``, is told by the pointer block it can compute on it, and then finds
nothing in the sandbox — the whole point of carrying the original is lost.

Second invariant: the sync lands files AFTER ``_init_file_directory`` took the
deliverable baseline, so they must be added to it. Otherwise the user's own upload
comes back as "the agent produced this".

``asyncio_mode = auto`` — async tests need no decorator.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

SVID = "sv-followup"


class _Obj:
    def __init__(self, name: str, size: int = 10):
        self.object_name = name
        self.size = size
        self.is_dir = False


def _minio(objects: dict[str, bytes]) -> MagicMock:
    """MinIO stand-in whose listing and reads are backed by one dict."""
    minio = MagicMock()
    minio.bucket = "bisheng"

    def _list(bucket, prefix="", recursive=True):
        return iter([_Obj(k, len(v)) for k, v in objects.items() if k.startswith(prefix)])

    minio.minio_client_sync.list_objects.side_effect = _list
    minio.get_object_sync.side_effect = lambda bucket_name=None, object_name=None: objects.get(object_name)
    return minio


def _task(file_dir: str) -> LinsightWorkflowTask:
    task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
    task.file_dir = file_dir
    task._baseline_files = set()
    return task


async def test_original_synced_from_workspace_and_baselined(tmp_path):
    objects = {
        f"workspace/{SVID}/uploads/销售数据.md": b"# view\n",
        f"workspace/{SVID}/uploads/销售数据.xlsx": b"PK\x03\x04binary",
    }
    task = _task(str(tmp_path))

    with patch(
        "bisheng.linsight.domain.task_exec.get_minio_storage",
        AsyncMock(return_value=_minio(objects)),
    ):
        await task._sync_workspace_originals(SimpleNamespace(id=SVID))

    local = tmp_path / "uploads" / "销售数据.xlsx"
    assert local.read_bytes() == b"PK\x03\x04binary"
    # The markdown view is read through read_file (MinIO); no local copy needed.
    assert not (tmp_path / "uploads" / "销售数据.md").exists()
    # ...and it must not be mistaken for this turn's deliverable.
    assert str(local) in {os.path.normpath(p) for p in task._baseline_files}


async def test_sync_is_idempotent_for_already_prefetched_files(tmp_path):
    """Fresh turns already prefetched the original; the sync must not re-download."""
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "data.xlsx").write_bytes(b"already here")
    objects = {f"workspace/{SVID}/uploads/data.xlsx": b"different bytes"}
    task = _task(str(tmp_path))
    minio = _minio(objects)

    with patch("bisheng.linsight.domain.task_exec.get_minio_storage", AsyncMock(return_value=minio)):
        await task._sync_workspace_originals(SimpleNamespace(id=SVID))

    assert (tmp_path / "uploads" / "data.xlsx").read_bytes() == b"already here"
    minio.get_object_sync.assert_not_called()
    assert task._baseline_files == set()


async def test_sync_failure_never_blocks_the_turn(tmp_path):
    """Best-effort: losing the precise-data track must not fail the task."""
    task = _task(str(tmp_path))

    with patch(
        "bisheng.linsight.domain.task_exec.get_minio_storage",
        AsyncMock(side_effect=RuntimeError("minio down")),
    ):
        await task._sync_workspace_originals(SimpleNamespace(id=SVID))  # must not raise

    assert task._baseline_files == set()
