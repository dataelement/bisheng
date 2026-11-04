"""Process-group kill and tree ownership helpers. Must not import bisheng."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable

from logutil import get_logger

_log = get_logger()


def kill_group(
    proc: subprocess.Popen,
    *,
    session_id: str = "",
    reason: str = "",
    killpg: Callable[[int, int], None] | None = None,
) -> bool:
    """SIGKILL the child's process group; fall back to the child itself.

    Never raises. Returns True when a kill signal was delivered to the group or
    the child. ``start_new_session=True`` makes the child a group leader, so its
    pid is the pgid; ``os.getpgid`` is not used because it fails once the child
    is a zombie.
    """
    send = killpg or os.killpg
    try:
        send(proc.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        # Group already gone: nothing left to kill.
        return True
    except OSError as exc:
        _log.warning(
            "kill group failed session_id=%s pid=%s reason=%s error=%r; falling back to proc.kill",
            session_id,
            proc.pid,
            reason,
            exc,
        )
    try:
        proc.kill()
        return True
    except ProcessLookupError:
        return True
    except OSError as exc:
        _log.error(
            "kill process failed session_id=%s pid=%s reason=%s error=%r",
            session_id,
            proc.pid,
            reason,
            exc,
        )
        return False


# Helper run as the session uid: kill(-1) reaches every process that uid may
# signal (all of its own processes, never PID 1 or the helper itself), needs no
# CAP_KILL and also catches processes that left the group with setsid.
_KILL_UID_CODE = "import os, signal\ntry:\n    os.kill(-1, signal.SIGKILL)\nexcept ProcessLookupError:\n    pass\n"
_KILL_UID_TIMEOUT_S = 10.0


def kill_uid(
    uid: int,
    *,
    session_id: str = "",
    reason: str = "",
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> bool:
    """SIGKILL every process running as ``uid``. Never raises.

    Must be called by root. Returns True when the helper ran to completion.
    The helper is started through subprocess (not os.fork) because the runner
    is multi-threaded.
    """
    runner = run or subprocess.run
    try:
        done = runner(
            [sys.executable, "-I", "-S", "-c", _KILL_UID_CODE],
            user=uid,
            group=uid,
            extra_groups=[],
            env={},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=_KILL_UID_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _log.error(
            "kill uid failed session_id=%s uid=%s reason=%s error=%r",
            session_id,
            uid,
            reason,
            exc,
        )
        return False
    if done.returncode == -signal.SIGKILL:
        # Another helper for the same uid (exec end racing DELETE) ran kill(-1)
        # and took this one down with the session's processes; that kill did
        # the job. Callers that must be sure rescan /proc afterwards.
        _log.info(
            "kill uid helper killed by a concurrent kill session_id=%s uid=%s reason=%s",
            session_id,
            uid,
            reason,
        )
        return True
    if done.returncode != 0:
        _log.error(
            "kill uid failed session_id=%s uid=%s reason=%s exitcode=%s stderr=%r",
            session_id,
            uid,
            reason,
            done.returncode,
            (done.stderr or b"")[-500:],
        )
        return False
    return True


def uid_processes(uid: int, *, proc_root: str = "/proc") -> list[int]:
    """Pids of live (non-zombie) processes whose real/effective/saved/fs uid is ``uid``.

    Zombies are skipped: they hold no resources and wait only for a reaper.
    A process that exits while it is being read is skipped too.
    """
    found: list[int] = []
    try:
        entries = os.listdir(proc_root)
    except OSError as exc:
        _log.warning("list processes failed proc_root=%s error=%r", proc_root, exc)
        return found
    for name in entries:
        if not name.isdigit():
            continue
        try:
            with open(
                os.path.join(proc_root, name, "status"),
                encoding="utf-8",
                errors="replace",
            ) as fh:
                status = fh.read()
        except OSError:
            continue
        uids: list[int] = []
        state = ""
        for line in status.splitlines():
            if line.startswith("Uid:"):
                uids = [int(part) for part in line.split()[1:] if part.isdigit()]
            elif line.startswith("State:"):
                state = (line.split()[1:2] or [""])[0]
        if state in ("Z", "X"):
            continue
        if uid in uids:
            found.append(int(name))
    return found


def chown_tree(path: str, uid: int, gid: int, *, owner_rwx: bool = False) -> None:
    """Chown ``path`` and everything under it, parents before children.

    The parent is chowned before ``os.walk`` lists it, so a 0700 directory the
    session uid created becomes listable by root without DAC_OVERRIDE.
    ``owner_rwx`` also adds u+rwx on directories so rmtree can unlink entries.
    """
    _chown_one(path, uid, gid, owner_rwx, is_dir=True)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            _chown_one(os.path.join(root, name), uid, gid, owner_rwx, is_dir=True)
        for name in files:
            _chown_one(os.path.join(root, name), uid, gid, owner_rwx, is_dir=False)


def _chown_one(path: str, uid: int, gid: int, owner_rwx: bool, *, is_dir: bool) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)
    if owner_rwx and is_dir and not os.path.islink(path):
        mode = os.stat(path).st_mode
        os.chmod(path, (mode & 0o7777) | 0o700)
