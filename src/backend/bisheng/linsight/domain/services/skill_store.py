"""Object-storage persistence for Linsight skill bundles (F035 Track D, design §7).

A skill is a "bundle": a mapping of relative paths to bytes, with a mandatory
``SKILL.md`` at its root whose frontmatter ``name`` equals the skill name
(deepagents hard constraint). The human-facing ``display_name`` lives in
``metadata.display-name`` and in the ``linsight_skill`` table; it is the only
name surfaced in UI.

**Object storage is the single source of truth**, keyed by content::

    linsight/skills/{tenant_id}/{name}/{content_hash}.zip

Nodes materialize a bundle into a local cache directory on demand. The cache is
disposable: the directory name *is* the content hash, so a present directory can
never hold stale bytes and no freshness probe is needed.

Why content-addressed rather than a stable ``{name}.zip`` key: with a stable key
two concurrent edits race in two places at once — the object store keeps one
winner and the DB row keeps possibly the *other*. The row would then advertise a
hash the object no longer has, and nothing could ever detect it. Putting the hash
in the key means every write lands on its own object, so whichever UPDATE wins
still points at bytes that match it. Superseded objects become garbage, collected
out-of-band (see ``delete``) rather than by the writer — a writer that pruned
"other" versions would delete a concurrent writer's freshly published bundle.

This replaces the previous local-filesystem layout, which made multi-node
deployments inconsistent by construction: only the node that received an upload
had the bytes, and a Linsight worker elsewhere silently skipped the skill.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from uuid import uuid4

import yaml
from pypinyin import lazy_pinyin

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.cache.utils import CACHE_DIR
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

SKILL_MD = "SKILL.md"
# Object-key namespace for skill bundles, sibling to the workspace's "workspace/".
SKILL_OBJECT_PREFIX = "linsight/skills"
# Legacy on-disk layout, still used by the one-off migration/restore scripts to
# find bundles a pre-object-storage release left on a node's local disk.
LEGACY_TENANT_SKILLS_DIR = "data/skills"

# Upload payload limit: the .md / .zip / .skill bytes that arrive over HTTP.
MAX_BUNDLE_SIZE = 10 * 1024 * 1024
# Unpacked limit: sum of every extracted file's contents (also the GitHub import's
# total download size). Deliberately larger than the upload limit — an archive of
# pptx templates/fonts/images compresses well and expands past 10MB while the .zip
# itself is far below it. This line is the zip-bomb guard, not a second copy of the
# upload limit. (deepagents' MAX_SKILL_FILE_SIZE is a per-SKILL.md cap, unrelated.)
MAX_UNPACKED_SIZE = 100 * 1024 * 1024
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_DISPLAY_NAME_LEN = 255

DISPLAY_NAME_META_KEY = "display-name"
SOP_ID_META_KEY = "sop-id"

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Earliest timestamp the zip format can represent. Fixed so packing is reproducible.
_ZIP_FIXED_MTIME = (1980, 1, 1, 0, 0, 0)


def slugify_pinyin(text: str, max_len: int = MAX_NAME_LEN) -> str:
    """Build a deepagents-legal skill name from arbitrary (Chinese) text.

    ASCII letters/digits are kept lowercased, CJK characters become pinyin
    syllables, everything else collapses into single hyphens.
    Returns "" when nothing survives — caller decides the fallback name.
    """
    parts: list[str] = []
    for ch in text:
        if ch.isascii() and ch.isalnum():
            parts.append(ch.lower())
        elif ch.isascii():
            parts.append("-")
        else:
            # lazy_pinyin echoes characters it cannot transliterate (e.g. full-width
            # punctuation) — only accept pure-ASCII alphanumeric syllables.
            py = lazy_pinyin(ch)
            syllable = py[0].strip().lower() if py else ""
            parts.append(f"-{syllable}-" if syllable.isascii() and syllable.isalnum() else "-")
    slug = re.sub(r"-+", "-", "".join(parts)).strip("-")
    slug = slug[:max_len].rstrip("-")
    # Truncation may leave a trailing fragment producing "--"; normalize again.
    return re.sub(r"-+", "-", slug)


def validate_skill_name(name: str) -> str | None:
    """Return an error message when ``name`` violates the spec, else None.

    Mirrors deepagents ``_validate_skill_name`` so a skill we accept is always
    loadable by the middleware.
    """
    if not name:
        return "name is required"
    if len(name) > MAX_NAME_LEN:
        return f"name exceeds {MAX_NAME_LEN} characters"
    if not _NAME_RE.match(name):
        return "name must be lowercase alphanumeric with single hyphens only"
    return None


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split SKILL.md into (frontmatter dict, body). Raises ValueError when malformed."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("missing YAML frontmatter (--- block) in SKILL.md")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return meta, text[match.end() :]


def render_skill_md(meta: dict, body: str) -> str:
    """Render SKILL.md from an arbitrary frontmatter mapping + body.

    Keeps every frontmatter key as-is (document order preserved) — used when an
    imported bundle's frontmatter must be rewritten without dropping foreign keys
    like ``license`` or ``allowed-tools``.
    """
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
    return f"---\n{front}\n---\n\n{body.strip()}\n"


def compose_skill_md(
    name: str,
    description: str,
    body: str,
    display_name: str | None = None,
    allowed_tools: str | None = None,
    extra_metadata: dict[str, str] | None = None,
) -> str:
    """Render a canonical SKILL.md from structured fields (form-create path)."""
    meta: dict = {"name": name, "description": description}
    if allowed_tools:
        meta["allowed-tools"] = allowed_tools
    metadata: dict[str, str] = {}
    if display_name:
        metadata[DISPLAY_NAME_META_KEY] = display_name
    if extra_metadata:
        metadata.update({k: str(v) for k, v in extra_metadata.items()})
    if metadata:
        meta["metadata"] = metadata
    return render_skill_md(meta, body)


def unpack_zip_bytes(data: bytes) -> dict[str, bytes]:
    """Extract a .zip/.skill archive into {relative_posix_path: bytes}.

    A single top-level wrapper directory (the common "zip a folder" shape) is
    stripped so SKILL.md lands at the bundle root. Raises ValueError when the
    archive is unreadable or contains no SKILL.md.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid zip archive") from exc
    files: dict[str, bytes] = {}
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = info.filename.replace("\\", "/").lstrip("/")
            if not path or path.startswith("__MACOSX/") or PurePosixPath(path).name == ".DS_Store":
                continue
            files[path] = zf.read(info)
    if not files:
        raise ValueError("empty archive")
    if SKILL_MD not in files:
        tops = {p.split("/", 1)[0] for p in files}
        if len(tops) == 1 and all("/" in p for p in files):
            prefix = next(iter(tops)) + "/"
            files = {p[len(prefix) :]: c for p, c in files.items()}
    if SKILL_MD not in files:
        raise ValueError("SKILL.md not found at archive root")
    return files


