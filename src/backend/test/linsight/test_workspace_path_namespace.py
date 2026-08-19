"""The file tools and the code interpreter speak two path namespaces.

The workspace tools render everything with a LEADING SLASH (`/output/a.md`), while
the interpreter's cwd IS that same workspace root, so on disk it is `output/a.md`.
Session ``aa352cb4…`` (180 POC, 2026-08-08) paid for that gap twice:

- forward: `open("/skills/html-ppt-templates/...")` → FileNotFoundError, and three
  model round-trips to work out why;
- backward: the model handed `read_file` a host path it had seen in the interpreter
  (`/root/.cache/bisheng/linsight/aa352cb4/output/.../qa/s08.png`), the leading slash
  was simply dropped, and it became the nonsense key
  `workspace/<svid>/root/.cache/...` → four silent "File not found"s.

The backward half is fixed by folding the host prefix back to a workspace key. That
also makes those reads SUCCEED, because the interpreter writes into ``file_dir`` and
``read`` checks that cache before MinIO.

Stripping must be provably unambiguous: a heuristic here would silently open the
WRONG file, which is worse than an error. Hence the adversarial cases below.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from __future__ import annotations

import tempfile

import pytest

# Reuse the in-memory MinIO stand-in rather than duplicating it. ``test/linsight``
# has no ``__init__.py``, so pytest puts the directory itself on sys.path and this
# resolves as a top-level module.
from test_workspace_backend import FakeMinioStorage

from bisheng.linsight.domain.services.workspace_backend import (
    WorkspaceBackend,
    normalize_workspace_path,
    strip_executor_host_prefix,
)

SVID = "aa352cb420f649d2be391cb09d9ad69d"
FILE_DIR = "/root/.cache/bisheng/linsight/aa352cb4"


# ---------------------------------------------------------------------------
# Pure function
# ---------------------------------------------------------------------------


def test_the_180_host_path_folds_back_to_a_workspace_key():
    """The exact path that produced four 'File not found' errors in production."""
    assert (
        normalize_workspace_path(f"{FILE_DIR}/output/siyuan-signal-deck/qa/s08.png", file_dir=FILE_DIR)
        == "output/siyuan-signal-deck/qa/s08.png"
    )


@pytest.mark.parametrize(
    "path",
    ["/output/a.md", "output/a.md", "/uploads/report.xlsx", "skills/x/SKILL.md"],
)
def test_ordinary_workspace_paths_are_unchanged(path):
    assert normalize_workspace_path(path, file_dir=FILE_DIR) == path.lstrip("/")


def test_a_real_root_directory_in_the_workspace_is_not_stripped():
    """Adversarial: the workspace may legitimately contain ``root/``. Only the FULL
    file_dir prefix counts — never a mere ancestor segment."""
    assert normalize_workspace_path("/root/report.md", file_dir=FILE_DIR) == "root/report.md"
    assert normalize_workspace_path("/root/.cache/x", file_dir=FILE_DIR) == "root/.cache/x"
    assert normalize_workspace_path("/root/.cache/bisheng/x", file_dir=FILE_DIR) == "root/.cache/bisheng/x"


def test_a_prefix_similar_sibling_is_not_stripped():
    """Adversarial: ``/tmp/ws/aa352cb4x/...`` shares a string prefix with
    ``/tmp/ws/aa352cb4`` but is a different directory — the ``/`` boundary is what
    keeps them apart."""
    assert normalize_workspace_path("/tmp/ws/aa352cb4x/output/a", file_dir="/tmp/ws/aa352cb4") == (
        "tmp/ws/aa352cb4x/output/a"
    )


def test_another_sessions_task_dir_is_not_stripped():
    """A sibling task dir is NOT folded in. Catching it would also catch any
    unrelated directory that merely shares the parent, and a rewrite rule that
    cannot tell those apart would silently open the wrong file. The measured
    production failure used the CURRENT session's dir, which rule 1 covers."""
    assert normalize_workspace_path("/root/.cache/bisheng/linsight/bb99ff00/output/a.md", file_dir=FILE_DIR) == (
        "root/.cache/bisheng/linsight/bb99ff00/output/a.md"
    )


