"""Isolation-environment executor: replica pool over HTTP, no docker/k8s client."""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import signal
import stat
import tarfile
import tempfile
from collections.abc import Iterator
from typing import Any

import httpx
from loguru import logger

from bisheng.common.errcode.sandbox import (
    SandboxCapacityExceededError,
    SandboxCopyInLimitError,
    SandboxExecTimeoutError,
    SandboxProtocolError,
    SandboxUnreachableError,
)
from bisheng_langchain.gpts.tools.code_interpreter.base_executor import path_namespace_rules
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import (
    LOCAL_DESCRIPTION,
    MAX_FAILURE_LOG_CHARS,
    PARTIAL_OUTPUT_HEADER,
    TASK_ENDED_MSG,
    LocalExecutor,
)

_LEASE_FIELDS = ("session_id", "lease_token", "lease_expires_at")
_BLOCK = 64 * 1024
_DEFAULT_COPY_IN = 50 * 1024 * 1024
_DEFAULT_COPY_IN_TOTAL = 512 * 1024 * 1024
_DEFAULT_TIMEOUT = 600
_ACQUIRE_TIMEOUT = 30
# The copy-in tar is built in memory up to this size, then spills to a temp file.
_SPOOL_BYTES = 8 * 1024 * 1024
# Session-scoped calls whose 404 means the runner no longer has this session.
_SESSION_OPS = frozenset({"files", "exec"})
# RLIMIT_CPU the runner applies to user code (SANDBOX_RLIMIT_CPU_S default).
_RUNNER_CPU_LIMIT_S = 600
_TIMEOUT_EXIT = 124

# Model-facing notices for a run the sandbox killed. Each one names the cause in
# plain words, because "exitcode 137, empty output" reads as a flaky
# environment and the model retries the identical script.
KILL_NOTICE_MEMORY = (
    "\n\n[SYSTEM NOTICE] The script was killed because it ran out of memory "
    "(the sandbox memory limit was reached). It did not finish, so nothing it was "
    "about to write exists. Do not rerun it unchanged: hold less data in memory, "
    "e.g. read large files in chunks (pandas chunksize), load only the needed "
    "columns or rows, and process the data piece by piece."
)
KILL_NOTICE_CPU = (
    "\n\n[SYSTEM NOTICE] The script was killed because it used up its CPU time "
    "limit ({limit}s of CPU time). It did not finish, so nothing it was about to "
    "write exists. Look for an unbounded loop or an algorithm that is too slow for "
    "this data size, and make the next attempt do less work."
)
KILL_NOTICE_SIGNAL = (
    "\n\n[SYSTEM NOTICE] The script was killed by signal {signum} ({name}). It did "
    "not finish, so nothing it was about to write exists."
)
KILL_NOTICE_SIGKILL_UNKNOWN = (
    "\n\n[SYSTEM NOTICE] The script was killed by signal 9 (SIGKILL). This usually "
    "means it ran out of memory or used up its CPU time limit. It did not finish, so "
    "nothing it was about to write exists. Hold less data in memory and do less work "
    "per run."
)
TIMEOUT_NOTICE = (
    "[SYSTEM NOTICE] Execution timed out: the script hit the wall-clock timeout of "
    "{timeout}s and was killed. It did not finish, so nothing it was about to write "
    "exists. Scope the next attempt down instead of rerunning it unchanged: an "
    "unbounded loop, a long sleep or a scan of a huge directory cannot finish here."
)
COPY_IN_TOTAL_NOTICE = (
    "These workspace files were not available to this run because the workspace "
    "is larger than the {limit}-byte copy-in limit"
)
SESSION_LOST_MSG = "Isolation environment lost the session again after a fresh lease"
TASK_STOPPED_MSG = "The task was stopped, so this run was ended before it finished."


class _Unreachable(Exception):
    """Internal: this replica did not answer; try the next endpoint."""


class _LeaseLost(Exception):
    """Internal: the runner answered 404 for our session (restart, idle reap)."""


def _normalize_exitcode(raw: Any) -> int:
    """Runner exit code as a shell-style value: a signal death -N becomes 128+N."""
    try:
        code = int(raw)
    except (TypeError, ValueError) as exc:
        raise SandboxProtocolError() from exc
    return 128 - code if code < 0 else code


