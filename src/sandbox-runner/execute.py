"""Run user code inside a lease working directory. Must not import bisheng."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable

from files import snapshot_tree
from leases import Lease, LeaseStore, UnknownLeaseError
from logutil import get_logger
from procutil import chown_tree, kill_group

_log = get_logger()

_ENV_ALLOW = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TERM",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    # Image-wide matplotlib defaults (CJK font); see docker/bisheng-sandbox.
    "MATPLOTLIBRC",
)

# Memory / nproc / CPU seconds — compose mem_limit is asserted separately.
_RLIMIT_AS = 2 * 1024 * 1024 * 1024
_RLIMIT_NPROC = 256
_RLIMIT_CPU = 600

# After SIGKILL on timeout, how long to wait for the pipes to close.
_KILL_GRACE_S = 5.0

# Exit code reported for a wall-clock timeout (same as coreutils `timeout`).
TIMEOUT_EXITCODE = 124
# Exit code reported when the child could not be started at all.
START_FAILED_EXITCODE = 126

# Memory cgroup counters of this container: v2 first, then v1.
_OOM_EVENT_PATHS = (
    "/sys/fs/cgroup/memory.events",
    "/sys/fs/cgroup/memory/memory.oom_control",
)


def _child_env(work_dir: str, home_dir: str | None = None) -> dict[str, str]:
    home = home_dir or work_dir
    env = {key: os.environ[key] for key in _ENV_ALLOW if key in os.environ}
    env["HOME"] = home
    env["TMPDIR"] = work_dir
    env["TMP"] = work_dir
    env["TEMP"] = work_dir
    env["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    env["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["LC_CTYPE"] = "C.UTF-8"
    env.pop("token", None)
    env.pop("lease_token", None)
    for key in list(env):
        upper = key.upper()
        if "MINIO" in upper or "MYSQL" in upper or "TOKEN" in upper:
            env.pop(key, None)
    return env


def _preexec(uid: int = 65534) -> None:
    # Runs in the forked child before exec: no logging, no locks.
    for res, limit in (
        (resource.RLIMIT_AS, _RLIMIT_AS),
        (resource.RLIMIT_NPROC, _RLIMIT_NPROC),
        (resource.RLIMIT_CPU, _RLIMIT_CPU),
    ):
        try:
            resource.setrlimit(res, (limit, limit))
        except (OSError, ValueError):
            continue
    if os.geteuid() == 0:
        # Drop root's supplementary groups (notably gid 0) before changing ids.
        # Fails closed: if this raises, the child never runs.
        os.setgroups([])
        try:
            os.setgid(uid)
        except OSError:
            pass
        os.setuid(uid)


class _RusagePopen(subprocess.Popen):
    """Popen that reaps with wait4 so the child's own CPU time is known.

    ``getrusage(RUSAGE_CHILDREN)`` is process-wide and mixes in the children of
    other sessions that finish in the same window; wait4 is per child.
    """

    rusage: resource.struct_rusage | None = None

    def _try_wait(self, wait_flags):
        try:
            pid, sts, usage = os.wait4(self.pid, wait_flags)
        except ChildProcessError:
            # Same fallback as CPython: someone else reaped the child.
            return (self.pid, 0)
        if pid == self.pid:
            self.rusage = usage
        return (pid, sts)


def read_oom_kills(paths: Iterable[str] = _OOM_EVENT_PATHS) -> int | None:
    """Return the memory cgroup's ``oom_kill`` counter, or None if unreadable."""
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) == 2 and parts[0] == "oom_kill":
                        return int(parts[1])
        except (OSError, ValueError):
            continue
    return None


def _children_cpu_s() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def classify_exit(
    returncode: int | None,
    *,
    timed_out: bool,
    kill_requested: bool = False,
    cpu_s: float | None = None,
    cpu_limit_s: float = _RLIMIT_CPU,
    oom_delta: int | None = None,
) -> tuple[int, str | None]:
    """Map a Popen result to (exitcode, killed_reason) per the runner contract.

    exitcode is never negative: death by signal N is 128+N. killed_reason is
    "timeout" | "memory" | "cpu" | "signal" | None.
    """
    if timed_out:
        return TIMEOUT_EXITCODE, "timeout"
    if returncode is None:
        return 1, None
    if returncode >= 0:
        return int(returncode), None
    sig = -int(returncode)
    exitcode = 128 + sig
    if kill_requested:
        return exitcode, "signal"
    if sig == signal.SIGXCPU:
        return exitcode, "cpu"
    if sig == signal.SIGKILL:
        if cpu_s is not None and cpu_s >= cpu_limit_s - 1:
            return exitcode, "cpu"
        if oom_delta is None or oom_delta > 0:
            return exitcode, "memory"
    return exitcode, "signal"


def _result(
    exitcode: int, stdout: str, stderr: str, duration_ms: int, killed_reason: str | None
) -> dict:
    return {
        "exitcode": exitcode,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "duration_ms": duration_ms,
        "killed_reason": killed_reason,
    }


