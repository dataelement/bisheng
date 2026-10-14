"""Run a LocalExecutor script as a throwaway uid in a private run dir.

Enabled by ``sandbox_conf.local_isolation = "uid"``. The child never touches
the task workspace W: W is copied into a fresh run dir R owned by a pool uid,
the script runs there under ``prlimit`` with an allowlisted environment, every
process of the uid is killed afterwards, and only then are new or changed
regular files copied back into W.

Fails closed: if the process is not root on Linux, lacks a capability, has no
``prlimit``, or the startup probe does not confirm the expected access
denials, ``LocalIsolationUnavailable`` is raised and nothing runs.
"""

from __future__ import annotations

import glob
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from bisheng_langchain.gpts.tools.code_interpreter import local_run_registry, local_uid_pool, workspace_copy

DATA_DIR = "/app/data"
STREAM_HEAD_BYTES = 512 * 1024
STREAM_TAIL_BYTES = 512 * 1024
OUTPUT_HARD_LIMIT_BYTES = 256 * 1024 * 1024
DISK_CHECK_INTERVAL_S = 5.0
PROBE_TIMEOUT_S = 120
CHILD_USER = "sandbox"

# Capability bits in /proc/self/status CapEff (linux/capability.h).
_REQUIRED_CAPS = {
    "CAP_CHOWN": 0,
    "CAP_DAC_OVERRIDE": 1,
    "CAP_KILL": 5,
    "CAP_SETGID": 6,
    "CAP_SETUID": 7,
}

# Characters that would continue a path component: W followed by one of these
# is a longer, different path and must not be rewritten.
_PATH_CONTINUES = r"(?![A-Za-z0-9._\-])"

_PROBE_SOURCE = r"""
import json, os, sys

config_path, pkg_dir, data_dir = sys.argv[1:4]


def denied(fn):
    try:
        fn()
    except PermissionError:
        return True
    except FileNotFoundError:
        return None
    except OSError as exc:
        return "error: %s" % exc
    return False


def read_one(path):
    with open(path, "rb") as fh:
        fh.read(1)


result = {
    "uid": os.getuid(),
    "euid": os.geteuid(),
    "gid": os.getgid(),
    "groups": os.getgroups(),
    "environ": denied(lambda: read_one("/proc/1/environ")),
    "root_home": denied(lambda: os.listdir("/root")),
    "config": denied(lambda: read_one(config_path)),
    "pkg": denied(lambda: os.listdir(pkg_dir)),
    "data": denied(lambda: os.listdir(data_dir)),
}
try:
    import numpy, pandas, matplotlib  # noqa: F401
    result["imports"] = None
except Exception as exc:
    result["imports"] = repr(exc)
try:
    with open("probe-write.txt", "w") as fh:
        fh.write("ok")
    result["write"] = None
except Exception as exc:
    result["write"] = repr(exc)
print(json.dumps(result))
"""


class LocalIsolationUnavailable(RuntimeError):
    """The isolated local executor cannot run on this host; nothing was executed."""


@dataclass
class IsolatedOutcome:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    disk_exceeded: bool = False
    output_overflow: bool = False
    reaped: bool = True
    skipped: list[str] = field(default_factory=list)
    harvested: list[str] = field(default_factory=list)


# --- configuration ---------------------------------------------------------

_off_warned = False


def _conf() -> Any:
    from bisheng.common.services.config_service import settings

    return settings.sandbox_conf


def isolation_mode() -> str:
    """'uid' or 'off'. Anything unreadable counts as 'uid' (fail closed)."""
    global _off_warned
    try:
        mode = _conf().local_isolation
    except Exception:
        logger.exception("local isolation: sandbox_conf unreadable; treating as uid")
        return "uid"
    if mode == "off":
        if not _off_warned:
            _off_warned = True
            logger.warning(
                "local code execution is NOT isolated (sandbox_conf.local_isolation=off): scripts run as the "
                "service user with its full environment"
            )
        return "off"
    return "uid"


# --- preflight -------------------------------------------------------------

_preflight_lock = threading.Lock()
_prlimit_path: str | None = None


def _backend_package_dir() -> str:
    import bisheng

    return os.path.dirname(os.path.abspath(bisheng.__file__))


def _cap_eff() -> int:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("CapEff:"):
                return int(line.split()[1], 16)
    raise LocalIsolationUnavailable("CapEff not found in /proc/self/status")


