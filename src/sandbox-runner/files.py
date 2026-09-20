"""Tar copy-in / copy-out for one session. Must not import bisheng."""

from __future__ import annotations

import hashlib
import io
import os
import tarfile

from leases import Lease

_BLOCK = 64 * 1024


class ZipSlipError(ValueError):
    pass


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
    return tarfile.open(fileobj=fileobj, mode=mode, encoding="utf-8", format=tarfile.PAX_FORMAT)


def _md5_file(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_BLOCK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def handle_put_files(lease: Lease, body: bytes, manifest: dict, max_copy_in_bytes: int) -> dict:
    skipped: list[dict] = []
    written: list[str] = []
    if not body:
        return {"skipped": skipped, "written": written}
    buf = io.BytesIO(body)
    try:
        tar = _open_tar(buf, "r:gz")
    except tarfile.TarError:
        buf.seek(0)
        tar = _open_tar(buf, "r:")
    with tar:
        for member in tar:
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
            dest = _safe_dest(lease.work_dir, rel)
            os.makedirs(os.path.dirname(dest) or lease.work_dir, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(dest, "wb") as out:
                while True:
                    chunk = source.read(_BLOCK)
                    if not chunk:
                        break
                    out.write(chunk)
            lease.md5_index[rel] = expected_md5 or _md5_file(dest)
            written.append(rel)
    return {"skipped": skipped, "written": written}


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