def handle_exec(
    store: LeaseStore,
    lease: Lease,
    payload: dict,
    *,
    oom_reader: Callable[[], int | None] = read_oom_kills,
    killpg: Callable[[int, int], None] | None = None,
    kill_grace_s: float = _KILL_GRACE_S,
) -> dict:
    """Run one exec on ``lease``. Blocking: call it from a worker thread.

    Raises UnknownLeaseError only when the lease was deleted before the child
    started; every outcome after that (including a failed kill) is a result dict.
    """
    code = payload.get("code") or ""
    lang = payload.get("lang") or "python"
    timeout_s = float(payload.get("timeout_s") or 600)
    _log.info(
        "exec start session_id=%s lang=%s timeout_s=%s code_bytes=%s",
        lease.session_id,
        lang,
        timeout_s,
        len(code.encode("utf-8")),
    )
    with store.locked(lease):
        if lease.deleted:
            raise UnknownLeaseError()
        lease.pre_exec_snapshot = snapshot_tree(lease.work_dir)
        lease.copy_out_allowed = False
        script = os.path.join(lease.work_dir, "_run.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(code)
        # Copy-in skips empty directories, so the zones the tool description promises
        # must be created here. Done while the tree is still root-owned (before the chown).
        for zone in ("output", "scratch"):
            os.makedirs(os.path.join(lease.work_dir, zone), exist_ok=True)
        cmd = (
            [sys.executable, script]
            if str(lang).startswith("python")
            else ["sh", "-c", code]
        )
        started = time.monotonic()
        dropped = os.geteuid() == 0 and lease.uid != 0
        oom_before = oom_reader()
        cpu_before = _children_cpu_s()
        timed_out = False
        kill_failed = False
        stdout = stderr = ""
        try:
            if dropped:
                chown_tree(lease.work_dir, lease.uid, lease.uid)
            with lease.state_lock:
                if lease.deleted:
                    raise UnknownLeaseError()
                try:
                    proc = _RusagePopen(
                        cmd,
                        cwd=lease.work_dir,
                        env=_child_env(lease.work_dir, lease.home_dir),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        start_new_session=True,
                        preexec_fn=lambda uid=lease.uid: _preexec(uid),
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    _log.error(
                        "exec start failed session_id=%s error=%r",
                        lease.session_id,
                        exc,
                    )
                    duration_ms = int((time.monotonic() - started) * 1000)
                    return _result(
                        START_FAILED_EXITCODE,
                        "",
                        f"failed to start: {exc}",
                        duration_ms,
                        None,
                    )
                lease.proc = proc
            try:
                stdout, stderr = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_group(
                    proc, session_id=lease.session_id, reason="timeout", killpg=killpg
                )
                # A setsid escape holding the pipes would keep communicate waiting.
                store.kill_uid_processes(lease, reason="timeout")
                try:
                    stdout, stderr = proc.communicate(timeout=kill_grace_s)
                except subprocess.TimeoutExpired:
                    kill_failed = True
                    _close_pipes(proc)
            # The exec is over: nothing it started may keep running as this
            # session (background jobs, setsid escapes) into the next exec or
            # past DELETE, where the uid could be reissued.
            _kill_leftovers(store, lease, proc, killpg)
        finally:
            with lease.state_lock:
                lease.proc = None
            if dropped:
                try:
                    chown_tree(lease.work_dir, 0, 0)
                except OSError as exc:
                    _log.warning(
                        "reclaim work dir failed session_id=%s error=%r",
                        lease.session_id,
                        exc,
                    )
        if kill_failed:
            # The child may still be running as lease.uid: never reissue that uid.
            _log.error(
                "exec kill failed session_id=%s pid=%s uid=%s; process may still be running",
                lease.session_id,
                proc.pid,
                lease.uid,
            )
            store.quarantine_uid(lease.uid)
        duration_ms = int((time.monotonic() - started) * 1000)
        cpu_s = _proc_cpu_s(proc, cpu_before)
        oom_after = oom_reader() if oom_before is not None else None
        oom_delta = (
            oom_after - oom_before
            if oom_before is not None and oom_after is not None
            else None
        )
        exitcode, killed_reason = classify_exit(
            proc.returncode,
            timed_out=timed_out,
            kill_requested=lease.kill_requested,
            cpu_s=cpu_s,
            oom_delta=oom_delta,
        )
        try:
            os.remove(script)
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log.warning(
                "remove script failed session_id=%s error=%r", lease.session_id, exc
            )
        if killed_reason == "memory":
            # The session survives an OOM kill: only this process died.
            _log.error(
                "exec oom session_id=%s duration_ms=%s stdout_bytes=%s stderr_bytes=%s",
                lease.session_id,
                duration_ms,
                len(stdout or ""),
                len(stderr or ""),
            )
        if not timed_out:
            lease.copy_out_allowed = True
        _log.info(
            "exec done session_id=%s exitcode=%s killed_reason=%s duration_ms=%s stdout_bytes=%s "
            "stderr_bytes=%s timed_out=%s",
            lease.session_id,
            exitcode,
            killed_reason,
            duration_ms,
            len(stdout or ""),
            len(stderr or ""),
            timed_out,
        )
        return _result(exitcode, stdout, stderr, duration_ms, killed_reason)


def _kill_leftovers(
    store: LeaseStore,
    lease: Lease,
    proc: subprocess.Popen,
    killpg: Callable[[int, int], None] | None,
) -> None:
    """Kill what the exec left behind: its process group, then the session uid."""
    send = killpg or os.killpg
    try:
        send(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        _log.warning(
            "kill leftover group failed session_id=%s pid=%s error=%r",
            lease.session_id,
            proc.pid,
            exc,
        )
    store.kill_uid_processes(lease, reason="exec_end")


def _proc_cpu_s(proc: subprocess.Popen, cpu_before: float) -> float | None:
    usage = getattr(proc, "rusage", None)
    if usage is not None:
        return usage.ru_utime + usage.ru_stime
    if proc.returncode is None:
        return None
    # Child was reaped elsewhere: fall back to the process-wide children delta.
    return _children_cpu_s() - cpu_before


def _close_pipes(proc: subprocess.Popen) -> None:
    for stream in (proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError as exc:
            _log.warning("close pipe failed pid=%s error=%r", proc.pid, exc)
