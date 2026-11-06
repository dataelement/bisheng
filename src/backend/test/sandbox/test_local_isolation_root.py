"""LocalExecutor uid isolation end to end. Linux + root only.

Every test runs real scripts as a pool uid, so they are skipped on developer
machines and in non-root CI; run them inside the backend image.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time

import pytest

from bisheng.core.config.settings import SandboxConf
from bisheng_langchain.gpts.tools.code_interpreter import local_executor as local_executor_module
from bisheng_langchain.gpts.tools.code_interpreter import local_isolation, local_run_registry, local_uid_pool
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import TASK_ENDED_MSG, LocalExecutor

pytestmark = pytest.mark.skipif(
    not (os.uname().sysname == "Linux" and os.geteuid() == 0), reason="needs Linux and root"
)


@pytest.fixture
def conf(monkeypatch: pytest.MonkeyPatch):
    # Directly under /tmp: pytest's own tmp dirs are 0700 and the pool uid has
    # to traverse every ancestor of its run dir.
    run_root = tempfile.mkdtemp(prefix="bisheng-local-run-test-", dir="/tmp")
    value = SandboxConf(local_isolation="uid", local_run_root=run_root)
    monkeypatch.setattr(local_isolation, "_conf", lambda: value)
    yield value
    shutil.rmtree(run_root, ignore_errors=True)


@pytest.fixture
def workspace(tmp_path):
    w = tmp_path / "w"
    w.mkdir(mode=0o700)
    (w / "uploads").mkdir()
    (w / "uploads" / "in.txt").write_text("source data")
    return w


def _run(code: str, work_dir, timeout: int = 30):
    return LocalExecutor.execute_code(code=code, work_dir=str(work_dir), timeout=timeout)


def test_child_runs_as_a_pool_uid_with_only_allowlisted_env(conf, workspace, monkeypatch) -> None:
    monkeypatch.setenv("BS_MYSQL_PASSWORD", "leak-me")
    code = (
        "import os, json\n"
        "print(json.dumps({'uid': os.getuid(), 'groups': os.getgroups(), 'env': sorted(os.environ)}))\n"
    )
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs

    info = json.loads(logs.strip().splitlines()[-1])
    assert local_uid_pool.UID_MIN <= info["uid"] <= local_uid_pool.UID_MAX
    assert set(info["groups"]) <= {info["uid"]}
    assert "BS_MYSQL_PASSWORD" not in info["env"]


def test_secrets_and_other_workspaces_are_unreachable(conf, workspace) -> None:
    pkg = local_isolation._backend_package_dir()
    code = (
        "def denied(fn):\n"
        "    try:\n"
        "        fn()\n"
        "    except PermissionError:\n"
        "        return True\n"
        "    return False\n"
        "print(denied(lambda: open('/proc/1/environ','rb').read(1)), denied(lambda: __import__('os').listdir('/root')),"
        f" denied(lambda: open({os.path.join(pkg, 'config.yaml')!r}).read(1)))\n"
    )
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs
    assert logs.strip().splitlines()[-1] == "True True True"


def test_results_are_harvested_and_inputs_visible(conf, workspace) -> None:
    code = (
        "import os\n"
        "os.makedirs('output', exist_ok=True)\n"
        "data = open('uploads/in.txt').read()\n"
        "open('output/out.txt', 'w').write(data.upper())\n"
        f"print(os.path.exists({str(workspace / 'uploads' / 'in.txt')!r}))\n"
        "print(os.getcwd())\n"
    )
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs
    assert (workspace / "output" / "out.txt").read_text() == "SOURCE DATA"
    lines = logs.strip().splitlines()
    # absolute W paths in the code and the run dir in the output are both rewritten
    assert lines[-2] == "True"
    assert lines[-1] == str(workspace)
    assert os.stat(workspace / "output" / "out.txt").st_uid == 0


def test_planted_links_are_not_harvested(conf, workspace) -> None:
    code = (
        "import os\n"
        "os.symlink('/etc/passwd', 'passwd')\n"
        "open('a.txt', 'w').write('a')\n"
        "os.link('a.txt', 'hard.txt')\n"
        "os.mkfifo('pipe')\n"
    )
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs
    for name in ("passwd", "hard.txt", "pipe", "a.txt"):
        assert not os.path.lexists(workspace / name)


def test_workspace_is_not_modified_in_place(conf, workspace) -> None:
    code = "import os\nos.remove('uploads/in.txt')\n"
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs
    assert (workspace / "uploads" / "in.txt").read_text() == "source data"


def test_timeout_and_background_processes_leave_nothing_behind(conf, workspace) -> None:
    code = (
        "import subprocess, os, time\n"
        "subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
        "print(os.getuid(), flush=True)\n"
        "time.sleep(300)\n"
    )
    started = time.monotonic()
    exitcode, logs, _ = _run(code, workspace, timeout=2)
    assert exitcode == 1
    assert logs.startswith("Timeout")
    assert time.monotonic() - started < 30
    uid = int(logs.split("Output captured before the kill:\n")[1].split()[0])
    assert not local_uid_pool.uid_has_live_process(uid)
    assert not os.path.exists(os.path.join(local_uid_pool.MARKER_DIR, str(uid)))
    assert os.listdir(conf.local_run_root) == []


def test_background_process_of_a_finished_run_is_reaped(conf, workspace) -> None:
    code = "import subprocess, os\nsubprocess.Popen(['sleep', '300'], start_new_session=True)\nprint(os.getuid())\n"
    exitcode, logs, _ = _run(code, workspace)
    assert exitcode == 0, logs
    uid = int(logs.strip().splitlines()[-1])
    assert not local_uid_pool.uid_has_live_process(uid)


def test_freeing_a_uid_wipes_its_run_dirs(conf, workspace) -> None:
    uid = local_uid_pool.acquire(conf.local_run_root)
    stale = os.path.join(conf.local_run_root, "run-stale")
    os.mkdir(stale)
    with open(os.path.join(stale, "secret.txt"), "w") as fh:
        fh.write("previous run")
    os.chown(stale, uid, uid)
    local_uid_pool.free(uid, conf.local_run_root)
    assert not os.path.exists(stale)


def test_matplotlib_chart_with_cjk_text(conf, workspace) -> None:
    code = (
        "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
        "import os\nos.makedirs('output', exist_ok=True)\n"
        "plt.title('中文标题')\nplt.plot([1, 2])\nplt.savefig('output/c.png')\n"
    )
    exitcode, logs, _ = _run(code, workspace, timeout=120)
    assert exitcode == 0, logs
    assert (workspace / "output" / "c.png").exists()


# --- retained mode (Linsight) ------------------------------------------------


@pytest.fixture
def retained(conf, workspace, monkeypatch):
    monkeypatch.setattr(local_executor_module, "isolation_mode", lambda: "uid")
    executor = LocalExecutor(minio={}, local_sync_path=str(workspace), keep_run_dir=True)
    # file_list upload goes to MinIO; not what these tests look at
    monkeypatch.setattr(executor, "upload_minio", lambda name, path: name)
    yield executor
    local_run_registry.release_local_run(str(workspace))


def _last_line(result: dict) -> str:
    assert result["exitcode"] == 0, result["log"]
    return result["log"].strip().splitlines()[-1]


def test_retained_run_keeps_uid_and_run_dir_across_calls(retained, workspace) -> None:
    first = _last_line(retained.run("import os\nprint(os.getuid(), os.path.realpath('.'))"))
    entry = retained._run_entry
    run_dir = entry.run_dir
    retained.run("import os\nos.makedirs('scratch', exist_ok=True)\nopen('scratch/s.txt','w').write('step1')")
    second = _last_line(retained.run("import os\nprint(os.getuid(), open('scratch/s.txt').read())"))

    assert first.split()[0] == second.split()[0] == str(entry.uid)
    # the run dir is reported as W and stays the same
    assert first.split()[1] == str(workspace)
    assert entry.run_dir == run_dir
    assert second.split()[1] == "step1"
    assert (workspace / "scratch" / "s.txt").read_text() == "step1"


def test_retained_run_picks_up_changes_made_to_w_between_calls(retained, workspace) -> None:
    retained.run("print(open('uploads/in.txt').read())")
    time.sleep(0.01)
    (workspace / "uploads" / "in.txt").write_text("edited by a file tool")
    (workspace / "new.txt").write_text("new")
    out = retained.run("print(open('uploads/in.txt').read(), open('new.txt').read())")
    assert _last_line(out) == "edited by a file tool new"


def test_links_planted_in_the_run_dir_are_not_written_through(retained, workspace) -> None:
    victim = tempfile.NamedTemporaryFile(dir="/tmp", delete=False)
    victim.write(b"root file")
    victim.close()
    os.chmod(victim.name, 0o644)
    # Hex-encoded so the textual escape guard does not reject the script before
    # it runs: this test is about the boundary behind the guard.
    file_hex, dir_hex = victim.name.encode().hex(), os.path.dirname(victim.name).encode().hex()
    try:
        planted = (
            "import os, shutil\n"
            f"os.remove('uploads/in.txt'); os.symlink(bytes.fromhex({file_hex!r}).decode(), 'uploads/in.txt')\n"
            "shutil.rmtree('.mpl', ignore_errors=True)\n"
            f"os.symlink(bytes.fromhex({dir_hex!r}).decode(), '.mpl')\n"
        )
        retained.run(planted)
        time.sleep(0.01)
        (workspace / "uploads" / "in.txt").write_text("fresh")
        out = retained.run("import matplotlib\nprint(open('uploads/in.txt').read())")
        assert _last_line(out) == "fresh"
        with open(victim.name, "rb") as fh:
            assert fh.read() == b"root file"
        assert not any(name.startswith("fontlist") for name in os.listdir(os.path.dirname(victim.name)))
    finally:
        os.unlink(victim.name)


def test_release_kills_leftovers_and_frees_everything(retained, workspace, conf) -> None:
    retained.run("import subprocess\nsubprocess.Popen(['sleep', '300'], start_new_session=True)")
    entry = retained._run_entry
    uid, run_dir = entry.uid, entry.run_dir
    local_run_registry.release_local_run(str(workspace))
    assert not local_uid_pool.uid_has_live_process(uid)
    assert not os.path.exists(run_dir)
    assert not os.path.exists(os.path.join(local_uid_pool.MARKER_DIR, str(uid)))
    assert retained.run("print(1)")["log"] == TASK_ENDED_MSG


def test_release_during_a_run_stops_it_without_harvesting(retained, workspace) -> None:
    retained.run("print('warm up')")
    code = "import time\nopen('late.txt','w').write('x')\ntime.sleep(300)\n"
    result = {}
    worker = threading.Thread(target=lambda: result.update(retained.run(code)))
    started = time.monotonic()
    worker.start()
    time.sleep(2)
    local_run_registry.release_local_run(str(workspace))
    worker.join(30)
    assert not worker.is_alive()
    assert time.monotonic() - started < 30
    assert result["log"] == TASK_ENDED_MSG
    assert not (workspace / "late.txt").exists()


def test_startup_sweep_reclaims_a_dead_workers_leftovers(conf, monkeypatch) -> None:
    monkeypatch.setattr(local_isolation, "isolation_mode", lambda: "uid")
    uid = local_uid_pool.acquire(conf.local_run_root)
    run_dir = local_isolation._make_run_dir(conf.local_run_root, uid)
    marker = os.path.join(local_uid_pool.MARKER_DIR, str(uid))
    with open(marker, "w") as fh:
        fh.write("999999999 1")  # a pid that cannot exist
    local_isolation.sweep_on_startup()
    assert not os.path.exists(run_dir)
    assert not os.path.exists(marker)
