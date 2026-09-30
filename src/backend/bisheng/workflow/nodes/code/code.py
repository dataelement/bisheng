"""Workflow Code node — chroot-jailed execution.

Security patch payload for BiSheng v2.0.0 - v2.6.0. The original node executed
user code inside the backend process at parse time and again in ``_run``. Here
the backend only does a static AST check (see ``code_parse.CodeParser``); the
user code runs in a chroot jail, as a throwaway ordinary uid, with the code and
its input passed over stdin and the result read back over a pipe. Nothing in
the jail is writable, and the backend never reads a file from it.

If the jail is missing, the process is not root, or ``chroot`` fails, execution
fails closed — it never falls back to in-process ``exec``.

Stays within Python 3.10 syntax and the standard library so the same file drops
onto every image from v2.0.0 (Python 3.10) to v2.6.0 (Python 3.11).
"""

import json
import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.code.code_parse import RUNNER_SOURCE, CodeParser

# Jail layout, baked into the image by build-code-root.sh.
JAIL_ROOT = "/opt/code-root"
JAIL_PYTHON = "/usr/bin/python"
JAIL_PATH = "/usr/bin:/bin"

# Per-run identity pool. Markers live OUTSIDE the jail, owned by root, so the
# jailed user cannot touch them.
UID_MIN = 20000
UID_MAX = 29999
MARKER_DIR = "/var/run/bisheng-code-uids"

TIMEOUT_SECONDS = 30
STDOUT_LIMIT = 4 * 1024 * 1024  # 4 MiB
STDERR_LIMIT = 4096  # last 4 KiB kept for error messages

_JAIL_REQUIRED = "the Code node must run in a container that has the sandbox jail at %s and runs as root" % JAIL_ROOT

_REAP_SOURCE = "import os\ntry:\n    os.kill(-1, 9)\nexcept (ProcessLookupError, PermissionError):\n    pass\n"


class CodeNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._code_input = self.node_params["code_input"]
        self._code = self.node_params["code"]
        self._code_output = self.node_params["code_output"]

        # Static check at build time, same failure timing as before.
        # No import, no exec.
        self._parse_code(self._code)

    def handle_input(self, user_input: dict) -> Any:
        self.node_params.update(user_input)
        self._code_input = self.node_params["code_input"]
        self._code_output = self.node_params["code_output"]
        self._code = self.node_params["code"]

    def _parse_code(self, code: str):
        try:
            CodeParser(code).parse_code()
        except Exception as e:
            raise Exception(f"CodeNode {self.name} exec code error: " + str(e))

    def _run(self, unique_id: str):
        # handle_input may have replaced self._code since build time.
        self._parse_code(self._code)
        main_params = self._parse_code_input()
        main_ret = self._run_in_jail(self._code, main_params)
        return self._parse_code_output(main_ret)

    def parse_log(self, unique_id: str, result: dict):
        return [
            [
                {
                    "key": "code_input",
                    "value": self._parse_code_input(),
                    "type": "params",
                },
                {"key": "code_output", "value": result, "type": "params"},
            ]
        ]

    def _parse_code_input(self) -> dict:
        ret = {}
        for one in self._code_input:
            if one["type"] == "ref":
                ret[one["key"]] = self.get_other_node_variable(one["value"])
            else:
                ret[one["key"]] = one["value"]
        return ret

    def _parse_code_output(self, result: dict) -> dict:
        if not isinstance(result, dict):
            raise Exception(f"CodeNode {self.name} main function output must be dict")
        ret = {}
        for one in self._code_output:
            if one["key"] not in result:
                raise Exception(f"CodeNode {self.name} main function output must have key {one['key']}")
            ret[one["key"]] = result.get(one["key"])
        return ret

    # --- jailed execution ----------------------------------------------------

    def _fail(self, reason: str):
        return Exception(f"CodeNode {self.name} exec code error: {reason}")

    def _run_in_jail(self, code: str, main_params: dict) -> dict:
        _require_jail(self._fail)
        try:
            payload = json.dumps({"code": code, "input": main_params}, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as e:
            raise self._fail(f"input is not JSON-serializable: {e}")

        uid = _acquire_uid()
        if uid is None:
            raise self._fail(f"no free uid in {UID_MIN}-{UID_MAX}")
        try:
            outcome = _execute(uid, payload)
        finally:
            _release_uid(uid)

        stdout, stderr, returncode, timed_out, over_limit = outcome
        tail = stderr.decode("utf-8", "replace").strip()
        if timed_out:
            raise self._fail(f"timed out after {TIMEOUT_SECONDS}s")
        if over_limit:
            raise self._fail(f"output exceeded {STDOUT_LIMIT} bytes")
        if returncode != 0:
            raise self._fail(tail or f"exit code {returncode}")
        try:
            return json.loads(stdout.decode("utf-8"))
        except ValueError as e:
            raise self._fail(f"bad result: {e}")


# --- jail helpers (module level: shared by all node instances and threads) ---


def _chroot_path() -> str:
    # Popen resolves a bare command against the env it is given. That env's
    # PATH is only /usr/bin:/bin, so the jailed interpreter cannot see sbin.
    # On Debian, chroot is /usr/sbin/chroot, which the parent can still find.
    return shutil.which("chroot") or ""


def _require_jail(fail):
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise fail(_JAIL_REQUIRED)
    if not os.path.exists(os.path.join(JAIL_ROOT, JAIL_PYTHON.lstrip("/"))):
        raise fail(_JAIL_REQUIRED)
    if not _chroot_path():
        raise fail(_JAIL_REQUIRED)


def _jail_argv(uid: int, *python_args: str) -> list:
    return [
        _chroot_path(),
        "--userspec=%d:%d" % (uid, uid),
        "--groups=%d" % uid,
        JAIL_ROOT,
        JAIL_PYTHON,
        *python_args,
    ]


def _execute(uid: int, payload: bytes):
    env = {"PATH": JAIL_PATH, "LANG": "C.UTF-8"}
    if os.environ.get("TZ"):
        env["TZ"] = os.environ["TZ"]
    proc = subprocess.Popen(
        _jail_argv(uid, "-I", "-S", "-B", "-X", "utf8", "-c", RUNNER_SOURCE),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd="/",
        close_fds=True,
        start_new_session=True,
    )
    try:
        stdout, stderr, timed_out, over_limit = _communicate(proc, payload)
        if timed_out or over_limit:
            _killpg(proc.pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _killpg(proc.pid)
            proc.wait()
            timed_out = True
        return stdout, stderr, proc.returncode, timed_out, over_limit
    finally:
        if proc.poll() is None:
            _killpg(proc.pid)
            proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            _safe_close(stream)


def _communicate(proc, payload: bytes):
    """Feed stdin and drain stdout/stderr with bounded memory.

    Stops on: both output pipes at EOF, the wall-clock deadline, stdout over its
    cap, or the main child having exited with nothing left to read (an escaped
    descendant may keep the pipes open forever; uid reaping deals with it).
    """
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "out")
    sel.register(proc.stderr, selectors.EVENT_READ, "err")
    view = memoryview(payload)
    if view:
        os.set_blocking(proc.stdin.fileno(), False)
        sel.register(proc.stdin, selectors.EVENT_WRITE, "in")
    else:
        _safe_close(proc.stdin)

    out = bytearray()
    err = bytearray()
    timed_out = False
    over_limit = False
    deadline = time.monotonic() + TIMEOUT_SECONDS

    try:
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = sel.select(min(remaining, 0.5))
            for key, _ in events:
                if key.data == "in":
                    try:
                        written = os.write(key.fileobj.fileno(), view[:65536])
                        view = view[written:]
                        done = not view
                    except BlockingIOError:
                        done = False
                    except BrokenPipeError:
                        done = True
                    if done:
                        sel.unregister(key.fileobj)
                        _safe_close(key.fileobj)
                    continue
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    sel.unregister(key.fileobj)
                    _safe_close(key.fileobj)
                elif key.data == "out":
                    out.extend(data)
                    if len(out) > STDOUT_LIMIT:
                        over_limit = True
                else:
                    err.extend(data)
                    if len(err) > STDERR_LIMIT:
                        del err[:-STDERR_LIMIT]
            if over_limit:
                break
            if not events and proc.poll() is not None:
                break
    finally:
        sel.close()
    return bytes(out), bytes(err), timed_out, over_limit


# --- uid pool ----------------------------------------------------------------


def _acquire_uid():
    """Claim a free uid by publishing a marker atomically; None if exhausted.

    The marker records "<pid> <starttime>" of the claiming process. It is
    written to a private temp file first and then hard-linked into place, so a
    reader never sees an empty or half-written marker.
    """
    os.makedirs(MARKER_DIR, mode=0o700, exist_ok=True)
    pid = os.getpid()
    owner = "%d %d" % (pid, _proc_starttime(pid) or 0)
    tmp = os.path.join(MARKER_DIR, ".claim-%d-%d" % (pid, threading.get_ident()))
    with open(tmp, "w") as fh:
        fh.write(owner)
    try:
        for uid in range(UID_MIN, UID_MAX + 1):
            marker = os.path.join(MARKER_DIR, str(uid))
            if _try_link(tmp, marker):
                return uid
            if _marker_is_stale(marker) and _reap_uid(uid):
                _remove(marker)
                if _try_link(tmp, marker):
                    return uid
        return None
    finally:
        _remove(tmp)


def _release_uid(uid: int):
    """Free a uid only after confirming no process is left under it."""
    if _reap_uid(uid):
        _remove(os.path.join(MARKER_DIR, str(uid)))
    # Otherwise keep the marker: the uid stays quarantined and is never handed
    # out again while something still runs under it.


def _try_link(src: str, dst: str) -> bool:
    try:
        os.link(src, dst)
        return True
    except FileExistsError:
        return False


def _marker_is_stale(marker: str) -> bool:
    try:
        with open(marker) as fh:
            pid_str, _, start_str = fh.read().strip().partition(" ")
        pid, recorded_start = int(pid_str), int(start_str)
    except FileNotFoundError:
        return False  # released meanwhile; the next link attempt decides
    except (OSError, ValueError):
        return True
    current_start = _proc_starttime(pid)
    return current_start is None or current_start != recorded_start


def _reap_uid(uid: int) -> bool:
    """Kill every process running as ``uid``; True once none remain.

    killpg only reaches the original process group, and a child that calls
    setsid escapes it. kill(-1) issued *as that uid* reaches every process the
    kernel lets it signal: same uid, same PID namespace, caller excluded.
    """
    try:
        subprocess.run(
            _jail_argv(uid, "-I", "-S", "-B", "-c", _REAP_SOURCE),
            env={"PATH": JAIL_PATH, "LANG": "C.UTF-8"},
            cwd="/",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for _ in range(20):
        if not _uid_has_live_process(uid):
            return True
        time.sleep(0.05)
    return False


def _uid_has_live_process(uid: int) -> bool:
    """True if a non-zombie process runs as ``uid`` in this PID namespace."""
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        state, owner = None, None
        try:
            with open("/proc/%s/status" % entry) as fh:
                for line in fh:
                    if line.startswith("State:"):
                        state = line.split()[1]
                    elif line.startswith("Uid:"):
                        owner = int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
        if owner == uid and state != "Z":
            return True
    return False


def _proc_starttime(pid: int):
    """Start time (clock ticks) from /proc/<pid>/stat, or None if pid is gone."""
    try:
        with open("/proc/%d/stat" % pid) as fh:
            data = fh.read()
    except OSError:
        return None
    # comm (field 2) is parenthesised and may contain spaces; skip past it.
    rparen = data.rfind(")")
    if rparen == -1:
        return None
    fields = data[rparen + 2 :].split()
    try:
        return int(fields[19])  # starttime is field 22 (1-based)
    except (IndexError, ValueError):
        return None


def _killpg(pid: int):
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def _remove(path: str):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _safe_close(stream):
    if stream is None:
        return
    try:
        stream.close()
    except OSError:
        pass
