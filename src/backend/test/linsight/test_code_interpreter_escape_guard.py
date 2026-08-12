"""The code interpreter must refuse to read the host filesystem.

``LocalExecutor`` is a subprocess on the SHARED backend host, not a sandbox: a
script can read anything the service account can. A production daily-chat turn
walked ``/tmp``, ``/app``, ``/home``, ``/data`` and ``~``, landed in
``/root/.cache/bisheng/bisheng/`` — the GLOBAL download cache where every user's
uploads pile up under a flat ``<sha256>_<name>`` — and answered from a document
that belonged to a different conversation.

Annotating that after the fact (the ``absolute_path_advisory`` model) would be
useless: by then the other user's data is already in the model's context. So the
guard rejects the run BEFORE anything executes.

Two exemptions have to hold or legitimate code breaks:
  * prose is not access — a script may print a host path it is talking about;
  * linsight hands the model host paths OF ITS OWN workspace
    (``path_namespace_rules`` literally shows ``/root/.cache/.../output/a.png``),
    so a literal under ``local_sync_path`` stays legal.

No subprocess, matplotlib or MinIO is involved.
"""

from __future__ import annotations

import os

import pytest

from bisheng_langchain.gpts.tools.code_interpreter.base_executor import WORKSPACE_ESCAPE_NOTICE
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor

_MINIO = {"public_bucket": "bisheng", "tmp_bucket": "tmp-dir"}


def _executor(local_sync_path: str | None = None) -> LocalExecutor:
    return LocalExecutor(minio=_MINIO, local_sync_path=local_sync_path)


# ---------------------------------------------------------------------------
# Rejected: real filesystem access outside the working dir
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code",
    [
        # The exact shapes the production run used.
        "import os\nfor root, dirs, files in os.walk('/root'):\n    print(files)",
        "import os\nfor p in ['/tmp', '/app', '/home', '/data']:\n    os.listdir('/app')",
        "open('/root/.cache/bisheng/bisheng/84da_P_RfB.pdf', 'rb')",
        'import fitz\ndoc = fitz.open("/root/.cache/bisheng/bisheng/abc_tender.pdf")',
        "import glob\nglob.glob('/data/*.pdf')",
        "from pathlib import Path\nPath('/etc/passwd').read_text()",
        "import os\nos.path.exists('/var/log/app.log')",
        "import shutil\nshutil.copy('/home/other/report.xlsx', 'output/x.xlsx')",
        # Home expansion — how the model reached for "the file I was given".
        "import os\nos.walk(os.path.expanduser('~'))",
        'import os\nprint(os.listdir(os.path.expanduser("~")))',
        "from pathlib import Path\nprint(list(Path.home().iterdir()))",
        # A scan rooted at / walks the whole container.
        "import os\nfor root, dirs, files in os.walk('/'):\n    pass",
        "import glob\nglob.glob('/')",
    ],
)
def test_guard_rejects_host_access(code):
    assert _executor().workspace_escape_guard(code) == WORKSPACE_ESCAPE_NOTICE


def test_run_rejects_before_executing_anything(tmp_path):
    """A rejected run must not touch the filesystem at all."""
    executor = _executor()
    result = executor.run("import os\nprint(os.listdir('/root'))")

    assert result["exitcode"] == 1
    assert result["log"] == WORKSPACE_ESCAPE_NOTICE
    assert result["file_list"] == []


# ---------------------------------------------------------------------------
# Allowed: ordinary workspace code
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code",
    [
        "with open('output/report.pdf', 'wb') as f: f.write(b'x')",
        "import os\nos.makedirs('output', exist_ok=True)",
        "import fitz\ndoc = fitz.open('uploads/tender.pdf')",
        "import glob\nglob.glob('scratch/*.png')",
        "from pathlib import Path\nPath('output/a.md').read_text()",
        "import os\nfor root, dirs, files in os.walk('.'):\n    print(files)",
        # Prose ABOUT a host path is not access to it — the whole reason the
        # patterns are verb-anchored rather than matching bare literals.
        "print('nothing was found under /root/.cache, please re-upload')",
        "msg = '/etc/hosts is not readable here'\nprint(msg)",
        # A variable named like a verb must not drag an unrelated literal in.
        "home = '/home/report.pdf'  # noqa\nprint('done')",
    ],
)
def test_guard_allows_workspace_code(code):
    assert _executor().workspace_escape_guard(code) == ""


def test_guard_allows_absolute_path_into_own_workspace():
    """Linsight shows the model host paths of its own workspace; keep them legal."""
    file_dir = "/root/.cache/bisheng/linsight/8d2747aa"
    executor = _executor(local_sync_path=file_dir)

    assert executor.workspace_escape_guard(f"open('{file_dir}/output/a.png', 'rb')") == ""
    assert executor.workspace_escape_guard(f"open('{file_dir}')") == ""
    # A sibling task's dir shares the prefix but is NOT this workspace.
    assert (
        executor.workspace_escape_guard("open('/root/.cache/bisheng/linsight/ffffffff/output/a.png')")
        == WORKSPACE_ESCAPE_NOTICE
    )
    # The parent cache dir holds every user's uploads — still rejected.
    assert (
        executor.workspace_escape_guard("import os\nos.listdir('/root/.cache/bisheng/bisheng')")
        == WORKSPACE_ESCAPE_NOTICE
    )


def test_guard_ignores_empty_code():
    assert _executor().workspace_escape_guard("") == ""


# ---------------------------------------------------------------------------
# HOME redirect: `~` must resolve inside the workspace, not to the service home
# ---------------------------------------------------------------------------
def test_child_env_points_home_at_the_working_dir(tmp_path):
    env = LocalExecutor._child_env(str(tmp_path))

    assert env["HOME"] == str(tmp_path)
    # Pinned BEFORE HOME moves, or matplotlib rebuilds its font cache every run.
    assert env["MPLCONFIGDIR"] not in ("", str(tmp_path))
    assert os.path.isabs(env["MPLCONFIGDIR"])


def test_child_env_keeps_an_explicit_mplconfigdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", "/opt/mpl-cache")

    env = LocalExecutor._child_env(str(tmp_path))

    assert env["MPLCONFIGDIR"] == "/opt/mpl-cache"
    assert env["HOME"] == str(tmp_path)


def test_child_env_without_work_dir_is_untouched(monkeypatch):
    monkeypatch.setenv("HOME", "/root")

    env = LocalExecutor._child_env(None)

    assert env["HOME"] == "/root"