def _safe_rel_path(rel: str) -> PurePosixPath:
    """Normalize a bundle-relative path, rejecting traversal/absolute forms."""
    path = PurePosixPath(rel.replace("\\", "/"))
    if path.is_absolute() or any(part in ("..", "") for part in path.parts) or not path.parts:
        raise ValueError(f"illegal bundle path: {rel!r}")
    return path


def bundle_content_hash(files: dict[str, bytes]) -> str:
    """Content identity of a bundle: sha256 over the *file mapping*.

    Deliberately **not** the hash of the packed archive. ``zipfile`` stamps every
    entry with ``time.localtime()`` and writes them in dict-iteration order, so
    packing the same bundle twice produces different bytes. Hashing the archive
    would make the built-in seeder see "changed" on every single startup and
    rewrite every tenant's copy forever, and would grow one local cache directory
    per boot. Hash the mapping and the identity is stable across processes,
    machines and repacks.
    """
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[rel]).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def pack_bundle_zip(files: dict[str, bytes]) -> bytes:
    """Pack a bundle into a deterministic .zip — the object-storage transport form.

    Sorted entries + a fixed timestamp keep the stored object reproducible, so the
    same mapping never churns the object store. Bundle *identity* still comes from
    ``bundle_content_hash``; this only avoids gratuitously different archive bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(files):
            info = zipfile.ZipInfo(str(_safe_rel_path(rel)), date_time=_ZIP_FIXED_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[rel])
    return buffer.getvalue()


class BundleRef(NamedTuple):
    """What a write produced: the row's pointer plus its total byte size."""

    size: int
    content_hash: str
    object_key: str


