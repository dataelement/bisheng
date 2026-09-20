"""Isolation-environment executor: replica pool over HTTP, no docker/k8s client."""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import stat
import tarfile
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
from bisheng_langchain.gpts.tools.code_interpreter.discover import ReplicaDiscoverer
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LOCAL_DESCRIPTION, LocalExecutor

_LEASE_FIELDS = ("session_id", "lease_token", "lease_expires_at")
_BLOCK = 64 * 1024
_DEFAULT_COPY_IN = 50 * 1024 * 1024
_DEFAULT_TIMEOUT = 600
_ACQUIRE_TIMEOUT = 30


class _Unreachable(Exception):
    """Internal: this replica did not answer; try the next endpoint."""


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException)


class ContainerExecutor(LocalExecutor):
    """Lease a runner replica, tar the working dir, exec, copy-out.

    Non-empty ``endpoints`` skip DNS. Otherwise ``discoverer`` / hostname pattern
    expansion supplies the pool (T016). Sticky binds skip rediscovery.
    """

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
        self.pool_acquire_timeout_s = float(
            kwargs.get("pool_acquire_timeout_s") or getattr(conf, "pool_acquire_timeout_s", None) or _ACQUIRE_TIMEOUT
        )
        self.discover_host_pattern = kwargs.get("discover_host_pattern") or getattr(
            conf, "discover_host_pattern", "code-runner-{n}"
        )
        self.discover_index_start = int(
            kwargs.get("discover_index_start")
            if kwargs.get("discover_index_start") is not None
            else getattr(conf, "discover_index_start", 1)
        )
        self.discover_max = int(
            kwargs.get("discover_max") if kwargs.get("discover_max") is not None else getattr(conf, "discover_max", 32)
        )
        self.discover_ttl_s = float(
            kwargs.get("discover_ttl_s")
            if kwargs.get("discover_ttl_s") is not None
            else getattr(conf, "discover_ttl_s", 15)
        )
        self.discover_port = int(
            kwargs.get("discover_port")
            if kwargs.get("discover_port") is not None
            else getattr(conf, "discover_port", 8080)
        )
        self.discoverer = kwargs.get("discoverer")
        self.client = kwargs.get("client")
        self.copy_in_bytes = 0
        self._bound_url: str | None = None
        self._session_id: str | None = None
        self._lease_token: str | None = None
        self._md5_index: dict[str, str] = {}
        self._skipped: list[str] = []

    @property
    def description(self) -> str:
        # Same library list as local mode; skills/ is visible because copy-in
        # happens at run() (AC-04 / AC-11), unlike the frozen E2B snapshot.
        if "skills/" not in LOCAL_DESCRIPTION:
            return LOCAL_DESCRIPTION + path_namespace_rules(include_skills=True)
        return LOCAL_DESCRIPTION

    def execute_code(
        self,
        code: str | None = None,
        timeout: int | None = None,
        filename: str | None = None,
        work_dir: str | None = None,
        lang: str | None = "python",
    ) -> tuple[int, str, str]:
        timeout_s = int(timeout or self.timeout)
        work_dir = work_dir or os.getcwd()
        if code is None and filename:
            path = os.path.join(work_dir, filename) if not os.path.isabs(filename) else filename
            with open(path, encoding="utf-8") as fh:
                code = fh.read()
        code = code or ""
        self.copy_in_bytes = 0
        self._skipped = []
        acquired = bool(self.keep_session and self._session_id and self._bound_url)
        try:
            self._ensure_lease()
            acquired = True
            self._copy_in(work_dir)
            result = self._exec(code, lang or "python", timeout_s)
            exitcode = int(result["exitcode"])
            logs = self._logs_from(result, exitcode)
            if self._skipped:
                logs += self._skip_notice()
            if exitcode == 124:
                raise SandboxExecTimeoutError()
            if exitcode == 0:
                self._copy_out(work_dir)
            elif exitcode == 137:
                self._forget_lease()
            return exitcode, logs, ""
        finally:
            if not self.keep_session and acquired:
                self._release()

    def close(self) -> None:
        self._release()

    def _replica_urls(self) -> list[str]:
        if self.endpoints:
            return list(self.endpoints)
        if self.discoverer is None:
            probe_kwargs = {}
            if self.client is not None:
                probe_kwargs["health_probe"] = self._probe_health
            self.discoverer = ReplicaDiscoverer(
                endpoints=[],
                discover_host_pattern=self.discover_host_pattern,
                discover_index_start=self.discover_index_start,
                discover_max=self.discover_max,
                discover_ttl_s=self.discover_ttl_s,
                discover_port=self.discover_port,
                **probe_kwargs,
            )
        return self.discoverer.urls()

    def _probe_health(self, host: str, port: int) -> bool:
        try:
            resp = self.client.request("GET", f"http://{host}:{port}/health")
        except (OSError, ConnectionError, httpx.HTTPError):
            return False
        return getattr(resp, "status_code", 0) == 200

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
        members: dict[str, bytes] = {}
        manifest: dict[str, str] = {}
        for abs_path, rel, size in _walk_regular_files(work_dir):
            digest = _md5_file(abs_path)
            manifest[rel] = digest
            if size > self.max_copy_in_bytes:
                self._skipped.append(rel)
                logger.warning("{}: {}", SandboxCopyInLimitError.Msg, rel)
                continue
            if self._md5_index.get(rel) == digest:
                continue
            with open(abs_path, "rb") as fh:
                members[rel] = fh.read()
        payload = _tar_gz(members)
        self.copy_in_bytes = sum(len(blob) for blob in members.values())
        resp = self._request(
            "PUT",
            self._session_url("/files"),
            headers={
                **self._lease_headers(),
                # HTTP headers are ASCII: keep \uXXXX escapes so Chinese paths
                # (output/<中文>) cannot trip h11's ascii encode.
                "X-File-Manifest": json.dumps(manifest, separators=(",", ":"), ensure_ascii=True),
            },
            content=payload,
            timeout=self.pool_acquire_timeout_s,
            op="files",
        )
        body = self._json_object(resp)
        skipped = body.get("skipped") or []
        if isinstance(skipped, list):
            for item in skipped:
                path = item.get("path") if isinstance(item, dict) else item
                if path and path not in self._skipped:
                    self._skipped.append(str(path))
        for rel, digest in manifest.items():
            if rel not in self._skipped:
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
        data = self._json_object(resp, required=("exitcode",))
        return data

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

    def _release(self) -> None:
        if not self._bound_url or not self._session_id:
            return
        try:
            self._request(
                "DELETE",
                f"{self._bound_url}/v1/sessions/{self._session_id}",
                headers=self._lease_headers(),
                timeout=self.pool_acquire_timeout_s,
                op="release",
            )
        except (SandboxProtocolError, SandboxUnreachableError, _Unreachable, OSError, httpx.HTTPError):
            logger.warning("sandbox lease delete failed session={}", self._session_id)
        finally:
            self._forget_lease()

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
        content: bytes | None = None,
        json: dict | None = None,
        timeout: float | None = None,
        op: str = "control",
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
                raise SandboxExecTimeoutError() from exc
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
        names = ", ".join(self._skipped)
        return f"\n\n[SYSTEM NOTICE] {SandboxCopyInLimitError.Msg}: {names}"

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


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with _open_tar(buf, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name.replace("\\", "/"))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


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
