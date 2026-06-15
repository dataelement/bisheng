"""Real ``WorkspaceBackend`` for the F035 linsight task mode (Track C, Wave 2).

Truth source is **MinIO** (``workspace/{svid}/``); a local ``file_dir`` acts as
a **write-through cache** so deepagents file tools and the E2B copy-in/out path
share one workspace per session. This is the production swap-in for the C2
``FakeWorkspaceBackend`` stub (``test/linsight/fixtures/fake_workspace_backend.py``).

Design refs: ``features/v2.6.0/035-linsight-task-mode/design.md`` §9.3.2 and
``依赖与契约约定.md`` §3 (C2). It subclasses deepagents'
``FilesystemBackend`` and implements the ``BackendProtocol`` surface
(``read/write/ls/edit`` + ``glob/grep/upload_files/download_files`` and their
``a*`` async versions).

Key properties (design §9.3.2):
  - **write-through**: every ``write``/``edit`` persists to MinIO immediately, so
    MinIO is always the latest truth; clearing the local cache is lossless and a
    parked task resumes by re-materializing from MinIO.
  - **lazy read**: ``read`` serves from cache, lazily fetching from MinIO on a
    cache miss.
  - **ls authoritative from MinIO**: directory listings reflect the object store,
    not just the local cache.
  - **tenant isolation**: every object key is prefixed ``workspace/{svid}/`` and
    the cache lives under a per-session ``file_dir``.

Paths follow the deepagents protocol (absolute, leading ``/``); they are
normalized to workspace-relative keys and ``..`` traversal is rejected.

MinIO layout under ``workspace/{svid}/``:
  - ``uploads/<name>/index.md`` (+ ``images/``) — parsed attachments
  - ``output/`` — deliverables (product area)
  - ``scratch/`` — intermediate state (persistent, not a deliverable)
  - ``manifest.json`` — pointer manifest for large/binary files
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

try:
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.backends.protocol import (
        EditResult,
        FileData,
        FileDownloadResponse,
        FileInfo,
        FileUploadResponse,
        GlobResult,
        GrepResult,
        LsResult,
        ReadResult,
        WriteResult,
    )

    _DEEPAGENTS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when deepagents absent
    # deepagents not installed: define a thin base so the module still imports.
    # The real method bodies below still work because they construct the result
    # dataclasses lazily; if deepagents is missing the class raises
    # NotImplementedError to flag the unfinished Wave-2 alignment.
    _DEEPAGENTS_AVAILABLE = False
    FilesystemBackend = object  # type: ignore[assignment,misc]
    ReadResult = WriteResult = EditResult = LsResult = None  # type: ignore[assignment]
    GlobResult = GrepResult = None  # type: ignore[assignment]
    FileData = FileInfo = dict  # type: ignore[assignment,misc]
    FileDownloadResponse = FileUploadResponse = None  # type: ignore[assignment]


WORKSPACE_PREFIX = "workspace"
"""Top-level MinIO object-key prefix for all session workspaces."""

# Standard workspace sub-areas (design §9.3.2).
UPLOADS_DIR = "uploads"
OUTPUT_DIR = "output"
SCRATCH_DIR = "scratch"
MANIFEST_NAME = "manifest.json"


@dataclass
class FileEntry:
    """C2 ``FileEntry``: a single workspace path descriptor."""

    path: str
    size: int
    md5: str
    is_dir: bool = False
    mtime: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "md5": self.md5,
            "is_dir": self.is_dir,
            "mtime": self.mtime,
        }


def normalize_workspace_path(path: str) -> str:
    """Normalize a workspace path to a relative key; reject ``..`` traversal.

    Accepts both absolute (``/output/a.md``) and relative (``output/a.md``) forms
    and returns a clean relative key (``output/a.md``). Raises ``ValueError`` on
    any ``..`` segment so a model/tool cannot escape the session workspace.
    """
    p = (path or "").strip().lstrip("/")
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError(f"path traversal is not allowed: {path!r}")
        parts.append(seg)
    return "/".join(parts)


class WorkspaceBackend(FilesystemBackend):
    """MinIO-truth + write-through-cache backend for one linsight session.

    Args:
        svid: session-version id; scopes the MinIO prefix and tenant isolation.
        minio: a ``MinioStorage`` instance (see ``get_minio_storage()``).
        file_dir: local cache directory (per-task; safe to clear).
    """

    def __init__(self, svid: str, minio, file_dir: str) -> None:
        if not _DEEPAGENTS_AVAILABLE:
            # TODO(Wave2): align with deepagents FilesystemBackend once the
            # dependency is installed in this environment.
            raise NotImplementedError(
                "deepagents is not installed; WorkspaceBackend requires "
                "deepagents.backends.filesystem.FilesystemBackend (Wave2 alignment)."
            )
        # FilesystemBackend roots relative paths at cwd; we always pass absolute
        # cache paths so its base init is a no-op for our purposes.
        self.svid = str(svid)
        self.minio = minio
        self.file_dir = file_dir
        os.makedirs(self.file_dir, exist_ok=True)

    # -- key / cache helpers ------------------------------------------------
    def _object_key(self, rel_path: str) -> str:
        """Map a workspace-relative path to its MinIO object key."""
        return f"{WORKSPACE_PREFIX}/{self.svid}/{rel_path}"

    def _cache_path(self, rel_path: str) -> Path:
        return Path(self.file_dir) / rel_path

    def _bucket(self) -> str:
        return self.minio.bucket

    def _cache_read(self, rel_path: str) -> bytes | None:
        cp = self._cache_path(rel_path)
        if cp.exists() and cp.is_file():
            return cp.read_bytes()
        return None

    def _cache_write(self, rel_path: str, data: bytes) -> None:
        cp = self._cache_path(rel_path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(data)

    def _minio_get_sync(self, rel_path: str) -> bytes | None:
        return self.minio.get_object_sync(bucket_name=self._bucket(), object_name=self._object_key(rel_path))

    def _minio_put_sync(self, rel_path: str, data: bytes) -> None:
        self.minio.put_object_sync(
            bucket_name=self._bucket(),
            object_name=self._object_key(rel_path),
            file=data,
        )

    def _load_into_cache(self, rel_path: str) -> bytes | None:
        """Cache-miss path: fetch from MinIO and populate the local cache."""
        data = self._minio_get_sync(rel_path)
        if data is None:
            return None
        self._cache_write(rel_path, data)
        return data

    def _materialize(self, rel_path: str) -> bytes | None:
        """Return file bytes, preferring cache, lazily loading from MinIO."""
        data = self._cache_read(rel_path)
        if data is not None:
            return data
        return self._load_into_cache(rel_path)

    @staticmethod
    def _to_bytes(content) -> bytes:
        if isinstance(content, bytes):
            return content
        return str(content).encode("utf-8")

    # -- write --------------------------------------------------------------
    def write(self, file_path: str, content) -> WriteResult:
        rel = normalize_workspace_path(file_path)
        data = self._to_bytes(content)
        # cache first (fast local), then write-through to MinIO (truth).
        self._cache_write(rel, data)
        self._minio_put_sync(rel, data)
        return WriteResult(path="/" + rel)

    # -- read ---------------------------------------------------------------
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        rel = normalize_workspace_path(file_path)
        data = self._materialize(rel)
        if data is None:
            return ReadResult(error=f"File '{file_path}' not found")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        start = offset
        end = offset + limit if limit is not None else None
        sliced = "\n".join(lines[start:end])
        return ReadResult(file_data=FileData(content=sliced, encoding="utf-8"))

    # -- ls (authoritative from MinIO) --------------------------------------
    def ls(self, path: str = "") -> LsResult:
        rel_prefix = normalize_workspace_path(path) if path else ""
        object_prefix = f"{WORKSPACE_PREFIX}/{self.svid}/"
        if rel_prefix:
            object_prefix += rel_prefix
        entries: list[FileInfo] = []
        key_prefix = f"{WORKSPACE_PREFIX}/{self.svid}/"
        try:
            objects = self.minio.minio_client_sync.list_objects(self._bucket(), prefix=object_prefix, recursive=True)
            for obj in objects:
                # Return workspace-relative paths (strip the ``workspace/{svid}/``
                # object-key prefix). Otherwise the agent reads back the listed
                # path and _object_key prepends the prefix a second time, yielding
                # ``workspace/{svid}/workspace/{svid}/...`` (NoSuchKey).
                name = obj.object_name
                rel_key = name[len(key_prefix) :] if name.startswith(key_prefix) else name
                entries.append(
                    FileInfo(
                        path="/" + rel_key,
                        is_dir=bool(getattr(obj, "is_dir", False)),
                        size=int(getattr(obj, "size", 0) or 0),
                    )
                )
        except Exception as e:
            logger.exception("workspace ls failed for svid=%s prefix=%s", self.svid, path)
            return LsResult(error=f"Error listing '{path}': {e}")
        return LsResult(entries=entries)

    # -- edit (cache mutation + write-through) ------------------------------
    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        rel = normalize_workspace_path(file_path)
        data = self._materialize(rel)
        if data is None:
            return EditResult(error=f"File '{file_path}' not found")
        text = data.decode("utf-8", errors="replace")
        if old_string not in text:
            return EditResult(error=f"old_string not found in '{file_path}'")
        if replace_all:
            occurrences = text.count(old_string)
            new_text = text.replace(old_string, new_string)
        else:
            if text.count(old_string) > 1:
                return EditResult(
                    error=(f"old_string is not unique in '{file_path}'; pass replace_all=True or provide more context")
                )
            occurrences = 1
            new_text = text.replace(old_string, new_string, 1)
        new_data = new_text.encode("utf-8")
        self._cache_write(rel, new_data)
        self._minio_put_sync(rel, new_data)
        return EditResult(path="/" + rel, occurrences=occurrences)

    # -- glob ---------------------------------------------------------------
    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        import fnmatch

        base = normalize_workspace_path(path) if path else ""
        ls_res = self.ls(base)
        if ls_res.error is not None:
            return GlobResult(error=ls_res.error)
        prefix = f"/{WORKSPACE_PREFIX}/{self.svid}/"
        matches: list[FileInfo] = []
        for entry in ls_res.entries or []:
            rel = entry["path"]
            rel_in_ws = rel[len(prefix) :] if rel.startswith(prefix) else rel.lstrip("/")
            if fnmatch.fnmatch(rel_in_ws, pattern) or fnmatch.fnmatch(os.path.basename(rel_in_ws), pattern):
                matches.append(entry)
        return GlobResult(matches=matches)

    # -- grep ---------------------------------------------------------------
    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        from deepagents.backends.protocol import GrepMatch

        base = normalize_workspace_path(path) if path else ""
        ls_res = self.ls(base)
        if ls_res.error is not None:
            return GrepResult(error=ls_res.error)
        prefix = f"/{WORKSPACE_PREFIX}/{self.svid}/"
        matches: list = []
        import fnmatch

        for entry in ls_res.entries or []:
            full = entry["path"]
            rel_in_ws = full[len(prefix) :] if full.startswith(prefix) else full.lstrip("/")
            if glob and not (fnmatch.fnmatch(rel_in_ws, glob) or fnmatch.fnmatch(os.path.basename(rel_in_ws), glob)):
                continue
            data = self._materialize(rel_in_ws)
            if data is None:
                continue
            text = data.decode("utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    matches.append(GrepMatch(path=full, line=lineno, text=line))
        return GrepResult(matches=matches)

    # -- upload / download (worker <-> workspace bulk ops) ------------------
    def upload_files(self, files: list[tuple[str, bytes]]) -> list:
        responses: list = []
        for raw_path, content in files:
            try:
                rel = normalize_workspace_path(raw_path)
                data = self._to_bytes(content)
                self._cache_write(rel, data)
                self._minio_put_sync(rel, data)
                responses.append(FileUploadResponse(path="/" + rel))
            except ValueError:
                responses.append(FileUploadResponse(path=raw_path, error="invalid_path"))
            except Exception:
                logger.exception("workspace upload failed for %s", raw_path)
                responses.append(FileUploadResponse(path=raw_path, error="permission_denied"))
        return responses

    def download_files(self, paths: list[str]) -> list:
        responses: list = []
        for raw_path in paths:
            try:
                rel = normalize_workspace_path(raw_path)
            except ValueError:
                responses.append(FileDownloadResponse(path=raw_path, error="invalid_path"))
                continue
            data = self._materialize(rel)
            if data is None:
                responses.append(FileDownloadResponse(path=raw_path, error="file_not_found"))
            else:
                responses.append(FileDownloadResponse(path="/" + rel, content=data))
        return responses

    # -- async surface (write-through truth uses real async MinIO) ----------
    async def awrite(self, file_path: str, content) -> WriteResult:
        rel = normalize_workspace_path(file_path)
        data = self._to_bytes(content)
        await asyncio.to_thread(self._cache_write, rel, data)
        await self.minio.put_object(
            bucket_name=self._bucket(),
            object_name=self._object_key(rel),
            file=data,
        )
        return WriteResult(path="/" + rel)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        rel = normalize_workspace_path(file_path)
        data = await asyncio.to_thread(self._cache_read, rel)
        if data is None:
            data = await self.minio.get_object(bucket_name=self._bucket(), object_name=self._object_key(rel))
            if data is not None:
                await asyncio.to_thread(self._cache_write, rel, data)
        if data is None:
            return ReadResult(error=f"File '{file_path}' not found")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        end = offset + limit if limit is not None else None
        return ReadResult(file_data=FileData(content="\n".join(lines[offset:end]), encoding="utf-8"))

    async def als(self, path: str = "") -> LsResult:
        return await asyncio.to_thread(self.ls, path)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return await asyncio.to_thread(self.edit, file_path, old_string, new_string, replace_all)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return await asyncio.to_thread(self.glob, pattern, path)

    async def agrep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        return await asyncio.to_thread(self.grep, pattern, path, glob)

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list:
        return await asyncio.to_thread(self.upload_files, files)

    async def adownload_files(self, paths: list[str]) -> list:
        return await asyncio.to_thread(self.download_files, paths)

    # -- convenience helpers (not part of the C2 contract) ------------------
    @staticmethod
    def md5_bytes(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()