class SkillStore:
    """Object-storage persistence for skill bundles, with a local materialize cache.

    ``content_hash`` identifies a bundle version and is required by every read —
    callers already hold it on the ``linsight_skill`` row, so resolving a bundle
    costs zero extra queries and zero metadata round-trips.
    """

    def __init__(self, root: str | Path | None = None, minio=None):
        """``root`` is the *local cache* root (not authoritative storage)."""
        if root is None:
            conf = bisheng_settings.get_linsight_conf()
            root = conf.skills_cache_dir or Path(CACHE_DIR) / "linsight_skills"
        self.root = Path(root).resolve()
        self._minio = minio

    @property
    def minio(self):
        """Resolved lazily: ``get_minio_storage_sync`` self-registers, so this works
        in the API process, a Celery worker and the Linsight worker alike."""
        if self._minio is None:
            self._minio = get_minio_storage_sync()
        return self._minio

    def _bucket(self) -> str:
        return self.minio.bucket

    # ---- keys & cache paths ----
    def object_key(self, tenant_id: int, name: str, content_hash: str) -> str:
        """Object key stored in ``linsight_skill.object_path``.

        The tenant segment is the numeric ``tenant_id`` and is deliberately NOT
        the F017 ``tenant_{code}/`` key-prefix convention. Skills are strictly
        tenant-private (every DAO read runs under ``strict_tenant_filter``), and
        keeping the key outside that convention means ``_translate_to_root_prefix``
        can never kick in — a Root-tenant fallback here would let a sub-tenant
        read the Root tenant's skills. Do not "align" this with the F017 prefix.
        """
        return f"{SKILL_OBJECT_PREFIX}/{tenant_id}/{name}/{content_hash}.zip"

    def _skill_prefix(self, tenant_id: int, name: str) -> str:
        return f"{SKILL_OBJECT_PREFIX}/{tenant_id}/{name}/"

    def cache_dir(self, tenant_id: int, name: str, content_hash: str) -> Path:
        """Local directory holding one materialized bundle version."""
        return self.root / str(tenant_id) / name / content_hash

    # ---- bundle IO ----
    def exists(self, tenant_id: int, name: str, content_hash: str) -> bool:
        if (self.cache_dir(tenant_id, name, content_hash) / SKILL_MD).is_file():
            return True
        return bool(
            self.minio.object_exists_sync(
                bucket_name=self._bucket(), object_name=self.object_key(tenant_id, name, content_hash)
            )
        )

    def write_bundle(self, tenant_id: int, name: str, files: dict[str, bytes]) -> BundleRef:
        """Publish a bundle version and return its pointer.

        The object PUT is a single atomic operation, so there is no window in
        which half a bundle is visible. Superseded versions are intentionally
        left behind — see the module docstring.
        """
        if SKILL_MD not in files:
            raise ValueError("bundle must contain SKILL.md")
        total = 0
        for rel, content in files.items():
            _safe_rel_path(rel)
            total += len(content)
        if total > MAX_UNPACKED_SIZE:
            raise ValueError(f"bundle exceeds {MAX_UNPACKED_SIZE} bytes when unpacked")

        content_hash = bundle_content_hash(files)
        key = self.object_key(tenant_id, name, content_hash)
        self.minio.put_object_sync(bucket_name=self._bucket(), object_name=key, file=pack_bundle_zip(files))
        # Seed the local cache from what we already hold, so the writing node
        # never round-trips to fetch back bytes it just uploaded.
        self._install_cache(self.cache_dir(tenant_id, name, content_hash), files)
        return BundleRef(size=total, content_hash=content_hash, object_key=key)

    def read_text(self, tenant_id: int, name: str, content_hash: str, rel: str = SKILL_MD) -> str:
        target = self.materialize(tenant_id, name, content_hash) / _safe_rel_path(rel)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target.read_text(encoding="utf-8", errors="replace")

    def read_bytes(self, tenant_id: int, name: str, content_hash: str, rel: str) -> bytes:
        """Read a bundle file as raw bytes (binary-safe).

        ``read_text`` decodes utf-8 with ``errors="replace"`` and is lossy for
        binary assets (images, fonts) bundled alongside SKILL.md. The skill
        copy-into-workspace path (skill_provisioning) needs faithful bytes, so it
        reads through here instead.
        """
        target = self.materialize(tenant_id, name, content_hash) / _safe_rel_path(rel)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target.read_bytes()

    def list_files(self, tenant_id: int, name: str, content_hash: str) -> list[dict]:
        """Bundle file tree as [{path, size}], SKILL.md first, then sorted.

        Returns ``[]`` when the bundle cannot be resolved, matching the previous
        "missing directory" behaviour so callers keep degrading the same way.
        """
        try:
            base = self.materialize(tenant_id, name, content_hash)
        except FileNotFoundError:
            return []
        entries = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                entries.append({"path": p.relative_to(base).as_posix(), "size": p.stat().st_size})
        entries.sort(key=lambda e: (e["path"] != SKILL_MD, e["path"]))
        return entries

    def delete(self, tenant_id: int, name: str) -> bool:
        """Remove every stored version of a skill, plus its local cache.

        Deleting by prefix (rather than by a single hash) is what finally clears
        superseded versions: the skill is gone, so no concurrent writer can be
        publishing a version worth keeping.
        """
        prefix = self._skill_prefix(tenant_id, name)
        removed = False
        for obj in self.minio.minio_client_sync.list_objects(self._bucket(), prefix=prefix, recursive=True):
            self.minio.remove_object_sync(bucket_name=self._bucket(), object_name=obj.object_name)
            removed = True
        local = self.root / str(tenant_id) / name
        if local.exists():
            shutil.rmtree(local, ignore_errors=True)
            removed = True
        return removed

    # ---- materialization ----
    def materialize(self, tenant_id: int, name: str, content_hash: str) -> Path:
        """Return the local directory holding this bundle version, fetching it if absent.

        A cache hit performs no network I/O at all: the directory name is the
        content hash, so its presence already proves the bytes are the right ones.
        """
        dst = self.cache_dir(tenant_id, name, content_hash)
        if (dst / SKILL_MD).is_file():
            return dst
        key = self.object_key(tenant_id, name, content_hash)
        data = self.minio.get_object_sync(bucket_name=self._bucket(), object_name=key)
        if data is None:
            raise FileNotFoundError(f"skill bundle object not found: {key}")
        self._install_cache(dst, self._unpack_for_cache(unpack_zip_bytes(data), key))
        return dst

    @staticmethod
    def _unpack_for_cache(files: dict[str, bytes], key: str) -> dict[str, bytes]:
        """Re-apply the upload path's guards to bytes coming back from storage.

        Materialization is a *second* write-to-disk path: the size cap lives in
        ``skill_service._parse_upload`` and the traversal check in the old
        ``write_bundle``, so neither protects this one. A corrupted or tampered
        object must not be able to fill the disk or escape the cache directory.
        """
        total = 0
        for rel, content in files.items():
            _safe_rel_path(rel)
            total += len(content)
            if total > MAX_UNPACKED_SIZE:
                raise ValueError(f"skill bundle {key} exceeds {MAX_UNPACKED_SIZE} bytes when unpacked")
        return files

    def _install_cache(self, dst: Path, files: dict[str, bytes]) -> None:
        """Atomically place a bundle's files at ``dst`` (a content-hash directory)."""
        if (dst / SKILL_MD).is_file():
            return
        tmp = dst.with_name(f"{dst.name}.tmp-{os.getpid()}-{uuid4().hex[:8]}")
        try:
            for rel, content in files.items():
                target = tmp / _safe_rel_path(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                tmp.replace(dst)
            except OSError:
                # Someone materialized the same hash first. os.replace refuses a
                # non-empty target rather than "winning", and that is fine: the
                # directory name is the content hash, so their bytes equal ours.
                pass
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
