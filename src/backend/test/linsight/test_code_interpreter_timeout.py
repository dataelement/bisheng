"""A code-interpreter run that never ends must be killed, not waited on forever.

`_execute_code` used to emulate a timeout with a thread pool:

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(subprocess.run, cmd, ...)
        try:
            result = future.result(timeout=timeout)
        except TimeoutError:
            return 1, TIMEOUT_MSG, ""      # <- never actually delivered

`future.result` did time out, but the `return` first runs the `with` block's
`__exit__` = `shutdown(wait=True)`, which joins the worker thread — and that thread
is blocked in `subprocess.run` until the child exits. So the timeout branch was
itself blocked by the very thing it was supposed to abort: a runaway script pinned a
CPU core and a linsight worker slot until someone killed the pid by hand. Observed in
production on 2026-08-06 — a model wrote `glob.glob('/**/validate.py', recursive=True)`
(the interpreter is not sandboxed, so that walks the whole host filesystem) and the
task sat at 99% CPU for over an hour past its 600s limit.

The fix runs the child in its own process group and kills that group on timeout.
Real subprocesses throughout — the bug lived entirely in the process plumbing, so
mocking it away would test nothing.
"""

from __future__ import annotations

import os
import threading
import time

from bisheng_langchain.gpts.tools.code_interpreter.local_executor import (
    MAX_FAILURE_LOG_CHARS,
    PARTIAL_OUTPUT_HEADER,
    LocalExecutor,
)

# Scripts are given this long before the kill; short so the suite stays fast.
RUN_TIMEOUT = 2
# How much longer than RUN_TIMEOUT the call may take before we call it hung.
WATCHDOG_SLACK = 20


def _execute(code: str, work_dir, timeout: int = RUN_TIMEOUT):
    """Run `execute_code` under a watchdog and return `(exitcode, logs, _)`.

    Under the old implementation this call never returns. A plain call would hang
    the entire pytest session with no output; the watchdog turns that regression
    into an ordinary failure.
    """
    box: dict[str, tuple] = {}

    def target() -> None:
        box["result"] = LocalExecutor.execute_code(code=code, timeout=timeout, work_dir=str(work_dir))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout + WATCHDOG_SLACK)
    assert not thread.is_alive(), (
        f"execute_code did not return within {timeout + WATCHDOG_SLACK}s — the timeout "
        "is not aborting the run (regression of the shutdown(wait=True) bug)"
    )
    return box["result"]


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # exists but is not ours — still alive for our purposes
        return True
    return True


# ---------------------------------------------------------------------------
# the timeout has to actually fire
# ---------------------------------------------------------------------------


def test_runaway_script_is_killed_and_reported(tmp_path):
    started = time.monotonic()
    exitcode, logs, _ = _execute("while True:\n    pass\n", tmp_path)
    elapsed = time.monotonic() - started

    assert exitcode == 1
    assert logs.startswith("Timeout")
    # the model gets told how long it had, so "just retry" is visibly not the fix
    assert str(RUN_TIMEOUT) in logs
    # the run is aborted near its deadline, not merely reported on afterwards
    assert elapsed < RUN_TIMEOUT + WATCHDOG_SLACK


def test_timeout_kills_processes_the_script_spawned(tmp_path):
    """Killing only the direct child leaves grandchildren burning CPU.

    Model-written code shells out constantly (LibreOffice, pandoc, pip), so the
    direct child is often just a launcher. `start_new_session` + `killpg` is what
    makes the whole run die, not merely its first process.
    """
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import pathlib, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(120)\n"
    )

    exitcode, logs, _ = _execute(code, tmp_path)

    assert exitcode == 1
    assert logs.startswith("Timeout")
    assert pid_file.exists(), "script never got far enough to spawn its child"
    grandchild = int(pid_file.read_text())

    # reparenting to init and reaping is not instantaneous — poll briefly
    deadline = time.monotonic() + 10
    while _process_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _process_alive(grandchild), f"grandchild {grandchild} survived the timeout kill"


# ---------------------------------------------------------------------------
# what the model is told about the aborted run
# ---------------------------------------------------------------------------


def test_output_printed_before_the_kill_is_surfaced(tmp_path):
    """A timed-out run has no traceback; its prints are the only clue where it hung."""
    code = "print('reached step 3', flush=True)\nwhile True:\n    pass\n"

    exitcode, logs, _ = _execute(code, tmp_path)

    assert exitcode == 1
    assert PARTIAL_OUTPUT_HEADER.strip() in logs
    assert "reached step 3" in logs


def test_timeout_notice_survives_capping_of_a_huge_partial_log(tmp_path):
    """The notice sits at the HEAD and the cap keeps the TAIL — order matters.

    Capping `notice + output` as one string would silently eat the one line that
    explains why the run failed, leaving the model to read a truncated dump and
    conclude the script simply crashed.
    """
    code = "print('x' * 40000, flush=True)\nwhile True:\n    pass\n"

    exitcode, logs, _ = _execute(code, tmp_path)

    assert exitcode == 1
    assert logs.startswith("Timeout")
    assert len(logs) <= MAX_FAILURE_LOG_CHARS


# ---------------------------------------------------------------------------
# the rewrite must not disturb runs that finish
# ---------------------------------------------------------------------------


def test_successful_run_still_returns_stdout(tmp_path):
    exitcode, logs, _ = _execute("print('hello from the box')\n", tmp_path)

    assert exitcode == 0
    assert "hello from the box" in logs


def test_failing_run_still_returns_its_traceback(tmp_path):
    exitcode, logs, _ = _execute("raise ValueError('boom')\n", tmp_path)

    assert exitcode != 0
    assert "ValueError: boom" in logs
