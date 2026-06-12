"""Disk storage for Linsight skills (F035 Track D, design §7).

Layout under SKILLS_ROOT (``linsight_conf.skills_root``)::

    built-in/<name>/SKILL.md            # kernel built-in skills, loaded directly, never via API
    data/skills/{tenant_id}/<name>/     # tenant custom skill bundles (SKILL.md + optional assets)

A skill is a directory ("bundle"): ``SKILL.md`` is mandatory and its frontmatter
``name`` must equal the directory name (deepagents hard constraint). The
human-facing ``display_name`` lives in ``metadata.display-name`` and in the
``linsight_skill`` table; it is the only name surfaced in UI.

Multi-node deployments must mount SKILLS_ROOT on a shared volume (design §7.1).
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

import yaml
from pypinyin import lazy_pinyin

from bisheng.common.services.config_service import settings as bisheng_settings

SKILL_MD = "SKILL.md"
BUILTIN_DIR = "built-in"
TENANT_SKILLS_DIR = "data/skills"

MAX_BUNDLE_SIZE = 10 * 1024 * 1024  # whole bundle, aligned with deepagents MAX_SKILL_FILE_SIZE
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_DISPLAY_NAME_LEN = 255

DISPLAY_NAME_META_KEY = "display-name"
SOP_ID_META_KEY = "sop-id"

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


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
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
    return f"---\n{front}\n---\n\n{body.rstrip()}\n"


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


class SkillStore:
    """Filesystem persistence for skill bundles. DB metadata stays in the DAO."""

    def __init__(self, root: str | Path | None = None):
        if root is None:
            root = bisheng_settings.get_linsight_conf().skills_root
        self.root = Path(root).resolve()

    # ---- paths (also consumed by skill_middleware as SkillsMiddleware sources) ----
    def builtin_dir(self) -> Path:
        return self.root / BUILTIN_DIR

    def tenant_dir(self, tenant_id: int) -> Path:
        return self.root / TENANT_SKILLS_DIR / str(tenant_id)

    def skill_dir(self, tenant_id: int, name: str) -> Path:
        return self.tenant_dir(tenant_id) / name

    def object_path(self, tenant_id: int, name: str) -> str:
        """Relative path stored in linsight_skill.object_path."""
        return f"{TENANT_SKILLS_DIR}/{tenant_id}/{name}"

    # ---- bundle IO ----
    def exists(self, tenant_id: int, name: str) -> bool:
        return (self.skill_dir(tenant_id, name) / SKILL_MD).is_file()

    def write_bundle(self, tenant_id: int, name: str, files: dict[str, bytes]) -> int:
        """(Over)write a whole skill bundle; returns total size in bytes.

        Writes into a sibling tmp dir first, then swaps — a crash mid-write
        never leaves a half-bundle at the live path.
        """
        if SKILL_MD not in files:
            raise ValueError("bundle must contain SKILL.md")
        dst = self.skill_dir(tenant_id, name)
        tmp = dst.with_name(dst.name + ".tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        total = 0
        try:
            for rel, content in files.items():
                rel_path = _safe_rel_path(rel)
                target = tmp / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                total += len(content)
            if dst.exists():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(dst)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        return total

    def read_text(self, tenant_id: int, name: str, rel: str = SKILL_MD) -> str:
        target = self.skill_dir(tenant_id, name) / _safe_rel_path(rel)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        return target.read_text(encoding="utf-8", errors="replace")

    def list_files(self, tenant_id: int, name: str) -> list[dict]:
        """Bundle file tree as [{path, size}], SKILL.md first, then sorted."""
        base = self.skill_dir(tenant_id, name)
        if not base.is_dir():
            return []
        entries = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                entries.append({"path": p.relative_to(base).as_posix(), "size": p.stat().st_size})
        entries.sort(key=lambda e: (e["path"] != SKILL_MD, e["path"]))
        return entries

    def delete(self, tenant_id: int, name: str) -> bool:
        dst = self.skill_dir(tenant_id, name)
        if not dst.exists():
            return False
        shutil.rmtree(dst)
        return True