def test_a_different_subtree_under_the_same_grandparent_is_not_stripped():
    assert normalize_workspace_path("/root/.cache/bisheng/other/output/a.md", file_dir=FILE_DIR) == (
        "root/.cache/bisheng/other/output/a.md"
    )


def test_the_file_dir_itself_is_the_workspace_root():
    assert normalize_workspace_path(FILE_DIR, file_dir=FILE_DIR) == ""


def test_traversal_is_still_rejected_after_stripping():
    with pytest.raises(ValueError):
        normalize_workspace_path(f"{FILE_DIR}/../../etc/passwd", file_dir=FILE_DIR)
    with pytest.raises(ValueError):
        normalize_workspace_path("../etc/passwd", file_dir=FILE_DIR)


def test_without_a_file_dir_the_old_behaviour_is_preserved():
    """``test_skill_provisioning`` calls this as a plain contract function."""
    assert normalize_workspace_path(f"{FILE_DIR}/output/a.md") == "root/.cache/bisheng/linsight/aa352cb4/output/a.md"


def test_strip_reports_whether_it_did_anything():
    assert strip_executor_host_prefix(f"{FILE_DIR}/output/a", FILE_DIR) == ("output/a", True)
    assert strip_executor_host_prefix("/output/a", FILE_DIR) == ("/output/a", False)
    assert strip_executor_host_prefix("/output/a", None) == ("/output/a", False)


# ---------------------------------------------------------------------------
# Backend integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def minio():
    return FakeMinioStorage()


@pytest.fixture()
def workdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _backend(minio, workdir):
    return WorkspaceBackend(svid=SVID, minio=minio, file_dir=workdir)


def _interpreter_writes(workdir: str, rel: str, data: bytes) -> str:
    """Simulate the code interpreter: writes straight into its cwd, never MinIO."""
    from pathlib import Path

    p = Path(workdir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


def test_a_host_path_from_the_interpreter_now_reads_successfully(minio, workdir):
    """The real payoff: not just a better error, an actual successful read. The
    interpreter's output never reaches MinIO, but ``read`` checks the local cache
    first — which is the very directory the interpreter wrote to."""
    host_path = _interpreter_writes(workdir, "output/report.md", b"hello from the interpreter")
    backend = _backend(minio, workdir)

    result = backend.read(host_path)

    assert result.error is None
    assert "hello from the interpreter" in result.file_data["content"]
    assert (minio.bucket, f"workspace/{SVID}/output/report.md") not in minio.store


async def test_the_async_read_folds_the_same_way(minio, workdir):
    host_path = _interpreter_writes(workdir, "output/report.md", b"async hello")
    backend = _backend(minio, workdir)

    result = await backend.aread(host_path)

    assert result.error is None
    assert "async hello" in result.file_data["content"]


def test_ls_accepts_either_namespace(minio, workdir):
    _interpreter_writes(workdir, "output/a.txt", b"a")
    backend = _backend(minio, workdir)
    backend.write("/output/a.txt", "a")

    by_workspace = {e["path"] for e in backend.ls("/output").entries}
    by_host = {e["path"] for e in backend.ls(f"{workdir}/output").entries}
    assert by_workspace == by_host


def test_a_real_root_directory_still_round_trips(minio, workdir):
    """Adversarial, end to end: a workspace file literally named ``root/...`` must
    still write and read back as itself."""
    backend = _backend(minio, workdir)
    backend.write("/root/report.md", "mine")

    assert (minio.bucket, f"workspace/{SVID}/root/report.md") in minio.store
    assert "mine" in backend.read("/root/report.md").file_data["content"]


def test_missing_host_path_error_names_both_namespaces(minio, workdir):
    backend = _backend(minio, workdir)

    err = backend.read(f"{workdir}/output/missing.png").error
    assert "workspace path 'output/missing.png'" in err

    err_host = backend.read("/home/user/output/x.png").error
    assert "HOST filesystem" in err_host

    err_plain = backend.read("/output/missing.png").error
    assert err_plain == "File '/output/missing.png' not found"


def test_edit_shares_the_same_error_wording(minio, workdir):
    backend = _backend(minio, workdir)
    err = backend.edit(f"{workdir}/output/missing.md", "a", "b").error
    assert "workspace path 'output/missing.md'" in err
