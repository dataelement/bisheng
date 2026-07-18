"""C2 stub: in-memory ``FakeWorkspaceBackend`` (F035 Wave-0 deliverable).

This is the **decoupling stub** for contract C2 (WorkspaceBackend). Track A/B/H
program against it during Wave 1; Track C swaps in the real
``workspace_backend.WorkspaceBackend`` (MinIO truth + write-through cache) at
integration (Wave 2).

Deliberately standalone — it does **not** import deepagents' ``FilesystemBackend``
so any Track can use it without the full agent runtime. The real backend will
subclass ``FilesystemBackend``; the public method surface here is the frozen C2
interface and must stay signature-compatible:

    write(path, content)            -> None
    read(path, offset=0, limit=None) -> str
    ls(prefix="")                   -> list[FileEntry]
    edit(path, old_string, new_string) -> None

MinIO layout mirrored in-memory under ``workspace/{svid}/``:
    uploads/<name>/index.md | output/ | scratch/ | manifest.json
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


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


class WorkspaceFileNotFoundError(FileNotFoundError):
    """Raised when reading/editing a path that does not exist in the workspace."""


def _normalize(path: str) -> str:
    """Normalize a workspace-relative path; reject traversal (``..``)."""
    p = path.strip().lstrip("/")
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError(f"path traversal is not allowed: {path!r}")
        parts.append(seg)
    return "/".join(parts)


class FakeWorkspaceBackend:
    """In-memory implementation of the C2 WorkspaceBackend contract.

    Paths are workspace-relative (e.g. ``output/report.md``); the ``svid``
    scopes the namespace so multiple instances stay isolated, mirroring
    ``workspace/{svid}/`` in MinIO. Tenant isolation in the real backend is
    enforced by ``svid`` + MinIO prefix; here it is the instance boundary.
    """

    def __init__(self, svid: str, minio=None, file_dir: str | None = None) -> None:
        self.svid = svid
        self.minio = minio  # unused in the fake; kept for signature parity
        self.file_dir = file_dir  # unused in the fake; kept for signature parity
        self._store: dict[str, bytes] = {}
        self._mtime: dict[str, float] = {}

    # -- write -------------------------------------------------------------
    def write(self, path: str, content) -> None:
        key = _normalize(path)
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        self._store[key] = data
        self._mtime[key] = time.time()

    # -- read --------------------------------------------------------------
    def read(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        key = _normalize(path)
        if key not in self._store:
            raise WorkspaceFileNotFoundError(key)
        text = self._store[key].decode("utf-8", errors="replace")
        lines = text.splitlines()
        end = None if limit is None else offset + limit
        return "\n".join(lines[offset:end])

    # -- ls ----------------------------------------------------------------
    def ls(self, prefix: str = "") -> list[FileEntry]:
        norm_prefix = _normalize(prefix) if prefix else ""
        entries: list[FileEntry] = []
        for key, data in sorted(self._store.items()):
            if norm_prefix and not key.startswith(norm_prefix):
                continue
            entries.append(
                FileEntry(
                    path=key,
                    size=len(data),
                    md5=hashlib.md5(data).hexdigest(),
                    is_dir=False,
                    mtime=self._mtime.get(key, 0.0),
                )
            )
        return entries

    # -- edit --------------------------------------------------------------
    def edit(self, path: str, old_string: str, new_string: str) -> None:
        key = _normalize(path)
        if key not in self._store:
            raise WorkspaceFileNotFoundError(key)
        text = self._store[key].decode("utf-8", errors="replace")
        if old_string not in text:
            raise ValueError(f"old_string not found in {key!r}")
        self._store[key] = text.replace(old_string, new_string, 1).encode("utf-8")
        self._mtime[key] = time.time()

    # -- helpers (test convenience, not part of the C2 contract) -----------
    def exists(self, path: str) -> bool:
        return _normalize(path) in self._store

    def snapshot(self) -> dict[str, str]:
        return {k: v.decode("utf-8", errors="replace") for k, v in self._store.items()}
