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

**Binary content.** Since the dual-track write (e96ce0017) ``uploads/`` holds the
ORIGINAL xlsx / docx / pdf next to its ``.md`` view, so every read path here must
distinguish text from bytes — see ``_decode_workspace_text``. deepagents requires
the BACKEND to make that call (all four built-in backends do); returning
replace-decoded mojibake with ``encoding="utf-8"`` silently fed U+FFFD to the
model and let ``edit`` corrupt originals.

**Storage growth (known trade-off).** ``seed_workspace_from_previous`` copies
``uploads/`` forward on every follow-up turn, so an original is duplicated once
per turn (server-side copy — no app-side bytes, but real stored bytes). Skipping
originals is NOT an option: the code interpreter's cross-turn access depends on
them. Reclaim belongs to ops — a MinIO lifecycle rule on the ``workspace/``
prefix — not to this module; the seed logs its byte volume so the growth is
visible rather than silent.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from minio.error import S3Error


def _is_missing_key(exc: S3Error) -> bool:
    """True when an S3 error means the object simply isn't there (NoSuchKey).

    MinIO raises ``S3Error`` (a frozen dataclass) on a missing object instead of
    returning empty. Workspace reads treat a missing object as a recoverable
    "file not found", so callers map this to ``None`` rather than letting the
    (frozen) exception escape and crash the task.
    """
    return getattr(exc, "code", None) == "NoSuchKey"


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

# Extensions deepagents' ``_EXTENSION_TO_FILE_TYPE`` classifies as ``image`` — the
# ONE multimodal shape mainstream OpenAI-compatible endpoints accept. Reading one
# of these hands the model a real base64 image block; every other binary is
# refused outright (see ``_binary_read_result``). MUST stay in sync with the
# upstream table: an extension we call an image but deepagents does not gets a
# generic ``file`` block instead, which is exactly the 400 we are avoiding.
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"})

# Ceiling for inlining an image as base64 in a tool result. Mirrors deepagents'
# ``backends/sandbox.py:MAX_BINARY_BYTES``; base64 inflates by 4/3 and the result
# is NOT subject to the text-path token truncation, so an unbounded read would
# push megabytes of payload straight into the conversation.
_MAX_INLINE_BINARY_BYTES = 500 * 1024

# ``grep`` walks every workspace object. Since the dual-track write (e96ce0017)
# the workspace legitimately holds multi-MB originals, and materializing one just
# to scan it for a pattern means a full MinIO download for content that cannot
# match anyway. Skip by the size ``ls`` already reports.
_MAX_GREP_BYTES = 2 * 1024 * 1024

# cchardet confidence floor for treating non-UTF-8 bytes as text. Same threshold
# the upload pipeline uses (``core/cache/utils.convert_encoding_cchardet``).
_ENCODING_MIN_CONFIDENCE = 0.5

# Marker prefix on every "this is binary" error the backend returns. The tool-layer
# guard (``binary_content_guard``) keys off it to swap in a fuller, code-interpreter
# aware hint; on its own the message still reads correctly to the model.
BINARY_READ_ERROR_PREFIX = "[binary-file]"


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


# First segments that only ever appear in a container/host path, never as a
# workspace zone. Used ONLY to word the error message — never to pick a file.
_HOST_ROOT_HINTS = frozenset({"root", "home", "tmp", "var", "usr", "opt", "mnt", "media", "Users", "app"})


