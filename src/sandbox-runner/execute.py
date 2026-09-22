"""Run user code inside a lease working directory. Must not import bisheng."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import time

from files import snapshot_tree
from leases import Lease, LeaseStore
from logutil import get_logger

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
)

# Memory / nproc / CPU seconds — compose mem_limit is asserted separately.
_RLIMIT_AS = 2 * 1024 * 1024 * 1024
_RLIMIT_NPROC = 256
_RLIMIT_CPU = 600


def _child_env(work_dir: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOW if key in os.environ}
    env["HOME"] = work_dir
    env["TMPDIR"] = work_dir
    env["TMP"] = work_dir
    env["TEMP"] = work_dir
    env["XDG_CACHE_HOME"] = work_dir
    env["XDG_CONFIG_HOME"] = work_dir
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
        try:
            os.setgid(uid)
        except OSError:
            pass
        os.setuid(uid)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _chown_tree(path: str, uid: int, gid: int) -> None:
    os.chown(path, uid, gid)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            os.chown(os.path.join(root, name), uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def handle_exec(store: LeaseStore, lease: Lease, payload: dict) -> dict:
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
    with lease.lock:
        lease.pre_exec_snapshot = snapshot_tree(lease.work_dir)
        lease.copy_out_allowed = False
        script = os.path.join(lease.work_dir, "_run.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(code)
        cmd = [sys.executable, script] if str(lang).startswith("python") else ["sh", "-c", code]
        started = time.monotonic()
        dropped = os.geteuid() == 0 and lease.uid != 0
        if dropped:
            _chown_tree(lease.work_dir, lease.uid, lease.uid)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=lease.work_dir,
                env=_child_env(lease.work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
                preexec_fn=lambda uid=lease.uid: _preexec(uid),
            )
            timed_out = False
            try:
                stdout, stderr = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc)
                stdout, stderr = proc.communicate()
        finally:
            if dropped:
                try:
                    _chown_tree(lease.work_dir, 0, 0)
                except OSError:
                    pass
        duration_ms = int((time.monotonic() - started) * 1000)
        exitcode = 124 if timed_out else int(proc.returncode if proc.returncode is not None else 1)
        try:
            os.remove(script)
        except OSError:
            pass
        if exitcode == 137:
            _log.error(
                "exec oom session_id=%s duration_ms=%s stdout_bytes=%s stderr_bytes=%s",
                lease.session_id,
                duration_ms,
                len(stdout or ""),
                len(stderr or ""),
            )
            store.delete(lease.session_id, lease.lease_token, force=True, reason="oom")
            return {
                "exitcode": 137,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "duration_ms": duration_ms,
            }
        if not timed_out:
            lease.copy_out_allowed = True
        _log.info(
            "exec done session_id=%s exitcode=%s duration_ms=%s stdout_bytes=%s stderr_bytes=%s timed_out=%s",
            lease.session_id,
            exitcode,
            duration_ms,
            len(stdout or ""),
            len(stderr or ""),
            timed_out,
        )
        return {
            "exitcode": exitcode,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "duration_ms": duration_ms,
        }