def _killed_reason(result: dict, exitcode: int) -> str | None:
    """Why the runner killed the run, or None when it was not killed.

    A runner that sends ``killed_reason`` is authoritative: null means the
    process exited on its own, even with exit code 124 (e.g. ``timeout 2 curl``)
    or 128+N (e.g. ``sys.exit(130)``). The exit-code heuristics apply only to an
    older runner that omits the field.
    """
    if "killed_reason" in result:
        reason = result.get("killed_reason")
        if reason in ("timeout", "memory", "cpu", "signal"):
            return str(reason)
        if reason is not None:
            logger.warning("sandbox runner sent an unknown killed_reason={}", reason)
            return "signal" if 128 < exitcode <= 128 + 64 else None
        return None
    if exitcode == _TIMEOUT_EXIT:
        return "timeout"
    if 128 < exitcode <= 128 + 64:
        return "signal"
    return None


def _kill_notice(reason: str | None, exitcode: int, reported: bool) -> str:
    """Notice for a killed run; ``reported`` = the runner sent ``killed_reason``."""
    if reason == "memory":
        return KILL_NOTICE_MEMORY
    if reason == "cpu":
        return KILL_NOTICE_CPU.format(limit=_RUNNER_CPU_LIMIT_S)
    if reason != "signal":
        return ""
    signum = exitcode - 128
    if signum == signal.SIGKILL and not reported:
        # An older runner cannot tell an OOM or CPU kill from a plain SIGKILL.
        return KILL_NOTICE_SIGKILL_UNKNOWN
    try:
        name = signal.Signals(signum).name
    except ValueError:
        name = "unknown signal"
    return KILL_NOTICE_SIGNAL.format(signum=signum, name=name)


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException)


