"""Tar copy-in / copy-out for one session. Must not import bisheng."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import zlib
from collections.abc import Callable
from typing import BinaryIO

from leases import Lease

_BLOCK = 64 * 1024
# 4-byte length can claim up to 4 GiB. Cap the JSON before parsing it.
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


class ZipSlipError(ValueError):
    pass


class ManifestError(ValueError):
    pass


class ArchiveError(ValueError):
    """The copy-in tar after the manifest is not a readable (gzip) tar."""


class CopyInAbortedError(Exception):
    """The session was deleted while its copy-in was being extracted."""


class _Prefixed:
    """Read-only stream that yields ``head`` before the rest of ``fh``."""

    def __init__(self, head: bytes, fh: BinaryIO):
        self._head = head
        self._fh = fh

    def read(self, size: int = -1) -> bytes:
        if not self._head:
            return self._fh.read(size)
        if size is None or size < 0:
            out, self._head = self._head + self._fh.read(), b""
            return out
        out, self._head = self._head[:size], self._head[size:]
        if len(out) < size:
            out += self._fh.read(size - len(out))
        return out


def split_copy_in_body(body: bytes) -> tuple[dict, bytes]:
    """Split a copy-in body into the manifest and the tar.gz that follows it.

    Layout: 4-byte big-endian byte length, UTF-8 JSON ``{rel_path: md5}``, then tar.gz.
    The manifest used to ride in ``X-File-Manifest``. That header is buffered by the
    HTTP parser only until it exceeds 16 KiB, so a workspace of a few hundred files
    was rejected before the tar was read.
    """
    if len(body) < 4:
        raise ManifestError("manifest length missing")
    size = int.from_bytes(body[:4], "big")
    if size > MAX_MANIFEST_BYTES or 4 + size > len(body):
        raise ManifestError("manifest length invalid")
    try:
        manifest = json.loads(body[4 : 4 + size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("invalid manifest") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("invalid manifest")
    return manifest, body[4 + size :]


def read_copy_in_manifest(fh: BinaryIO) -> dict:
    """Read the framed manifest from a spooled copy-in body.

    Same layout as ``split_copy_in_body``. Leaves ``fh`` positioned at the
    first byte of the tar so the archive is read straight from disk.
    """
    head = fh.read(4)
    if len(head) < 4:
        raise ManifestError("manifest length missing")
    size = int.from_bytes(head, "big")
    if size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest length invalid")
    raw = fh.read(size)
    if len(raw) < size:
        raise ManifestError("manifest length invalid")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("invalid manifest") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("invalid manifest")
    return manifest


def _rel_from_member(name: str) -> str:
    rel = name.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    parts = rel.split("/")
    if rel.startswith("/") or any(p == ".." for p in parts):
        raise ZipSlipError(f"rejected tar member {name!r}")
    return "/".join(p for p in parts if p not in ("", "."))


def _safe_dest(work_dir: str, rel: str) -> str:
    dest = os.path.realpath(os.path.join(work_dir, *rel.split("/")))
    root = os.path.realpath(work_dir)
    if dest != root and not dest.startswith(root + os.sep):
        raise ZipSlipError(f"rejected tar member {rel!r}")
    return dest


def snapshot_tree(work_dir: str) -> dict[str, tuple[float, int]]:
    snap: dict[str, tuple[float, int]] = {}
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            abs_path = os.path.join(root, name)
            try:
                stat = os.stat(abs_path)
            except OSError:
                continue
            rel = os.path.relpath(abs_path, work_dir).replace(os.sep, "/")
            snap[rel] = (stat.st_mtime, stat.st_size)
    return snap


def _open_tar(fileobj, mode: str):
    # PAX + utf-8: Chinese workspace names (output/<中文>) must not use locale ascii.
    return tarfile.open(
        fileobj=fileobj, mode=mode, encoding="utf-8", format=tarfile.PAX_FORMAT
    )


def _md5_file(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_BLOCK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def handle_put_files(
    lease: Lease,
    body: bytes | BinaryIO,
    manifest: dict,
    max_copy_in_bytes: int,
    max_total_bytes: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Extract a copy-in tar into the lease work dir.

    ``body`` is bytes or a readable binary stream positioned at the tar (gzip or
    plain). The tar is read in stream mode, member by member, so the body never
    has to be held or spooled in full. Files over ``max_copy_in_bytes`` and files
    that would push the session's copied-in total over ``max_total_bytes`` are
    skipped and listed in ``skipped``. ``should_stop`` is polled between members
    and chunks; when it returns True extraction stops with CopyInAbortedError.
    """
    skipped: list[dict] = []
    written: list[str] = []
    fh: BinaryIO = io.BytesIO(body) if isinstance(body, bytes | bytearray) else body
    first = fh.read(1)
    if not first:
        return {"skipped": skipped, "written": written}
    try:
        tar = _open_tar(_Prefixed(first, fh), "r|*")
    except tarfile.TarError as exc:
        raise ArchiveError("invalid archive") from exc
    try:
        with tar:
            _extract_members(
                tar,
                lease,
                manifest,
                max_copy_in_bytes,
                max_total_bytes,
                should_stop,
                skipped,
                written,
            )
    except (tarfile.TarError, EOFError, zlib.error) as exc:
        raise ArchiveError("invalid archive") from exc
    return {"skipped": skipped, "written": written}


def _extract_members(
    tar: tarfile.TarFile,
    lease: Lease,
    manifest: dict,
    max_copy_in_bytes: int,
    max_total_bytes: int | None,
    should_stop: Callable[[], bool] | None,
    skipped: list[dict],
    written: list[str],
) -> None:
    def _check_stop() -> None:
        if should_stop is not None and should_stop():
            raise CopyInAbortedError()

    total = sum(lease.copy_in_sizes.values())
    for member in tar:
        _check_stop()
        if not member.isfile():
            continue
        rel = _rel_from_member(member.name)
        if not rel:
            continue
        expected_md5 = manifest.get(rel)
        if expected_md5 and lease.md5_index.get(rel) == expected_md5:
            continue
        if member.size > max_copy_in_bytes:
            skipped.append({"path": rel, "size": member.size})
            continue
        new_total = total - lease.copy_in_sizes.get(rel, 0) + member.size
        if max_total_bytes is not None and new_total > max_total_bytes:
            skipped.append({"path": rel, "size": member.size})
            continue
        dest = _safe_dest(lease.work_dir, rel)
        os.makedirs(os.path.dirname(dest) or lease.work_dir, exist_ok=True)
        source = tar.extractfile(member)
        if source is None:
            continue
        with source, open(dest, "wb") as out:
            while True:
                _check_stop()
                chunk = source.read(_BLOCK)
                if not chunk:
                    break
                out.write(chunk)
        lease.md5_index[rel] = expected_md5 or _md5_file(dest)
        lease.copy_in_sizes[rel] = member.size
        total = new_total
        written.append(rel)


def handle_get_files(lease: Lease) -> bytes:
    if not lease.copy_out_allowed or lease.pre_exec_snapshot is None:
        empty = io.BytesIO()
        with _open_tar(empty, "w:gz"):
            pass
        return empty.getvalue()
    pre = lease.pre_exec_snapshot
    post = snapshot_tree(lease.work_dir)
    changed = [rel for rel, meta in post.items() if rel not in pre or pre[rel] != meta]
    buf = io.BytesIO()
    with _open_tar(buf, "w:gz") as tar:
        for rel in changed:
            abs_path = os.path.join(lease.work_dir, *rel.split("/"))
            if os.path.isfile(abs_path):
                tar.add(abs_path, arcname=rel)
    return buf.getvalue()
