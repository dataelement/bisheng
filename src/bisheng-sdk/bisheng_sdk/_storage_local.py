"""本地目录后端 —— `bisheng dev` 期的附件空间（design D8）。

同一套 API、同一个 `AttachmentMeta`，只是真身落在项目本地的附件目录里而不是平台
存储。**真实落盘位置对应用逻辑不可见**：元信息与错误文案里只有应用内路径。

写入是 `tempfile` + `os.replace` 的原子落地：中途异常不会留下半个文件，另一个
进程也读不到写了一半的附件。
"""

from __future__ import annotations

import mimetypes
import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from bisheng_sdk._attachment import AttachmentMeta
from bisheng_sdk.errors import AttachmentNotFoundError, AttachmentTooLargeError, InvalidAttachmentPathError

_CHUNK = 1024 * 1024


class LocalDirBackend:
    """把 `<root>/<应用内路径>` 当作附件空间。"""

    def __init__(self, root: str | os.PathLike[str], max_bytes: int | None = None) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes

    # -- helpers ---------------------------------------------------------

    def _resolved(self, path: str) -> Path:
        target = self.root / path
        # 防御性二次守卫：路径规则已经拒了 `..` 与绝对路径，符号链接仍可能把
        # 解析结果带出根目录。
        root = self.root.resolve()
        try:
            resolved = target.resolve()
        except OSError:  # pragma: no cover - defensive
            return target
        if root not in resolved.parents and resolved != root:
            raise _escapes(path)
        return target

    def _meta(self, path: str, target: Path) -> AttachmentMeta:
        stat = target.stat()
        guessed, _ = mimetypes.guess_type(path)
        return AttachmentMeta(
            path=path,
            size=stat.st_size,
            content_type=guessed,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    def _check_size(self, path: str, size: int) -> None:
        if self.max_bytes is not None and size > self.max_bytes:
            raise AttachmentTooLargeError(path=path, limit_bytes=self.max_bytes)

    # -- operations ------------------------------------------------------

    def put(self, path: str, data: Any, content_type: str | None = None) -> AttachmentMeta:
        target = self._resolved(path)
        known = known_length(data)
        if known is not None:
            # 长度已知就在建临时文件之前拒——零落盘。
            self._check_size(path, known)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".bstmp")
        written = 0
        try:
            for chunk in _iter_chunks(data):
                written += len(chunk)
                self._check_size(path, written)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(handle.name, target)
        except BaseException:
            handle.close()
            # 半个文件不留：失败的 put 必须让附件空间回到调用前的样子。
            try:
                os.unlink(handle.name)
            except OSError:  # pragma: no cover - 已被 replace 走或已删
                pass
            raise
        return self._meta(path, target)

    def get(self, path: str) -> bytes:
        target = self._resolved(path)
        if not target.is_file():
            raise AttachmentNotFoundError(path=path)
        return target.read_bytes()

    def open(self, path: str) -> IO[bytes]:
        target = self._resolved(path)
        if not target.is_file():
            raise AttachmentNotFoundError(path=path)
        return target.open("rb")

    def stat(self, path: str) -> AttachmentMeta:
        target = self._resolved(path)
        if not target.is_file():
            raise AttachmentNotFoundError(path=path)
        return self._meta(path, target)

    def list(self, prefix: str = "", limit: int | None = None) -> list[AttachmentMeta]:
        if not self.root.is_dir():
            return []
        rows: list[AttachmentMeta] = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for name in filenames:
                if name.endswith(".bstmp"):
                    continue
                absolute = Path(dirpath) / name
                relative = absolute.relative_to(self.root).as_posix()
                if prefix and not relative.startswith(prefix):
                    continue
                rows.append(self._meta(relative, absolute))
        rows.sort(key=lambda meta: meta.path)
        if limit is not None:
            return rows[:limit]
        return rows

    def delete(self, path: str) -> None:
        target = self._resolved(path)
        if not target.is_file():
            # 删一个不存在的附件不是静默成功（AC-25）。
            raise AttachmentNotFoundError(path=path)
        target.unlink()


def _escapes(path: str) -> InvalidAttachmentPathError:
    return InvalidAttachmentPathError(path=path, reason="解析后超出附件空间")


def known_length(data: Any) -> int | None:
    """发送前能确定的长度，确定不了就 ``None``（边写边计数）。"""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return len(data)
    if isinstance(data, str):
        return len(data.encode("utf-8"))
    if isinstance(data, os.PathLike):
        try:
            return os.path.getsize(data)
        except OSError:  # pragma: no cover - 交给随后的 open 去报真正的错
            return None
    try:
        current = data.tell()
        end = data.seek(0, os.SEEK_END)
        data.seek(current, os.SEEK_SET)
    except (AttributeError, OSError, ValueError):
        return None
    return max(int(end) - int(current), 0)


def _iter_chunks(data: Any) -> Iterator[bytes]:
    """bytes / 文件对象 / 本地文件路径三种入参都走同一条流式写入。"""
    if isinstance(data, (bytes, bytearray, memoryview)):
        yield bytes(data)
        return
    if isinstance(data, str):
        # 字符串是"写这段文本"而不是"读这个路径"——路径要用 `pathlib.Path`，
        # 否则一个恰好存在的同名文件会让语义在两台机器上不一样。
        yield data.encode("utf-8")
        return
    if isinstance(data, os.PathLike):
        with open(data, "rb") as source:
            while True:
                chunk = source.read(_CHUNK)
                if not chunk:
                    return
                yield chunk
    read = getattr(data, "read", None)
    if read is None:
        raise TypeError(f"unsupported attachment payload: {type(data).__name__}")
    while True:
        chunk = read(_CHUNK)
        if not chunk:
            return
        yield chunk if isinstance(chunk, bytes) else bytes(chunk)