def strip_executor_host_prefix(path: str, file_dir: str | None) -> tuple[str, bool]:
    """Drop the code interpreter's host-directory prefix; return ``(path, stripped)``.

    The interpreter's cwd IS this session's workspace cache dir, so the model routinely
    reports host paths like ``/root/.cache/bisheng/linsight/<svid8>/output/qa/s08.png``
    and then hands one back to ``read_file``. Without this the leading slash was simply
    dropped, producing the nonsense key ``workspace/<svid>/root/.cache/...`` and a bare
    "File not found" that never hinted at the real problem.

    ONE rule, deliberately: the full ``file_dir`` followed by ``/`` (or an exact
    match). Never a mere ancestor segment, so a workspace that genuinely contains
    ``root/report.md`` keeps it, and a near-miss sibling like ``/tmp/ws/<svid8>x/...``
    is left alone.

    A "strip any sibling task dir under the same parent" rule was considered — it
    would also catch the model quoting a path from an EARLIER turn's log — and
    rejected: it cannot distinguish a real sibling task dir from a directory that
    merely shares the parent, so it would silently reinterpret paths it has no
    business touching. Rewriting a path must be provably unambiguous; opening the
    wrong file is worse than an error message. Guessing belongs in the error text
    (``WorkspaceBackend._not_found_error``), never in file selection.
    """
    if not file_dir or not path.startswith("/"):
        return path, False
    root = os.path.normpath(file_dir)
    if path == root:
        return "", True
    if path.startswith(root + "/"):
        return path[len(root) + 1 :], True
    return path, False


def normalize_workspace_path(path: str, file_dir: str | None = None) -> str:
    """Normalize a workspace path to a relative key; reject ``..`` traversal.

    Accepts both absolute (``/output/a.md``) and relative (``output/a.md``) forms
    and returns a clean relative key (``output/a.md``). Raises ``ValueError`` on
    any ``..`` segment so a model/tool cannot escape the session workspace.

    ``file_dir`` is optional so this stays a plain function other modules can call
    (and test) without a backend; when given, a code-interpreter host path is folded
    back to its workspace key first. Traversal is validated AFTER stripping, so
    ``<file_dir>/../../etc/passwd`` still raises.
    """
    stripped, _ = strip_executor_host_prefix((path or "").strip(), file_dir)
    p = stripped.lstrip("/")
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise ValueError(f"path traversal is not allowed: {path!r}")
        parts.append(seg)
    return "/".join(parts)


def _decode_workspace_text(data: bytes, rel_path: str = "") -> str | None:
    """Decode workspace bytes as text, or return ``None`` when they are binary.

    This is the backend half of the deepagents contract: every built-in backend
    (``backends/state.py``, ``store.py``, ``filesystem.py``, ``sandbox.py``)
    recognises binary content ITSELF and either base64-encodes it or fails the
    read. This backend used to ``decode("utf-8", errors="replace")`` everything,
    which silently fed U+FFFD soup to the model for any unmapped binary
    (``.xlsx`` / ``.docx`` / ``.zip``) and corrupted originals on ``edit``.

    Two levels, in cost order:

    1. strict UTF-8 — the overwhelming majority of workspace content;
    2. a cchardet sniff for content that is legitimately TEXT in another encoding.
       This is not hypothetical: the code interpreter writing a GB18030 csv is the
       common case, and without this step the guard downstream would tell the model
       its own freshly written file is "raw binary". Reuses the detector the upload
       pipeline already depends on rather than adding a second sniffer.

    Bytes that survive neither are binary and every caller must refuse them.
    """
    # NUL first, and deliberately BEFORE the utf-8 attempt: NUL is itself a valid
    # UTF-8 code point, so a binary header such as b"%PDF-1.7\n\x00\x01" decodes
    # cleanly and would be served to the model as "text". No real text file contains
    # NUL, while essentially every container format (zip/xlsx/docx, pdf, images)
    # does — the same signal deepagents' sandbox backend classifies on. It also
    # saves a full-buffer sniff on multi-MB originals.
    if b"\x00" in data:
        return None

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    from bisheng.core.cache.utils import detect_encoding_cchardet

    try:
        encoding, confidence = detect_encoding_cchardet(data)
    except Exception:
        # cchardet is a C extension; a sniff failure must degrade to "binary",
        # never take down the read that called us.
        logger.exception("workspace read: encoding sniff failed for {}", rel_path)
        return None

    if not encoding or (confidence or 0) < _ENCODING_MIN_CONFIDENCE:
        return None
    try:
        text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None
    logger.info("workspace read: {} decoded as {} (confidence {})", rel_path, encoding, confidence)
    return text


