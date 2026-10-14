"""Copy a task workspace into a private run dir and harvest results back.

The run dir is owned by an untrusted uid. Copy-in happens before that uid has
run anything, into a dir root just created. Copy-back happens only after every
process of the uid is confirmed dead, but the content is still treated as
hostile: every component is opened with ``O_NOFOLLOW`` and every decision is
made on ``fstat`` of the very fd that is then read, so a symlink, FIFO, device
or hard link planted by the script is never followed or harvested.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import uuid
from dataclasses import dataclass, field

from loguru import logger

_SKIP_DIRS = ("__pycache__",)
_COPY_CHUNK = 1024 * 1024

# (size, mtime_ns) of a file, used to tell what a run changed.
FileMeta = tuple[int, int]


@dataclass
class CopyInResult:
    index: dict[str, FileMeta] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    copied_bytes: int = 0


def _skip_name(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_DIRS


def copy_in(
    src_dir: str,
    dst_dir: str,
    uid: int | None,
    file_limit: int,
    total_limit: int,
) -> CopyInResult:
    """Copy regular files of ``src_dir`` into ``dst_dir`` and hand them to ``uid``.

    Skips symlinks, sockets, FIFOs, devices, hidden names and ``__pycache__``.
    A file above ``file_limit`` is skipped; once ``total_limit`` would be
    exceeded every remaining file is skipped. ``uid=None`` leaves ownership
    unchanged (used by tests that do not run as root).
    """
    result = CopyInResult()
    for root, dirs, files in os.walk(src_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not _skip_name(d) and not os.path.islink(os.path.join(root, d)))
        rel_root = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        if rel_root != ".":
            os.makedirs(target_root, mode=0o755, exist_ok=True)
            _hand_over(target_root, uid, 0o755)
        for name in sorted(files):
            if _skip_name(name):
                continue
            src = os.path.join(root, name)
            rel = name if rel_root == "." else os.path.join(rel_root, name)
            try:
                st = os.lstat(src)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_size > file_limit or result.copied_bytes + st.st_size > total_limit:
                result.skipped.append(rel)
                continue
            dst = os.path.join(target_root, name)
            shutil.copy2(src, dst, follow_symlinks=False)
            mode = 0o755 if st.st_mode & 0o111 else 0o644
            _hand_over(dst, uid, mode)
            result.index[rel] = (st.st_size, st.st_mtime_ns)
            result.copied_bytes += st.st_size
    return result


def _hand_over(path: str, uid: int | None, mode: int) -> None:
    if uid is not None:
        os.lchown(path, uid, uid)
    os.chmod(path, mode)


def remove_path(path: str) -> None:
    """Remove whatever is at ``path`` without following a symlink there."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def _ensure_real_dir(path: str, uid: int | None) -> None:
    """Make ``path`` a real directory, replacing a symlink or file planted there."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None and stat.S_ISDIR(st.st_mode):
        return
    if st is not None:
        os.unlink(path)
    os.mkdir(path, 0o755)
    _hand_over(path, uid, 0o755)


def _real_dir_chain(root: str, rel_dir: str) -> str | None:
    """``root/rel_dir`` if every component below ``root`` is a real directory."""
    current = root
    for part in [p for p in rel_dir.split(os.sep) if p]:
        current = os.path.join(current, part)
        try:
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                return None
        except FileNotFoundError:
            return None
    return current


def _in_sync(path: str, meta: FileMeta) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and (st.st_size, st.st_mtime_ns) == meta


def sync_in(
    src_dir: str,
    dst_dir: str,
    uid: int | None,
    index: dict[str, FileMeta],
    file_limit: int,
    total_limit: int,
) -> CopyInResult:
    """Bring a retained run dir in line with the workspace, copying only what changed.

    ``index`` is what the previous call left R and W agreeing on. A file is
    copied when it is new, when W changed, or when R no longer holds the exact
    copy (the script deleted, edited or replaced it). Files gone from W are
    removed from R. ``total_limit`` counts only the bytes copied by this call.

    The caller guarantees no process of ``uid`` is alive, so nothing in
    ``dst_dir`` moves underneath: symlinks, FIFOs or hard links planted by the
    previous run are removed and replaced, never written through.
    """
    result = CopyInResult()
    for root, dirs, files in os.walk(src_dir, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not _skip_name(d) and not os.path.islink(os.path.join(root, d)))
        rel_root = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        if rel_root != ".":
            _ensure_real_dir(target_root, uid)
        for name in sorted(files):
            if _skip_name(name):
                continue
            src = os.path.join(root, name)
            rel = name if rel_root == "." else os.path.join(rel_root, name)
            try:
                st = os.lstat(src)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            meta = (st.st_size, st.st_mtime_ns)
            dst = os.path.join(target_root, name)
            if index.get(rel) == meta and _in_sync(dst, meta):
                result.index[rel] = meta
                continue
            remove_path(dst)
            if st.st_size > file_limit or result.copied_bytes + st.st_size > total_limit:
                result.skipped.append(rel)
                continue
            shutil.copy2(src, dst, follow_symlinks=False)
            _hand_over(dst, uid, 0o755 if st.st_mode & 0o111 else 0o644)
            result.index[rel] = meta
            result.copied_bytes += st.st_size
    for rel in index.keys() - result.index.keys():
        parent = _real_dir_chain(dst_dir, os.path.dirname(rel))
        if parent is not None:
            remove_path(os.path.join(parent, os.path.basename(rel)))
    return result


def copy_out(
    src_dir: str,
    dst_dir: str,
    index: dict[str, FileMeta],
    exclude: set[str],
    file_limit: int,
    total_limit: int,
    record: dict[str, FileMeta] | None = None,
) -> list[str]:
    """Harvest new or changed regular files of ``src_dir`` into ``dst_dir``.

    ``index`` lists what ``src_dir`` held when the run started; a file whose
    ``(size, mtime_ns)`` still matches is not copied back. ``exclude`` names
    top-level files never harvested (the script itself). Deletions are not
    mirrored. Returns the relative paths written; when ``record`` is given,
    each written file's ``(size, mtime_ns)`` (identical in both dirs) is stored
    in it.
    """
    written: list[str] = []
    budget = [total_limit]
    try:
        root_fd = os.open(src_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        logger.exception("local isolation: run dir {} cannot be opened for copy-back", src_dir)
        return written
    try:
        _copy_out_dir(root_fd, "", dst_dir, index, exclude, file_limit, budget, written, record)
    finally:
        os.close(root_fd)
    return written


def _copy_out_dir(
    dir_fd: int,
    rel_dir: str,
    dst_root: str,
    index: dict[str, FileMeta],
    exclude: set[str],
    file_limit: int,
    budget: list[int],
    written: list[str],
    record: dict[str, FileMeta] | None,
) -> None:
    with os.scandir(dir_fd) as entries:
        names = sorted(entry.name for entry in entries)
    for name in names:
        if _skip_name(name) or (not rel_dir and name in exclude):
            continue
        rel = os.path.join(rel_dir, name) if rel_dir else name
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except OSError as exc:
            # ELOOP: a symlink. Anything else unreadable is skipped as well.
            if exc.errno != errno.ELOOP:
                logger.warning("local isolation: skip {} on copy-back: {}", rel, exc)
            continue
        try:
            st = os.fstat(fd)
            if stat.S_ISDIR(st.st_mode):
                _copy_out_dir(fd, rel, dst_root, index, exclude, file_limit, budget, written, record)
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                continue
            if index.get(rel) == (st.st_size, st.st_mtime_ns):
                continue
            if st.st_size > file_limit or st.st_size > budget[0]:
                logger.warning("local isolation: {} exceeds the copy-back limit, not harvested", rel)
                continue
            if _write_into(fd, st, dst_root, rel):
                budget[0] -= st.st_size
                written.append(rel)
                if record is not None:
                    record[rel] = (st.st_size, st.st_mtime_ns)
        finally:
            os.close(fd)


def _safe_target_dir(dst_root: str, rel_dir: str) -> str | None:
    """Create ``rel_dir`` under ``dst_root`` without following any symlink."""
    current = dst_root
    for part in [p for p in rel_dir.split(os.sep) if p]:
        current = os.path.join(current, part)
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            os.mkdir(current, 0o755)
            continue
        if not stat.S_ISDIR(st.st_mode):
            return None
    return current


def _write_into(src_fd: int, st: os.stat_result, dst_root: str, rel: str) -> bool:
    rel_dir, name = os.path.split(rel)
    target_dir = _safe_target_dir(dst_root, rel_dir)
    if target_dir is None:
        logger.warning("local isolation: {} has a non-directory on its path in the workspace, not harvested", rel)
        return False
    target = os.path.join(target_dir, name)
    try:
        existing = os.lstat(target)
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        logger.warning("local isolation: {} is not a regular file in the workspace, not harvested", rel)
        return False
    tmp = os.path.join(target_dir, f".{name}.{uuid.uuid4().hex}.tmp")
    out_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        remaining = st.st_size
        os.lseek(src_fd, 0, os.SEEK_SET)
        while remaining > 0:
            chunk = os.read(src_fd, min(_COPY_CHUNK, remaining))
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                view = view[os.write(out_fd, view) :]
            remaining -= len(chunk)
    except BaseException:
        os.close(out_fd)
        os.unlink(tmp)
        raise
    os.close(out_fd)
    os.chmod(tmp, 0o644)
    os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.replace(tmp, target)
    return True