class ContainerExecutor(LocalExecutor):
    """Lease a runner replica, tar the working dir, exec, copy-out.

    The pool is the explicit ``endpoints`` list. An empty list is unreachable.
    Sticky binds keep the URL chosen for this executor.
    """

    supports_retained_run = False

    def __init__(self, minio: dict | None = None, **kwargs):
        super().__init__(minio, **kwargs)
        conf = kwargs.get("sandbox_conf")
        self.endpoints = [str(url).rstrip("/") for url in (kwargs.get("endpoints") or [])]
        if not self.endpoints and conf is not None:
            self.endpoints = [str(url).rstrip("/") for url in (conf.endpoints or [])]
        self.token = kwargs.get("token") or (getattr(conf, "token", None) or "")
        self.keep_session = bool(kwargs.get("keep_session", False))
        self.timeout = int(
            kwargs.get("timeout")
            or kwargs.get("default_timeout_s")
            or getattr(conf, "default_timeout_s", None)
            or _DEFAULT_TIMEOUT
        )
        self.max_copy_in_bytes = int(
            kwargs.get("max_copy_in_bytes") or getattr(conf, "max_copy_in_bytes", None) or _DEFAULT_COPY_IN
        )
        self.max_copy_in_total_bytes = int(
            kwargs.get("max_copy_in_total_bytes")
            or getattr(conf, "max_copy_in_total_bytes", None)
            or _DEFAULT_COPY_IN_TOTAL
        )
        self.pool_acquire_timeout_s = float(
            kwargs.get("pool_acquire_timeout_s") or getattr(conf, "pool_acquire_timeout_s", None) or _ACQUIRE_TIMEOUT
        )
        self.client = kwargs.get("client")
        self.copy_in_bytes = 0
        self._bound_url: str | None = None
        self._session_id: str | None = None
        self._lease_token: str | None = None
        self._md5_index: dict[str, str] = {}
        self._skipped: list[str] = []
        self._skipped_total: list[str] = []
        # Bumped by close(). A run that started under an older generation was
        # stopped from another thread and must not re-acquire or copy out.
        self._generation = 0

    @property
    def description(self) -> str:
        # Same library list as local mode; skills/ is visible because copy-in
        # happens at run() (AC-04 / AC-11), unlike the frozen E2B snapshot.
        if "skills/" not in LOCAL_DESCRIPTION:
            return LOCAL_DESCRIPTION + path_namespace_rules(include_skills=True) + self.kb_stage_hint()
        return LOCAL_DESCRIPTION + self.kb_stage_hint()

    def _publish_generated_files(self, dir_path: str, touched: list[str]) -> list[str]:
        if not self.workspace_prefix:
            return super()._publish_generated_files(dir_path, touched)
        files = [rel for rel in touched if os.path.isfile(os.path.join(dir_path, rel))]
        if self.sync_to_workspace(dir_path, files) != len(files):
            raise SandboxProtocolError(msg="Could not persist task artifacts to workspace storage")
        return ["/" + rel.replace(os.sep, "/").lstrip("/") for rel in files]

    def execute_code(
        self,
        code: str | None = None,
        timeout: int | None = None,
        filename: str | None = None,
        work_dir: str | None = None,
        lang: str | None = "python",
    ) -> tuple[int, str, str]:
        timeout_s = int(timeout or self.timeout)
        # None / missing dir = code-only (workflow code node). Never fall back
        # to os.getcwd(): Celery's cwd is /app and would tar the backend tree.
        workspace = work_dir if work_dir and os.path.isdir(work_dir) else None
        if code is None and filename:
            source_root = workspace or os.getcwd()
            path = filename if os.path.isabs(filename) else os.path.join(source_root, filename)
            with open(path, encoding="utf-8") as fh:
                code = fh.read()
        code = code or ""
        generation = self._generation
        try:
            for attempt in range(2):
                try:
                    return self._run_once(code, lang or "python", timeout_s, workspace, generation)
                except _LeaseLost:
                    lost = self._session_id
                    self._forget_lease()
                    if self._generation != generation:
                        return 1, TASK_STOPPED_MSG, ""
                    if attempt:
                        logger.error("sandbox session lost again after a fresh lease session={}", lost)
                        raise SandboxProtocolError(msg=SESSION_LOST_MSG) from None
                    logger.warning("sandbox session lost (404), acquiring a new lease session={}", lost)
                except SandboxExecTimeoutError:
                    raise
                except Exception:
                    if self._generation != generation:
                        logger.info("sandbox run ended by close() session={}", self._session_id)
                        return 1, TASK_STOPPED_MSG, ""
                    raise
            raise AssertionError("unreachable")  # pragma: no cover
        finally:
            if not self.keep_session:
                self._release()

    def _run_once(
        self, code: str, lang: str, timeout_s: int, workspace: str | None, generation: int
    ) -> tuple[int, str, str]:
        """One lease + copy-in + exec + copy-out pass. Raises ``_LeaseLost`` on 404."""
        self.copy_in_bytes = 0
        self._skipped = []
        self._skipped_total = []
        if self._generation != generation:
            return 1, TASK_ENDED_MSG, ""
        self._ensure_lease()
        # close() may have run while the acquire was in flight: it saw no session
        # and deleted nothing. Snapshot the lease so the stop deletes exactly the
        # session this run acquired, never one a later run holds.
        lease = (self._bound_url, self._session_id, self._lease_token)
        if self._generation != generation:
            return self._stop_after_acquire(lease)
        if workspace:
            self._copy_in(workspace)
            if self._generation != generation:
                return self._stop_after_acquire(lease)
        result = self._exec(code, lang, timeout_s)
        if self._generation != generation:
            return 1, TASK_STOPPED_MSG, ""
        exitcode = _normalize_exitcode(result["exitcode"])
        reason = _killed_reason(result, exitcode)
        logs = self._logs_from(result, exitcode)
        skip_notice = self._skip_notice()
        if reason == "timeout":
            logger.warning("sandbox exec timed out after {}s session={}", timeout_s, self._session_id)
            raise SandboxExecTimeoutError(msg=self._timeout_message(logs, timeout_s) + skip_notice)
        if exitcode == 0:
            if workspace:
                self._copy_out(workspace)
        elif reason is not None:
            # The session survives an OOM / CPU kill (only that process died), so
            # the lease is kept; a vanished session is handled by the 404 path.
            logger.warning("sandbox exec killed reason={} exitcode={} session={}", reason, exitcode, self._session_id)
        notice = _kill_notice(reason, exitcode, "killed_reason" in result)
        return exitcode, logs + notice + skip_notice, ""

    @staticmethod
    def _timeout_message(logs: str, timeout_s: int) -> str:
        message = TIMEOUT_NOTICE.format(timeout=timeout_s)
        partial = logs.strip()
        if not partial:
            return message
        budget = MAX_FAILURE_LOG_CHARS - len(message) - len(PARTIAL_OUTPUT_HEADER)
        return message + PARTIAL_OUTPUT_HEADER + LocalExecutor._tail(partial, budget)

    def close(self) -> None:
        """Release the lease. Safe to call while ``execute_code`` blocks in another thread.

        The runner's DELETE kills the session's running process group, so a
        cancelled task stops its sandbox code instead of letting it run on.
        """
        self._generation += 1
        self._release()

    def _replica_urls(self) -> list[str]:
        return list(self.endpoints)

    def _ensure_lease(self) -> None:
        if self.keep_session and self._session_id and self._bound_url:
            return
        urls = self._replica_urls()
        if not urls:
            raise SandboxUnreachableError()
        random.shuffle(urls)
        saw_503 = False
        for url in urls:
            try:
                resp = self._request(
                    "POST",
                    f"{url}/v1/sessions",
                    headers=self._bearer(),
                    timeout=self.pool_acquire_timeout_s,
                    op="acquire",
                )
            except _Unreachable:
                continue
            if resp.status_code == 503:
                saw_503 = True
                continue
            data = self._json_object(resp, required=_LEASE_FIELDS)
            self._bound_url = url
            self._session_id = str(data["session_id"])
            self._lease_token = str(data["lease_token"])
            self._md5_index = {}
            return
        if saw_503:
            raise SandboxCapacityExceededError()
        raise SandboxUnreachableError()

    def _copy_in(self, work_dir: str) -> None:
        """Send changed files as a streamed tar.gz; skip files over the per-file or total cap.

        The total counts every file the session will hold, unchanged ones too,
        because the runner enforces the same cap per session. Skipped files are
        never read, and the tar is spooled to disk rather than held in memory.
        """
        manifest: dict[str, str] = {}
        to_send: list[tuple[str, str]] = []
        total = 0
        for abs_path, rel, size in _walk_regular_files(work_dir):
            if size > self.max_copy_in_bytes:
                self._skipped.append(rel)
                logger.warning("{}: {}", SandboxCopyInLimitError.Msg, rel)
                continue
            if total + size > self.max_copy_in_total_bytes:
                self._skipped_total.append(rel)
                logger.warning("copy-in total limit {} reached, skipped: {}", self.max_copy_in_total_bytes, rel)
                continue
            total += size
            digest = _md5_file(abs_path)
            manifest[rel] = digest
            if self._md5_index.get(rel) == digest:
                continue
            to_send.append((abs_path, rel))
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES) as spool:
            self.copy_in_bytes = _write_tar_gz(spool, to_send)
            tar_size = spool.tell()
            spool.seek(0)
            head = _manifest_prefix(manifest)
            headers = self._lease_headers()
            headers["Content-Length"] = str(len(head) + tar_size)
            resp = self._request(
                "PUT",
                self._session_url("/files"),
                headers=headers,
                content=_iter_body(head, spool),
                timeout=self.pool_acquire_timeout_s,
                op="files",
            )
        body = self._json_object(resp)
        skipped = body.get("skipped") or []
        if isinstance(skipped, list):
            for item in skipped:
                path = item.get("path") if isinstance(item, dict) else item
                if not path or path in self._skipped or path in self._skipped_total:
                    continue
                size = item.get("size") if isinstance(item, dict) else None
                # The runner reports both caps the same way; a file under the
                # per-file cap can only have hit the session total.
                if isinstance(size, int) and size <= self.max_copy_in_bytes:
                    self._skipped_total.append(str(path))
                else:
                    self._skipped.append(str(path))
        for rel, digest in manifest.items():
            if rel not in self._skipped and rel not in self._skipped_total:
                self._md5_index[rel] = digest

    def _exec(self, code: str, lang: str, timeout_s: int) -> dict[str, Any]:
        resp = self._request(
            "POST",
            self._session_url("/exec"),
            headers=self._lease_headers(),
            json={"code": code, "lang": lang, "timeout_s": timeout_s},
            timeout=float(timeout_s) + 5.0,
            op="exec",
        )
        return self._json_object(resp, required=("exitcode",))

    def _copy_out(self, work_dir: str) -> None:
        resp = self._request(
            "GET",
            self._session_url("/files"),
            headers=self._lease_headers(),
            timeout=self.pool_acquire_timeout_s,
            op="files",
        )
        if resp.status_code != 200:
            raise SandboxProtocolError()
        _extract_tar(getattr(resp, "content", b"") or b"", work_dir)

    def _stop_after_acquire(self, lease: tuple[str | None, str | None, str | None]) -> tuple[int, str, str]:
        """close() raced this run's acquire or copy-in: delete its lease, skip the exec."""
        url, session_id, lease_token = lease
        logger.info("sandbox run stopped before exec, releasing its lease session={}", session_id)
        if self._session_id == session_id:
            self._forget_lease()
        self._delete_session(url, session_id, lease_token)
        return 1, TASK_STOPPED_MSG, ""

    def _release(self) -> None:
        # Snapshot then forget first: close() may run on another thread while an
        # exec is in flight, and that exec must not reuse the deleted session.
        url, session_id, lease_token = self._bound_url, self._session_id, self._lease_token
        self._forget_lease()
        self._delete_session(url, session_id, lease_token)

    def _delete_session(self, url: str | None, session_id: str | None, lease_token: str | None) -> None:
        if not url or not session_id:
            return
        headers = self._bearer()
        if lease_token:
            headers["X-Lease-Token"] = lease_token
        try:
            # 404 is success: the session is already gone.
            self._request(
                "DELETE",
                f"{url}/v1/sessions/{session_id}",
                headers=headers,
                timeout=self.pool_acquire_timeout_s,
                op="release",
            )
        except (SandboxProtocolError, SandboxUnreachableError, _Unreachable, OSError, httpx.HTTPError):
            logger.warning("sandbox lease delete failed session={}", session_id)

    def _forget_lease(self) -> None:
        self._bound_url = None
        self._session_id = None
        self._lease_token = None
        self._md5_index = {}

    def _session_url(self, suffix: str) -> str:
        if not self._bound_url or not self._session_id:
            raise SandboxUnreachableError()
        return f"{self._bound_url}/v1/sessions/{self._session_id}{suffix}"

    def _bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _lease_headers(self) -> dict[str, str]:
        headers = self._bearer()
        if self._lease_token:
            headers["X-Lease-Token"] = self._lease_token
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        content: bytes | Iterator[bytes] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        op: str = "control",
    ):
        resp = self._send(method, url, headers=headers, content=content, json=json, timeout=timeout, op=op)
        if op in _SESSION_OPS and getattr(resp, "status_code", 0) == 404:
            raise _LeaseLost()
        return resp

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None,
        content: bytes | Iterator[bytes] | None,
        json: dict | None,
        timeout: float | None,
        op: str,
    ):
        kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
        if json is not None:
            kwargs["json"] = json
        elif content is not None:
            kwargs["content"] = content
        try:
            if self.client is not None:
                return self.client.request(method, url, **kwargs)
            return httpx.request(method, url, **kwargs)
        except SandboxExecTimeoutError:
            raise
        except Exception as exc:
            if op == "exec" and _is_timeout(exc):
                # The runner did not even answer within timeout + 5s.
                wall = int(timeout - 5) if timeout else self.timeout
                raise SandboxExecTimeoutError(msg=TIMEOUT_NOTICE.format(timeout=wall)) from exc
            if op == "release":
                raise _Unreachable() from exc
            if _is_timeout(exc) or isinstance(exc, (OSError, ConnectionError, httpx.TransportError)):
                if op in {"acquire"}:
                    raise _Unreachable() from exc
                raise SandboxUnreachableError() from exc
            raise

    def _json_object(self, resp, required: tuple[str, ...] = ()) -> dict:
        if getattr(resp, "status_code", 0) != 200:
            raise SandboxProtocolError()
        try:
            data = resp.json()
        except Exception as exc:
            raise SandboxProtocolError() from exc
        if not isinstance(data, dict):
            raise SandboxProtocolError()
        for key in required:
            if key not in data:
                raise SandboxProtocolError()
        return data

    def _skip_notice(self) -> str:
        notice = ""
        if self._skipped:
            notice += f"\n\n[SYSTEM NOTICE] {SandboxCopyInLimitError.Msg}: {', '.join(self._skipped)}"
        if self._skipped_total:
            reason = COPY_IN_TOTAL_NOTICE.format(limit=self.max_copy_in_total_bytes)
            notice += f"\n\n[SYSTEM NOTICE] {reason}: {', '.join(self._skipped_total)}"
        return notice

    @staticmethod
    def _logs_from(result: dict, exitcode: int) -> str:
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        if exitcode:
            return stderr or stdout
        return stdout


