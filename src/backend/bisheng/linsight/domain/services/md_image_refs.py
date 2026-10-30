"""Local image references inside a task-mode markdown deliverable.

A deliverable md points at workspace images (``![](charts/a.png)``), which only
resolve inside the run's workspace. Every consumer that takes the md out of the
workspace has to carry those images along:

- the export tools and the pdf / docx download inline them as ``data:`` URIs
  (``sanitize_html_for_pdf`` drops scheme-less ``src`` values, so a plain path
  never reaches the converter);
- the markdown download packs md + images into a zip with rewritten paths.

The resolution rule is shared here so all of them agree on which file an
``src`` means.
"""

from __future__ import annotations

import base64
import io
import mimetypes
import posixpath
import re
import zipfile
from collections.abc import Awaitable, Callable
from urllib.parse import unquote

# ![alt](src "title") — group 2 is the src; <img ... src="..."> — group 2 likewise.
_MD_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\(\s*<?)([^)\s>]+)")
_HTML_IMG_RE = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*[\"'])([^\"']+)", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# workspace path -> bytes for the paths that exist (missing ones are left out).
FetchFiles = Callable[[list[str]], Awaitable[dict[str, bytes]]]


def image_path_candidates(src: str, source_path: str) -> list[str]:
    """Workspace-relative paths an image src may point at, most specific first.

    ``/output/a.png`` is workspace-rooted. A bare ``charts/a.png`` is tried
    relative to the md's directory first (``output/report.md`` -> ``output/charts/a.png``),
    then from the workspace root, because the workspace contract treats a
    slash-less path as workspace-rooted (``output/charts/a.png`` written inside
    ``output/report.md``). Candidates escaping the root are dropped.
    """
    # Models sometimes percent-encode non-ASCII names (中文.png -> %E4%B8%AD...).
    src = unquote(src)
    if src.startswith("/"):
        joined = [src.lstrip("/")]
    else:
        joined = [posixpath.join(posixpath.dirname(source_path.lstrip("/")), src), src]
    candidates: list[str] = []
    for path in joined:
        rel = posixpath.normpath(path)
        if rel in (".", "..") or rel.startswith("../") or rel in candidates:
            continue
        candidates.append(rel)
    return candidates


def has_local_image_refs(md: str) -> bool:
    """True when the md references at least one image by path (not http/data)."""
    return any(
        not _SCHEME_RE.match(m.group(2)) for pattern in (_MD_IMAGE_RE, _HTML_IMG_RE) for m in pattern.finditer(md)
    )


async def resolve_local_images(
    md: str, source_path: str, fetch: FetchFiles
) -> tuple[dict[str, tuple[str, bytes]], list[str]]:
    """Find the workspace image behind every local src.

    Returns ``({src: (workspace_path, bytes)}, [srcs not found])``. Remote
    (``http(s):``) and inline (``data:``) srcs are not local and are skipped.
    """
    srcs: dict[str, list[str]] = {}
    for pattern in (_MD_IMAGE_RE, _HTML_IMG_RE):
        for m in pattern.finditer(md):
            src = m.group(2)
            if not _SCHEME_RE.match(src):
                srcs.setdefault(src, image_path_candidates(src, source_path))
    if not srcs:
        return {}, []

    paths = sorted({p for candidates in srcs.values() for p in candidates if _image_mime(p)})
    files = await fetch(paths) if paths else {}

    found: dict[str, tuple[str, bytes]] = {}
    missing: list[str] = []
    for src, candidates in srcs.items():
        path = next((p for p in candidates if files.get(p)), None)
        if path is None:
            missing.append(src)
        else:
            found[src] = (path, files[path])
    return found, missing


def rewrite_image_refs(md: str, mapping: dict[str, str]) -> str:
    """Replace each mapped src (markdown and <img> forms); others are left as-is."""

    def _sub(m: re.Match) -> str:
        new = mapping.get(m.group(2))
        return m.group(1) + new if new else m.group(0)

    for pattern in (_MD_IMAGE_RE, _HTML_IMG_RE):
        md = pattern.sub(_sub, md)
    return md


async def inline_local_images(md: str, source_path: str, fetch: FetchFiles) -> tuple[str, list[str]]:
    """Inline workspace images as ``data:`` URIs; return (md, srcs not found)."""
    found, missing = await resolve_local_images(md, source_path, fetch)
    mapping = {
        src: f"data:{_image_mime(path)};base64,{base64.b64encode(data).decode('ascii')}"
        for src, (path, data) in found.items()
    }
    return rewrite_image_refs(md, mapping), missing


async def build_markdown_bundle(md: str, md_file_name: str, source_path: str, fetch: FetchFiles) -> bytes | None:
    """Zip the md with the images it references; None when no image was found.

    Images go to ``images/<name>`` (deduplicated with a numeric suffix) and the
    md is rewritten to point there, so it renders when opened from the unpacked
    folder. Srcs that resolve to nothing are left untouched.
    """
    found, _ = await resolve_local_images(md, source_path, fetch)
    if not found:
        return None

    mapping: dict[str, str] = {}
    entries: dict[str, str] = {}  # workspace path -> zip name
    used: set[str] = set()
    for src, (path, _data) in found.items():
        if path not in entries:
            stem, ext = posixpath.splitext(posixpath.basename(path))
            name, n = f"images/{stem}{ext}", 1
            while name in used:
                n += 1
                name = f"images/{stem}-{n}{ext}"
            used.add(name)
            entries[path] = name
        mapping[src] = entries[path]

    data_by_path = dict(found.values())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(md_file_name, rewrite_image_refs(md, mapping))
        for path, name in entries.items():
            zf.writestr(name, data_by_path[path])
    return buf.getvalue()


def _image_mime(path: str) -> str | None:
    mime = mimetypes.guess_type(path)[0]
    return mime if mime and mime.startswith("image/") else None