def _check_system() -> str:
    if not sys.platform.startswith("linux"):
        raise LocalIsolationUnavailable(f"not Linux ({sys.platform})")
    if os.geteuid() != 0:
        raise LocalIsolationUnavailable(f"not running as root (euid={os.geteuid()})")
    prlimit = shutil.which("prlimit")
    if not prlimit:
        raise LocalIsolationUnavailable("prlimit (util-linux) not found on PATH")
    cap_eff = _cap_eff()
    missing = [name for name, bit in _REQUIRED_CAPS.items() if not cap_eff & (1 << bit)]
    if missing:
        raise LocalIsolationUnavailable(f"missing capabilities: {', '.join(missing)}")
    return prlimit


def _prepare_run_root(run_root: str) -> None:
    os.makedirs(run_root, mode=0o711, exist_ok=True)
    st = os.lstat(run_root)
    if not os.path.isdir(run_root) or os.path.islink(run_root) or st.st_uid != 0:
        raise LocalIsolationUnavailable(f"{run_root} is not a root-owned directory")
    os.chmod(run_root, 0o711)


def _check_foreign_uids() -> None:
    held = local_uid_pool.held_uids()
    foreign = {
        uid: pids
        for uid, pids in local_uid_pool.live_processes_by_uid().items()
        if local_uid_pool.UID_MIN <= uid <= local_uid_pool.UID_MAX and uid not in held
    }
    if foreign:
        detail = ", ".join(f"uid {uid}: pids {pids[:5]}" for uid, pids in sorted(foreign.items())[:5])
        raise LocalIsolationUnavailable(
            f"processes outside the pool already run in uid range "
            f"{local_uid_pool.UID_MIN}-{local_uid_pool.UID_MAX} ({detail}); reaping would kill them"
        )


def tighten_permissions(pkg_dir: str, data_dir: str = DATA_DIR) -> None:
    """chmod 0700 the backend package dir and the data mount (top level only).

    A failure (read-only or root-squashed storage) is logged, not raised: the
    probe that follows decides by what the pool uid can actually reach.
    """
    for path in (pkg_dir, data_dir):
        if not os.path.isdir(path):
            continue
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            logger.warning("local isolation: chmod 0700 {} failed: {}", path, exc)
    config_path = os.path.join(pkg_dir, "config.yaml")
    try:
        mode = os.stat(config_path).st_mode
    except OSError:
        return
    if mode & 0o044:
        logger.warning(
            "local isolation: {} is group/other readable ({:o}); set it to 0600 owned by root on the host",
            config_path,
            mode & 0o777,
        )


def evaluate_probe(result: dict, uid: int, data_dir: str = DATA_DIR) -> None:
    """Raise LocalIsolationUnavailable unless the probe saw the expected denials."""
    problems = []
    if result.get("uid") != uid or result.get("euid") != uid or result.get("gid") != uid:
        problems.append(f"child identity {result.get('uid')}/{result.get('euid')}/{result.get('gid')} != {uid}")
    if set(result.get("groups") or []) - {uid}:
        problems.append(f"child kept supplementary groups {result.get('groups')}")
    if result.get("environ") is not True:
        problems.append("/proc/1/environ is readable")
    for key, label in (("root_home", "/root"), ("config", "config.yaml"), ("pkg", "the backend package dir")):
        if result.get(key) not in (True, None):
            problems.append(f"{label} is readable by the pool uid")
    if result.get("imports"):
        problems.append(f"numpy/pandas/matplotlib cannot be imported: {result['imports']}")
    if result.get("write"):
        problems.append(f"cannot write in the run dir: {result['write']}")
    if problems:
        raise LocalIsolationUnavailable("; ".join(problems))
    if result.get("data") is False:
        logger.warning("local isolation: sandboxed code can read {} (chmod 0700 did not take)", data_dir)


