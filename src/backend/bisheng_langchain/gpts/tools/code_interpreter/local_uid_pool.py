"""Per-run uid pool for the isolated LocalExecutor.

Each run claims one uid in ``UID_MIN``-``UID_MAX`` by atomically publishing a
marker file; nothing else ever runs under that uid while the marker exists.
When a run ends, every process of the uid is killed (``kill(-1)`` issued *as*
the uid) and ``/proc`` is checked before the uid goes back to the pool. A uid
whose processes could not be confirmed dead keeps its marker and is never
handed out again by this process.

Markers record ``<pid> <starttime>`` of the claiming worker process, so a marker
left by a crashed worker is recognised as stale (dead pid, or pid reused) and
reclaimed, while markers of other live workers on the same host are left alone.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

from loguru import logger

UID_MIN = 30000
UID_MAX = 39999
MARKER_DIR = "/var/run/bisheng-local-uids"
_LOCK_NAME = ".lock"

# Runs as the target uid. Refuses to signal anything unless it really is that
# uid: a wrong identity here would make kill(-1) hit the whole container.
_REAP_SOURCE = (
    "import os, sys\n"
    "uid = int(sys.argv[1])\n"
    f"if not ({UID_MIN} <= uid <= {UID_MAX}) or os.getuid() != uid or os.geteuid() != uid:\n"
    "    sys.exit(2)\n"
    "try:\n"
    "    os.kill(-1, 9)\n"
    "except (ProcessLookupError, PermissionError):\n"
    "    pass\n"
)


def proc_starttime(pid: int) -> int | None:
    """Start time (clock ticks) from /proc/<pid>/stat, or None if pid is gone."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
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


def live_processes_by_uid() -> dict[int, list[int]]:
    """Non-zombie processes in this PID namespace, grouped by real uid."""
    result: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return result
    for entry in entries:
        if not entry.isdigit():
            continue
        state, owner = None, None
        try:
            with open(f"/proc/{entry}/status") as fh:
                for line in fh:
                    if line.startswith("State:"):
                        state = line.split()[1]
                    elif line.startswith("Uid:"):
                        owner = int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
        if owner is not None and state != "Z":
            result.setdefault(owner, []).append(int(entry))
    return result


def uid_has_live_process(uid: int) -> bool:
    return uid in live_processes_by_uid()


def reap_uid(uid: int) -> bool:
    """Kill every process running as ``uid``; True once none remain.

    killpg only reaches the original process group, and a child that calls
    setsid escapes it. kill(-1) issued as that uid reaches every process the
    kernel lets it signal: same uid, same PID namespace, caller excluded.
    """
    if not UID_MIN <= uid <= UID_MAX:
        raise ValueError(f"uid {uid} is outside the pool")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", _REAP_SOURCE, str(uid)],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            cwd="/",
            user=uid,
            group=uid,
            extra_groups=[],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("local isolation: reap helper for uid {} failed to run", uid)
        return False
    if proc.returncode != 0:
        logger.error("local isolation: reap helper for uid {} exited {}", uid, proc.returncode)
        return False
    for _ in range(40):
        if not uid_has_live_process(uid):
            return True
        time.sleep(0.05)
    return False


def remove_owned_run_dirs(run_root: str, uid: int) -> None:
    """Delete every entry directly under ``run_root`` owned by ``uid``.

    A run dir left by a killed worker is owned by its uid; the next run that
    claims the same uid must not be able to read it.
    """
    try:
        names = os.listdir(run_root)
    except FileNotFoundError:
        return
    for name in names:
        path = os.path.join(run_root, name)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if st.st_uid != uid:
            continue
        _remove_entry(path, st)


def _remove_entry(path: str, st: os.stat_result) -> None:
    try:
        if stat.S_ISDIR(st.st_mode):
            # rmtree does not follow symlinks inside the tree.
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("local isolation: could not remove leftover {}", path)


def _marker_path(marker_dir: str, uid: int) -> str:
    return os.path.join(marker_dir, str(uid))


def _marker_is_stale(marker: str) -> bool:
    try:
        with open(marker) as fh:
            pid_str, _, start_str = fh.read().strip().partition(" ")
        pid, recorded_start = int(pid_str), int(start_str)
    except FileNotFoundError:
        return False  # released meanwhile; the next link attempt decides
    except (OSError, ValueError):
        return True
    current_start = proc_starttime(pid)
    return current_start is None or current_start != recorded_start