def _binary_read_result(rel_path: str, data: bytes) -> ReadResult:
    """Build the ``ReadResult`` for content that is not text.

    Images within the inline ceiling become a REAL base64 block — the one
    multimodal shape endpoints accept, so a vision model can actually see a chart
    the code interpreter just rendered. Everything else (spreadsheets, documents,
    pdf, audio/video, oversized images) is refused with an actionable message,
    matching what upstream ``FilesystemBackend`` does for an unmapped binary:
    a clear error beats a payload the provider will reject.
    """
    suffix = os.path.splitext(rel_path)[1].lower()
    if suffix in _IMAGE_SUFFIXES and len(data) <= _MAX_INLINE_BINARY_BYTES:
        return ReadResult(
            file_data=FileData(content=base64.standard_b64encode(data).decode("ascii"), encoding="base64")
        )

    stem = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path
    return ReadResult(
        error=(
            f"{BINARY_READ_ERROR_PREFIX} '{rel_path}' is a binary file and cannot be read as text. "
            f"Its parsed text view, when one exists, is '{stem}.md'."
        )
    )


async def seed_workspace_from_previous(
    minio,
    src_svid: str,
    dst_svid: str,
    zones: tuple[str, ...] = (OUTPUT_DIR, UPLOADS_DIR),
) -> int:
    """Cross-turn continuity: server-side copy a prior session-version's
    deliverables (``output/``) and sources (``uploads/``) into a new version's
    workspace, so a follow-up turn (e.g. "convert the report to HTML") can read
    and build on the previous turn's output.

    Each version's workspace is cumulative (a turn seeds from its immediate
    predecessor, which already inherited *its* predecessor), so copying just the
    one prior turn carries the whole conversation forward. ``scratch/`` is
    intentionally skipped (intermediate state, not a deliverable). The copy is
    server-side (no bytes through the app). Best-effort: it no-ops when the
    destination already has content (idempotent on re-runs) and a per-object
    failure is logged and skipped so a partial prior workspace never blocks the
    new turn. Returns the number of objects copied.
    """
    if not src_svid or not dst_svid or src_svid == dst_svid:
        return 0

    def _copy() -> int:
        bucket = minio.bucket
        src_root = f"{WORKSPACE_PREFIX}/{src_svid}/"
        dst_root = f"{WORKSPACE_PREFIX}/{dst_svid}/"

        # Idempotency: skip if the new turn's workspace already has any object
        # (already seeded, or the turn has started writing).
        for _ in minio.minio_client_sync.list_objects(bucket, prefix=dst_root, recursive=True):
            return 0

        src_keys: list[tuple[str, int]] = []
        for zone in zones:
            prefix = f"{WORKSPACE_PREFIX}/{src_svid}/{zone}/"
            for obj in minio.minio_client_sync.list_objects(bucket, prefix=prefix, recursive=True):
                src_keys.append((obj.object_name, int(getattr(obj, "size", 0) or 0)))
        # manifest.json is a top-level pointer file (not under a zone).
        src_keys.append((f"{WORKSPACE_PREFIX}/{src_svid}/{MANIFEST_NAME}", 0))

        copied = 0
        copied_bytes = 0
        for src_key, size in src_keys:
            dst_key = dst_root + src_key[len(src_root) :]
            try:
                minio.copy_object_sync(
                    source_bucket=bucket, source_object=src_key, dest_bucket=bucket, dest_object=dst_key
                )
                copied += 1
                copied_bytes += size
            except S3Error as e:
                # A missing manifest/object is expected (NoSuchKey) — skip quietly;
                # surface anything else but keep going (best-effort seeding).
                if not _is_missing_key(e):
                    logger.warning(f"workspace seed: copy failed for {src_key}: {e}")
            except Exception as e:
                logger.warning(f"workspace seed: copy failed for {src_key}: {e}")
        if copied:
            # Duplicating uploads/ per turn is a deliberate trade-off (the code
            # interpreter needs the originals across turns); log the volume so the
            # accumulation is visible to ops instead of silently growing.
            logger.info(
                "workspace seed: copied {} object(s), {} KiB from {} to {}",
                copied,
                copied_bytes // 1024,
                src_svid[:8],
                dst_svid[:8],
            )
        return copied

    return await asyncio.to_thread(_copy)


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
    def _ws_rel(self, path: str) -> str:
        """``normalize_workspace_path`` bound to this session's executor cache dir.

        Every tool entry point goes through here so a host path pasted back from the
        code interpreter resolves instead of turning into a bogus key.
        """
        rel = normalize_workspace_path(path, file_dir=self.file_dir)
        if rel != (path or "").strip().lstrip("/"):
            logger.info("workspace path: folded executor host path {} -> {}", path, rel)
        return rel

    def _object_key(self, rel_path: str) -> str:
        """Map a workspace-relative path to its MinIO object key."""
        return f"{WORKSPACE_PREFIX}/{self.svid}/{rel_path}"

    def _cache_path(self, rel_path: str) -> Path:
        return Path(self.file_dir) / rel_path

    def _not_found_error(self, file_path: str) -> str:
        """ "File not found" plus, when warranted, WHY the path could not resolve.

        A bare "File 'X' not found" was actively unhelpful for the most common
        failure: handing back a code-interpreter host path. Naming the two
        namespaces is what lets the model fix it in one step instead of retrying
        the same path.
        """
        _, stripped = strip_executor_host_prefix((file_path or "").strip(), self.file_dir)
        if stripped:
            rel = normalize_workspace_path(file_path, file_dir=self.file_dir)
            return (
                f"File '{file_path}' not found. (Interpreted as workspace path '{rel}' — the code "
                f"interpreter's working directory IS the workspace root.) Nothing exists there; "
                f"call ls to see what the workspace holds."
            )
        head = (file_path or "").strip().lstrip("/").split("/", 1)[0]
        if file_path.startswith("/") and head in _HOST_ROOT_HINTS:
            return (
                f"File '{file_path}' not found. NOTE: this looks like a path on the code "
                f"interpreter's HOST filesystem. The file tools take WORKSPACE paths only — the "
                f"interpreter's working directory IS the workspace root, so its 'output/a.png' is "
                f"'/output/a.png' here. Retry with the workspace path, or call ls to list it."
            )
        return f"File '{file_path}' not found"

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
        try:
            return self.minio.get_object_sync(bucket_name=self._bucket(), object_name=self._object_key(rel_path))
        except S3Error as e:
            # Missing object -> "not found" (None), not a task-fatal error.
            if _is_missing_key(e):
                return None
            raise

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
        # Binary views (e.g. BytesIO.getbuffer() returns a memoryview) must be
        # copied to bytes, NOT stringified. The export_docx tool feeds MarkDocx's
        # ``getbuffer()`` memoryview here; without this branch it fell through to
        # ``str(content)`` and wrote the literal text ``<memory at 0x...>`` to
        # MinIO, producing an unopenable .docx. This is the choke point for every
        # binary deliverable written through write/awrite.
        if isinstance(content, (bytearray, memoryview)):
            return bytes(content)
        return str(content).encode("utf-8")

    # -- write --------------------------------------------------------------
    def write(self, file_path: str, content) -> WriteResult:
        rel = self._ws_rel(file_path)
        data = self._to_bytes(content)
        # cache first (fast local), then write-through to MinIO (truth).
        self._cache_write(rel, data)
        self._minio_put_sync(rel, data)
        return WriteResult(path="/" + rel)

    # -- read ---------------------------------------------------------------
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        rel = self._ws_rel(file_path)
        data = self._materialize(rel)
        if data is None:
            return ReadResult(error=self._not_found_error(file_path))
        text = _decode_workspace_text(data, rel)
        if text is None:
            # Binary: offset/limit are meaningless here (slicing bytes by "lines"
            # would corrupt the payload), so the whole object is decided on at once.
            return _binary_read_result(rel, data)
        lines = text.splitlines()
        start = offset
        end = offset + limit if limit is not None else None
        sliced = "\n".join(lines[start:end])
        return ReadResult(file_data=FileData(content=sliced, encoding="utf-8"))

    # -- ls (authoritative from MinIO) --------------------------------------
    def ls(self, path: str = "") -> LsResult:
        rel_prefix = self._ws_rel(path) if path else ""
        object_prefix = f"{WORKSPACE_PREFIX}/{self.svid}/"
        if rel_prefix:
            # Terminate the prefix at a directory boundary. Without the slash,
            # ``ls("/uploads/年报")`` also matches a sibling ``年报备份/`` — harmless
            # when uploads were flat, wrong as soon as a folder upload puts real
            # sibling directories in there.
            object_prefix += rel_prefix.rstrip("/") + "/"
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
        rel = self._ws_rel(file_path)
        data = self._materialize(rel)
        if data is None:
            return EditResult(error=self._not_found_error(file_path))
        text = _decode_workspace_text(data, rel)
        if text is None:
            # Refuse BEFORE any write. A replace-decode here would turn every
            # undecodable byte into U+FFFD and the write-through would push that
            # back to MinIO — one successful edit permanently destroys the user's
            # original, which the workspace now carries next to its .md view.
            return EditResult(
                error=(
                    f"{BINARY_READ_ERROR_PREFIX} '{file_path}' is a binary file and cannot be edited as text "
                    f"(doing so would corrupt it). Regenerate it with the code interpreter instead."
                )
            )
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
    @staticmethod
    def _glob_patterns(pattern: str) -> tuple[str, ...]:
        """The spellings of ``pattern`` that should all mean the same thing.

        Two mismatches to absorb, both of which used to silently return zero
        matches for patterns we ourselves tell the model to write:

        - **Leading slash.** ``ls`` reports ``/uploads/a/b.csv`` and every tool
          argument in the prompt is written absolute, but matching happens against
          the workspace-RELATIVE key (``uploads/a/b.csv``). ``fnmatch`` is literal
          about that first character, so ``/uploads/**/*.xlsx`` — the exact
          spelling in the folder-upload guidance — matched nothing.
        - **``**`` spanning zero directories.** ``fnmatch`` has no ``**``; it
          treats it as a plain ``*`` that happens to cross ``/``. So
          ``uploads/**/*.csv`` demands at least one intermediate directory and
          skips ``uploads/top.csv`` — surprising for a pattern whose whole point
          is "anywhere under uploads". Collapsing ``**/`` gives that case its
          own candidate.
        """
        pat = (pattern or "").strip().lstrip("/")
        candidates = [pat]
        if "**/" in pat:
            candidates.append(pat.replace("**/", ""))
        return tuple(dict.fromkeys(c for c in candidates if c))

    @classmethod
    def _glob_matches(cls, rel_in_ws: str, pattern: str) -> bool:
        import fnmatch

        return any(
            fnmatch.fnmatch(rel_in_ws, pat) or fnmatch.fnmatch(os.path.basename(rel_in_ws), pat)
            for pat in cls._glob_patterns(pattern)
        )

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        base = self._ws_rel(path) if path else ""
        ls_res = self.ls(base)
        if ls_res.error is not None:
            return GlobResult(error=ls_res.error)
        prefix = f"/{WORKSPACE_PREFIX}/{self.svid}/"
        matches: list[FileInfo] = []
        for entry in ls_res.entries or []:
            rel = entry["path"]
            rel_in_ws = rel[len(prefix) :] if rel.startswith(prefix) else rel.lstrip("/")
            if self._glob_matches(rel_in_ws, pattern):
                matches.append(entry)
        return GlobResult(matches=matches)

    # -- grep ---------------------------------------------------------------
    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        from deepagents.backends.protocol import GrepMatch

        base = self._ws_rel(path) if path else ""
        ls_res = self.ls(base)
        if ls_res.error is not None:
            return GrepResult(error=ls_res.error)
        prefix = f"/{WORKSPACE_PREFIX}/{self.svid}/"
        matches: list = []

        skipped_large = 0
        skipped_binary = 0
        for entry in ls_res.entries or []:
            full = entry["path"]
            rel_in_ws = full[len(prefix) :] if full.startswith(prefix) else full.lstrip("/")
            # Same spelling tolerance as ``glob`` — an absolute filter must not
            # silently narrow the scan to nothing.
            if glob and not self._glob_matches(rel_in_ws, glob):
                continue
            # ``ls`` already reports the object size; use it to avoid downloading a
            # multi-MB original (uploads/ carries them since the dual-track write)
            # only to discover it holds no matchable text.
            if int(entry.get("size") or 0) > _MAX_GREP_BYTES:
                skipped_large += 1
                continue
            data = self._materialize(rel_in_ws)
            if data is None:
                continue
            text = _decode_workspace_text(data, rel_in_ws)
            if text is None:
                skipped_binary += 1
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    matches.append(GrepMatch(path=full, line=lineno, text=line))
        if skipped_large or skipped_binary:
            # Never let a bounded scan look like a complete one.
            logger.info(
                "workspace grep: skipped {} oversized and {} binary file(s) for pattern {!r}",
                skipped_large,
                skipped_binary,
                pattern,
            )
        return GrepResult(matches=matches)

    # -- upload / download (worker <-> workspace bulk ops) ------------------
    def upload_files(self, files: list[tuple[str, bytes]]) -> list:
        responses: list = []
        for raw_path, content in files:
            try:
                rel = self._ws_rel(raw_path)
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
                rel = self._ws_rel(raw_path)
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
        rel = self._ws_rel(file_path)
        data = self._to_bytes(content)
        await asyncio.to_thread(self._cache_write, rel, data)
        await self.minio.put_object(
            bucket_name=self._bucket(),
            object_name=self._object_key(rel),
            file=data,
        )
        return WriteResult(path="/" + rel)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        rel = self._ws_rel(file_path)
        data = await asyncio.to_thread(self._cache_read, rel)
        if data is None:
            try:
                data = await self.minio.get_object(bucket_name=self._bucket(), object_name=self._object_key(rel))
            except S3Error as e:
                # The agent asked for a file the workspace doesn't have (e.g. a URL
                # mistaken for a path, or a prior-turn deliverable under a different
                # session prefix). MinIO raises a *frozen-dataclass* S3Error on a
                # missing key; left unhandled it escapes the read tool, fails the
                # whole task, and on the resume path gets masked by langgraph's
                # traceback-trim as "cannot assign to field '__traceback__'". Treat
                # NoSuchKey as "not found" so deepagents returns a recoverable tool
                # error and the agent can re-plan instead of crashing.
                if not _is_missing_key(e):
                    raise
                data = None
            if data is not None:
                await asyncio.to_thread(self._cache_write, rel, data)
        if data is None:
            return ReadResult(error=self._not_found_error(file_path))
        text = _decode_workspace_text(data, rel)
        if text is None:
            # Same contract as the sync path: binary is decided whole, never sliced.
            return _binary_read_result(rel, data)
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
    def ensure_local(self, file_path: str) -> str | None:
        """Pull an object into the local cache; return its cache path (None if absent).

        The code interpreter reads the LOCAL ``file_dir`` (``os.walk`` for the E2B
        copy-in set, ``local_sync_path`` for the local executor) — it never talks to
        MinIO. So anything that arrived in the workspace by other means, notably a
        cross-turn seed, has to be materialized before the tool list is built or it
        is invisible to Python code even though ``ls`` shows it.
        """
        rel = self._ws_rel(file_path)
        data = self._materialize(rel)
        if data is None:
            return None
        return str(self._cache_path(rel))

    @staticmethod
    def md5_bytes(data: bytes) -> str:
        return hashlib.md5(data).hexdigest()