def _probe(prlimit: str, conf: Any) -> None:
    pkg_dir = _backend_package_dir()
    outcome, uid = _run_probe(prlimit, conf, pkg_dir)
    if outcome.returncode != 0 or outcome.timed_out:
        raise LocalIsolationUnavailable(
            f"probe as uid {uid} exited {outcome.returncode}: {outcome.stderr[-2000:] or outcome.stdout[-2000:]}"
        )
    try:
        result = json.loads(outcome.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise LocalIsolationUnavailable(f"probe output unreadable: {outcome.stdout[-500:]!r}") from exc
    evaluate_probe(result, uid)


def _run_probe(prlimit: str, conf: Any, pkg_dir: str) -> tuple[IsolatedOutcome, int]:
    uid = local_uid_pool.acquire(conf.local_run_root)
    if uid is None:
        raise LocalIsolationUnavailable("uid pool exhausted")
    try:
        run_dir = _make_run_dir(conf.local_run_root, uid)
        _write_script(os.path.join(run_dir, "probe.py"), _PROBE_SOURCE, uid)
        config_path = os.path.join(pkg_dir, "config.yaml")
        argv = [sys.executable, "-s", "-B", "-X", "utf8", "probe.py", config_path, pkg_dir, DATA_DIR]
        return _spawn_and_read(prlimit, conf, uid, run_dir, argv, PROBE_TIMEOUT_S), uid
    finally:
        if local_uid_pool.reap_uid(uid):
            local_uid_pool.free(uid, conf.local_run_root)
        else:
            logger.error("local isolation: probe uid {} could not be reaped; kept quarantined", uid)


def preflight() -> str:
    """Check the host once per process; return the prlimit path. Raises on failure."""
    global _prlimit_path
    if _prlimit_path is not None:
        return _prlimit_path
    with _preflight_lock:
        if _prlimit_path is not None:
            return _prlimit_path
        conf = _conf()
        try:
            prlimit = _check_system()
            local_uid_pool.ensure_marker_dir()
            _prepare_run_root(conf.local_run_root)
            local_uid_pool.sweep(conf.local_run_root)
            _check_foreign_uids()
            tighten_permissions(_backend_package_dir())
            _probe(prlimit, conf)
        except LocalIsolationUnavailable as exc:
            logger.error("local isolation unavailable: {}", exc)
            raise
        except Exception as exc:
            logger.exception("local isolation preflight failed")
            raise LocalIsolationUnavailable(f"preflight failed: {exc}") from exc
        logger.info("local isolation ready (uid pool {}-{})", local_uid_pool.UID_MIN, local_uid_pool.UID_MAX)
        _prlimit_path = prlimit
        return prlimit


# --- child environment and launch ----------------------------------------


def child_env(run_dir: str) -> dict[str, str]:
    """Allowlisted environment of the child; nothing else is inherited."""
    tmp = os.path.join(run_dir, ".tmp")
    env = {
        "PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": run_dir,
        "TMPDIR": tmp,
        "TEMP": tmp,
        "TMP": tmp,
        "MPLCONFIGDIR": os.path.join(run_dir, ".mpl"),
        "USER": CHILD_USER,
        "LOGNAME": CHILD_USER,
    }
    if os.environ.get("TZ"):
        env["TZ"] = os.environ["TZ"]
    return env


def _prlimit_argv(prlimit: str, conf: Any) -> list[str]:
    return [
        prlimit,
        f"--as={int(conf.local_rlimit_as_bytes)}",
        f"--cpu={int(conf.local_rlimit_cpu_s)}",
        f"--nproc={int(conf.local_rlimit_nproc)}",
        f"--fsize={int(conf.local_rlimit_fsize_bytes)}",
        f"--nofile={int(conf.local_rlimit_nofile)}",
        "--core=0",
        "--",
    ]


def _make_run_dir(run_root: str, uid: int) -> str:
    run_dir = os.path.realpath(tempfile.mkdtemp(prefix="run-", dir=run_root))
    os.chown(run_dir, uid, uid)
    os.chmod(run_dir, 0o700)
    for sub in (".tmp", ".mpl"):
        path = os.path.join(run_dir, sub)
        os.mkdir(path, 0o700)
        os.chown(path, uid, uid)
    return run_dir


def _write_script(path: str, code: str, uid: int) -> None:
    # The run dir was just filled by root and the uid has not run yet, so
    # nothing under it can be a planted symlink; O_NOFOLLOW is belt and braces.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(code)
    os.chown(path, uid, uid)
    os.chmod(path, 0o644)


class _HeadTail:
    """Keep the first and last bytes of a stream, drop the middle."""

    def __init__(self, head: int = STREAM_HEAD_BYTES, tail: int = STREAM_TAIL_BYTES):
        self._head_limit = head
        self._tail_limit = tail
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        room = self._head_limit - len(self.head)
        if room > 0:
            self.head.extend(data[:room])
            data = data[room:]
        if data:
            self.tail.extend(data)
            if len(self.tail) > self._tail_limit:
                del self.tail[: len(self.tail) - self._tail_limit]

    def text(self) -> str:
        omitted = self.total - len(self.head) - len(self.tail)
        body = bytes(self.head)
        if omitted > 0:
            body += f"\n[... {omitted} bytes of output omitted ...]\n".encode()
        body += bytes(self.tail)
        return body.decode("utf-8", errors="replace")


def dir_usage(path: str) -> int:
    """Bytes allocated under ``path``, without following symlinks."""
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    blocks = getattr(st, "st_blocks", None)
                    total += blocks * 512 if blocks is not None else st.st_size
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
        except OSError:
            continue
    return total


def _killpg(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass


def _spawn_and_read(
    prlimit: str,
    conf: Any,
    uid: int,
    run_dir: str,
    argv: list[str],
    timeout: float,
    stop: Callable[[], bool] | None = None,
) -> IsolatedOutcome:
    try:
        proc = subprocess.Popen(
            _prlimit_argv(prlimit, conf) + argv,
            cwd=run_dir,
            env=child_env(run_dir),
            user=uid,
            group=uid,
            extra_groups=[],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise LocalIsolationUnavailable(f"cannot start the child as uid {uid}: {exc}") from exc
    out, err = _HeadTail(), _HeadTail()
    timed_out = disk_exceeded = overflow = stopped = False
    disk_limit = int(conf.local_disk_limit_bytes)
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, out)
    sel.register(proc.stderr, selectors.EVENT_READ, err)
    started = time.monotonic()
    deadline = started + timeout
    next_disk = started + DISK_CHECK_INTERVAL_S
    try:
        while sel.get_map():
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                break
            if stop is not None and stop():
                stopped = True
                break
            if now >= next_disk:
                next_disk = now + DISK_CHECK_INTERVAL_S
                if dir_usage(run_dir) > disk_limit:
                    disk_exceeded = True
                    break
            events = sel.select(min(deadline - now, next_disk - now, 0.5))
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    sel.unregister(key.fileobj)
                    continue
                key.data.feed(data)
            if out.total + err.total > OUTPUT_HARD_LIMIT_BYTES:
                overflow = True
                break
            # The main child is gone and nothing is arriving: a backgrounded
            # descendant may hold the pipes open forever; the uid reap ends it.
            if not events and proc.poll() is not None:
                break
    finally:
        sel.close()
        if timed_out or disk_exceeded or overflow or stopped or proc.poll() is None:
            _killpg(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
    if not disk_exceeded and dir_usage(run_dir) > disk_limit:
        disk_exceeded = True
    return IsolatedOutcome(
        returncode=proc.returncode if not (timed_out or disk_exceeded or overflow or stopped) else 1,
        stdout=out.text(),
        stderr=err.text(),
        timed_out=timed_out,
        disk_exceeded=disk_exceeded,
        output_overflow=overflow,
    )


# --- path rewriting --------------------------------------------------------


def _path_forms(path: str) -> list[str]:
    forms = {path.rstrip("/") or "/", os.path.abspath(path), os.path.realpath(path)}
    return sorted((f for f in forms if f and f != "/"), key=len, reverse=True)


def rewrite_paths(text: str, src: str, dst: str) -> str:
    """Replace ``src`` with ``dst`` where it is a whole path prefix.

    ``/x/ab12`` is rewritten in ``/x/ab12``, ``/x/ab12/f`` and ``"/x/ab12"``,
    never in ``/x/ab12ef``.
    """
    if not text:
        return text
    for form in _path_forms(src):
        text = re.sub(re.escape(form) + _PATH_CONTINUES, lambda _m: dst, text)
    return text


# --- font cache --------------------------------------------------------------

_font_lock = threading.Lock()
_font_files: list[str] | None = None


def _font_cache_files() -> list[str]:
    """Root's matplotlib font cache, built once per process."""
    global _font_files
    if _font_files is not None:
        return _font_files
    with _font_lock:
        if _font_files is None:
            try:
                import matplotlib
                import matplotlib.font_manager as font_manager

                names = {font.name for font in font_manager.fontManager.ttflist}
                if "WenQuanYi Zen Hei" not in names:
                    logger.warning("local isolation: font cache has no 'WenQuanYi Zen Hei'; CJK charts may break")
                _font_files = glob.glob(os.path.join(matplotlib.get_cachedir(), "fontlist-*.json"))
            except Exception:
                logger.exception("local isolation: matplotlib font cache unavailable")
                _font_files = []
    return _font_files


def _seed_font_cache(run_dir: str, uid: int) -> None:
    mpl_dir = os.path.join(run_dir, ".mpl")
    for src in _font_cache_files():
        dst = os.path.join(mpl_dir, os.path.basename(src))
        try:
            shutil.copyfile(src, dst)
            os.chown(dst, uid, uid)
            os.chmod(dst, 0o644)
        except OSError:
            logger.exception("local isolation: could not seed font cache {}", src)


# --- one run ---------------------------------------------------------------


def _check_script_name(filename: str) -> None:
    if os.sep in filename or filename.startswith("."):
        raise AssertionError(f"invalid script name {filename!r}")


def _ready() -> tuple[str, Any]:
    prlimit = preflight()
    conf = _conf()
    try:
        _prepare_run_root(conf.local_run_root)
    except OSError as exc:
        raise LocalIsolationUnavailable(f"run root {conf.local_run_root} unusable: {exc}") from exc
    return prlimit, conf


def run_isolated(
    code: str,
    filename: str,
    work_dir: str,
    lang: str,
    interpreter: list[str],
    timeout: float,
) -> IsolatedOutcome:
    """Copy W in, run ``interpreter + [filename]`` as a pool uid, reap, copy back.

    Paths in the returned output are rewritten from the run dir back to W.
    """
    if not work_dir:
        raise AssertionError("local isolation needs a work_dir; the shared extensions/ dir is not a workspace")
    _check_script_name(filename)
    prlimit, conf = _ready()
    uid = local_uid_pool.acquire(conf.local_run_root)
    if uid is None:
        raise LocalIsolationUnavailable("uid pool exhausted")
    run_dir = None
    reaped = False
    try:
        run_dir = _make_run_dir(conf.local_run_root, uid)
        started = time.monotonic()
        copied = workspace_copy.copy_in(
            work_dir,
            run_dir,
            uid,
            int(conf.local_copy_in_file_bytes),
            int(conf.local_copy_in_total_bytes),
        )
        logger.debug(
            "local isolation: copied {} file(s), {} bytes into the run dir in {:.2f}s",
            len(copied.index),
            copied.copied_bytes,
            time.monotonic() - started,
        )
        if lang.startswith("python"):
            _seed_font_cache(run_dir, uid)
        _write_script(os.path.join(run_dir, filename), rewrite_paths(code, work_dir, run_dir), uid)
        outcome = _spawn_and_read(prlimit, conf, uid, run_dir, [*interpreter, filename], timeout)
        outcome.skipped = copied.skipped
        reaped = local_uid_pool.reap_uid(uid)
        outcome.reaped = reaped
        if not reaped:
            logger.error("local isolation: uid {} could not be reaped; nothing harvested, uid quarantined", uid)
        elif outcome.disk_exceeded:
            logger.warning("local isolation: run exceeded the disk limit; nothing harvested")
        else:
            outcome.harvested = workspace_copy.copy_out(
                run_dir,
                work_dir,
                copied.index,
                {filename},
                int(conf.local_rlimit_fsize_bytes),
                int(conf.local_disk_limit_bytes),
            )
        outcome.stdout = rewrite_paths(outcome.stdout, run_dir, work_dir)
        outcome.stderr = rewrite_paths(outcome.stderr, run_dir, work_dir)
        return outcome
    finally:
        if not reaped:
            reaped = local_uid_pool.reap_uid(uid)
        if reaped:
            local_uid_pool.free(uid, conf.local_run_root)


# --- retained run (one run dir per task workspace) ---------------------------


class RunClosed(Exception):
    """The retained run was released (the task ended) while this call waited or ran."""


def _reset_private_dirs(run_dir: str, uid: int) -> None:
    # R stays the uid's between calls. Undo whatever the last script did to its
    # mode and to the dirs root writes into, before root writes anything.
    st = os.lstat(run_dir)
    if not os.path.isdir(run_dir) or os.path.islink(run_dir) or st.st_uid != uid:
        raise RuntimeError(f"retained run dir {run_dir} is no longer a directory owned by uid {uid}")
    os.chmod(run_dir, 0o700)
    for sub in (".tmp", ".mpl"):
        path = os.path.join(run_dir, sub)
        workspace_copy.remove_path(path)
        os.mkdir(path, 0o700)
        os.chown(path, uid, uid)


def _claim(entry: local_run_registry.RunEntry, conf: Any) -> None:
    uid = local_uid_pool.acquire(conf.local_run_root)
    if uid is None:
        raise LocalIsolationUnavailable("uid pool exhausted")
    entry.uid, entry.run_root, entry.index = uid, conf.local_run_root, {}
    entry.run_dir = _make_run_dir(conf.local_run_root, uid)


def run_retained(
    entry: local_run_registry.RunEntry,
    code: str,
    filename: str,
    work_dir: str,
    lang: str,
    interpreter: list[str],
    timeout: float,
) -> IsolatedOutcome:
    """Like ``run_isolated``, in the run dir kept for ``entry`` across calls.

    The caller holds ``entry.inner``. The first call claims the uid and R;
    later calls copy in only what changed in W. Raises ``RunClosed`` when the
    entry was released meanwhile; nothing is harvested then, W is about to go.
    Any failure discards R, so the next call starts from a full copy.
    """
    _check_script_name(filename)
    if entry.closing:
        raise RunClosed()
    prlimit, conf = _ready()
    try:
        if entry.uid is None:
            _claim(entry, conf)
        return _run_retained_once(entry, prlimit, conf, code, filename, work_dir, lang, interpreter, timeout)
    except BaseException:
        local_run_registry.drop_resources(entry)
        raise
    finally:
        if entry.closing:
            local_run_registry.drop_resources(entry)


def _run_retained_once(
    entry: local_run_registry.RunEntry,
    prlimit: str,
    conf: Any,
    code: str,
    filename: str,
    work_dir: str,
    lang: str,
    interpreter: list[str],
    timeout: float,
) -> IsolatedOutcome:
    uid, run_dir = entry.uid, entry.run_dir
    _reset_private_dirs(run_dir, uid)
    started = time.monotonic()
    synced = workspace_copy.sync_in(
        work_dir,
        run_dir,
        uid,
        entry.index,
        int(conf.local_copy_in_file_bytes),
        int(conf.local_copy_in_total_bytes),
    )
    entry.index = synced.index
    logger.debug(
        "local isolation: incremental copy of {} byte(s) into the retained run dir in {:.2f}s ({} file(s) in sync)",
        synced.copied_bytes,
        time.monotonic() - started,
        len(synced.index),
    )
    if lang.startswith("python"):
        _seed_font_cache(run_dir, uid)
    script = os.path.join(run_dir, filename)
    workspace_copy.remove_path(script)
    _write_script(script, rewrite_paths(code, work_dir, run_dir), uid)
    if entry.closing:
        raise RunClosed()
    outcome = _spawn_and_read(
        prlimit, conf, uid, run_dir, [*interpreter, filename], timeout, stop=lambda: entry.closing
    )
    outcome.skipped = synced.skipped
    outcome.reaped = local_uid_pool.reap_uid(uid)
    if not outcome.reaped:
        logger.error("local isolation: uid {} could not be reaped; nothing harvested, uid quarantined", uid)
        local_run_registry.drop_resources(entry)
    elif entry.closing:
        raise RunClosed()
    elif outcome.disk_exceeded:
        logger.warning("local isolation: run exceeded the disk limit; nothing harvested, run dir discarded")
        local_run_registry.drop_resources(entry)
    else:
        workspace_copy.remove_path(script)
        outcome.harvested = workspace_copy.copy_out(
            run_dir,
            work_dir,
            entry.index,
            {filename},
            int(conf.local_rlimit_fsize_bytes),
            int(conf.local_disk_limit_bytes),
            record=entry.index,
        )
    outcome.stdout = rewrite_paths(outcome.stdout, run_dir, work_dir)
    outcome.stderr = rewrite_paths(outcome.stderr, run_dir, work_dir)
    return outcome


def sweep_on_startup() -> None:
    """Reclaim uids and run dirs a crashed worker left behind.

    Each worker process calls this once before taking tasks. Markers whose
    owner process is alive (a sibling worker) are kept with their run dirs.
    """
    if isolation_mode() != "uid":
        return
    try:
        _check_system()
        conf = _conf()
        _prepare_run_root(conf.local_run_root)
        local_uid_pool.sweep(conf.local_run_root)
    except LocalIsolationUnavailable as exc:
        logger.warning("local isolation: startup sweep skipped: {}", exc)
    except Exception:
        logger.exception("local isolation: startup sweep failed")