def _try_link(src: str, dst: str) -> bool:
    try:
        os.link(src, dst)
        return True
    except FileExistsError:
        return False


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def ensure_marker_dir(marker_dir: str = MARKER_DIR) -> None:
    os.makedirs(marker_dir, mode=0o700, exist_ok=True)
    os.chmod(marker_dir, 0o700)


@contextmanager
def _pool_lock(marker_dir: str):
    """Exclusive across threads and worker processes on this host.

    Claiming a uid and reclaiming stale ones must not interleave: a sweep that
    judged a marker stale would otherwise delete the run dir another process
    created right after re-claiming that uid.
    """
    fd = os.open(os.path.join(marker_dir, _LOCK_NAME), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def acquire(run_root: str, marker_dir: str = MARKER_DIR) -> int | None:
    """Claim a free uid; None if the pool is exhausted.

    The marker is written to a private temp file first and then hard-linked
    into place: the link is atomic and fails if the target exists, so exactly
    one claimant wins and nobody ever reads a half-written marker.
    """
    ensure_marker_dir(marker_dir)
    pid = os.getpid()
    owner = f"{pid} {proc_starttime(pid) or 0}"
    tmp = os.path.join(marker_dir, f".claim-{pid}-{threading.get_ident()}")
    with open(tmp, "w") as fh:
        fh.write(owner)
    try:
        with _pool_lock(marker_dir):
            for uid in range(UID_MIN, UID_MAX + 1):
                marker = _marker_path(marker_dir, uid)
                if not _try_link(tmp, marker):
                    if not (_marker_is_stale(marker) and reap_uid(uid)):
                        continue
                    remove_owned_run_dirs(run_root, uid)
                    _unlink(marker)
                    if not _try_link(tmp, marker):
                        continue
                remove_owned_run_dirs(run_root, uid)
                return uid
            return None
    finally:
        _unlink(tmp)


def free(uid: int, run_root: str, marker_dir: str = MARKER_DIR) -> None:
    """Return ``uid`` to the pool. The caller must already have confirmed the reap."""
    remove_owned_run_dirs(run_root, uid)
    _unlink(_marker_path(marker_dir, uid))


def held_uids(marker_dir: str = MARKER_DIR) -> set[int]:
    """Uids whose marker belongs to a live process (this or another worker)."""
    held: set[int] = set()
    try:
        names = os.listdir(marker_dir)
    except FileNotFoundError:
        return held
    for name in names:
        if not name.isdigit():
            continue
        if not _marker_is_stale(os.path.join(marker_dir, name)):
            held.add(int(name))
    return held


def sweep(run_root: str, marker_dir: str = MARKER_DIR) -> None:
    """Reclaim what crashed workers left: stale markers and their run dirs.

    Markers of live workers are kept, and so are the run dirs owned by their
    uids. Stale markers whose uid still has processes are reaped first; if the
    reap cannot be confirmed the marker stays.
    """
    ensure_marker_dir(marker_dir)
    with _pool_lock(marker_dir):
        _sweep_locked(run_root, marker_dir)


def _sweep_locked(run_root: str, marker_dir: str) -> None:
    names = os.listdir(marker_dir)
    for name in names:
        marker = os.path.join(marker_dir, name)
        if name.startswith(".claim-"):
            claim_pid = name.split("-")[1] if name.count("-") >= 2 else ""
            if not claim_pid.isdigit() or proc_starttime(int(claim_pid)) is None:
                _unlink(marker)
            continue
        if not name.isdigit() or not _marker_is_stale(marker):
            continue
        uid = int(name)
        if not UID_MIN <= uid <= UID_MAX:
            continue
        if uid_has_live_process(uid) and not reap_uid(uid):
            logger.error("local isolation: stale uid {} still has processes; kept quarantined", uid)
            continue
        remove_owned_run_dirs(run_root, uid)
        _unlink(marker)
        logger.info("local isolation: reclaimed stale uid {}", uid)

    held = held_uids(marker_dir)
    try:
        entries = os.listdir(run_root)
    except FileNotFoundError:
        return
    for name in entries:
        path = os.path.join(run_root, name)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if UID_MIN <= st.st_uid <= UID_MAX and st.st_uid not in held:
            logger.info("local isolation: removing orphaned run dir {}", path)
            _remove_entry(path, st)