def _walk_regular_files(work_dir: str):
    if not work_dir or not os.path.isdir(work_dir):
        return
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [name for name in dirs if not name.startswith(".") and name != "__pycache__"]
        for name in files:
            if name.startswith("."):
                continue
            abs_path = os.path.join(root, name)
            try:
                info = os.lstat(abs_path)
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode) or stat.S_ISSOCK(info.st_mode) or stat.S_ISFIFO(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            rel = os.path.relpath(abs_path, work_dir).replace(os.sep, "/")
            yield abs_path, rel, info.st_size


def _md5_file(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_BLOCK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _open_tar(fileobj, mode: str):
    return tarfile.open(fileobj=fileobj, mode=mode, encoding="utf-8", format=tarfile.PAX_FORMAT)


def _manifest_prefix(manifest: dict) -> bytes:
    """4-byte big-endian length plus the UTF-8 JSON manifest; the tar.gz follows.

    ``ensure_ascii`` keeps Chinese paths as ``\\uXXXX`` so the length prefix
    counts the bytes the runner will decode. Must match ``split_copy_in_body``.
    """
    raw = json.dumps(manifest, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw


def _write_tar_gz(fileobj, members: list[tuple[str, str]]) -> int:
    """Stream ``(abs_path, rel)`` files into a tar.gz on ``fileobj``; return the bytes added."""
    added = 0
    with _open_tar(fileobj, "w:gz") as tar:
        for abs_path, rel in members:
            try:
                fh = open(abs_path, "rb")
            except FileNotFoundError:
                logger.warning("copy-in file vanished before upload: {}", rel)
                continue
            with fh:
                info = tarfile.TarInfo(name=rel.replace("\\", "/"))
                info.size = os.fstat(fh.fileno()).st_size
                tar.addfile(info, fh)
                added += info.size
    return added


def _iter_body(head: bytes, fileobj) -> Iterator[bytes]:
    yield head
    while True:
        chunk = fileobj.read(_BLOCK)
        if not chunk:
            return
        yield chunk


def _extract_tar(payload: bytes, dest: str) -> None:
    if not payload:
        return
    buf = io.BytesIO(payload)
    try:
        tar = _open_tar(buf, "r:gz")
    except tarfile.TarError as exc:
        raise SandboxProtocolError() from exc
    with tar:
        for member in tar:
            if not member.isfile():
                continue
            rel = member.name.replace("\\", "/")
            while rel.startswith("./"):
                rel = rel[2:]
            parts = rel.split("/")
            if rel.startswith("/") or any(part == ".." for part in parts):
                raise SandboxProtocolError()
            rel = "/".join(part for part in parts if part not in ("", "."))
            if not rel:
                continue
            target = os.path.realpath(os.path.join(dest, *rel.split("/")))
            root = os.path.realpath(dest)
            os.makedirs(root, exist_ok=True)
            if target != root and not target.startswith(root + os.sep):
                raise SandboxProtocolError()
            os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(target, "wb") as out:
                while True:
                    chunk = source.read(_BLOCK)
                    if not chunk:
                        break
                    out.write(chunk)
