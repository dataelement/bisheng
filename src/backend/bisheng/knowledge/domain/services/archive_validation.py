"""Bounded ZIP expansion. Archive names never become filesystem paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import threading
import time
import unicodedata
from uuid import uuid4
import zipfile


DOCUMENT_EXTENSIONS = frozenset({"pdf", "txt", "md", "html", "htm", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "wps", "dps", "et", "ofd"})
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "bmp"})
ARCHIVE_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
MAX_ARCHIVE_FILES = 20
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 10
MAX_ARCHIVE_ENTRIES = 200
MAX_ARCHIVE_RATIO = 200


class ArchiveValidationError(ValueError):
    """An archive must be rejected atomically; detail contains no server paths."""


@dataclass(frozen=True)
class ExpandedFile:
    file_id: str
    relative_path: str
    local_path: Path
    size: int


def check_central_directory(stream, max_entries=MAX_ARCHIVE_ENTRIES, max_bytes=512 * 1024) -> None:
    """Bound the directory before ZipFile allocates a ZipInfo per entry."""
    stream.seek(0, 2)
    length = stream.tell()
    stream.seek(max(0, length - 65557))
    tail = stream.read(65557)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or len(tail) - pos < 22:
        raise ArchiveValidationError("Missing ZIP directory")
    _, disk, start_disk, on_disk, count, size, offset, comment = struct.unpack_from("<4s4H2LH", tail, pos)
    if disk or start_disk or on_disk != count or count == 65535 or size > max_bytes or count > max_entries:
        raise ArchiveValidationError("ZIP64, split ZIP or excessive directory is not supported")
    if pos + 22 + comment != len(tail) or offset + size > length - len(tail) + pos:
        raise ArchiveValidationError("Invalid ZIP directory bounds")
    stream.seek(offset)
    end, actual = offset + size, 0
    while stream.tell() < end:
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise ArchiveValidationError("Invalid ZIP directory entry")
        name_len, extra_len, comment_len = struct.unpack_from("<3H", header, 28)
        actual += 1
        if actual > max_entries or name_len > 2048:
            raise ArchiveValidationError("Too many entries or excessive ZIP name")
        stream.seek(name_len + extra_len + comment_len, 1)
    if stream.tell() != end or actual != count:
        raise ArchiveValidationError("ZIP directory count mismatch")
    stream.seek(0)


def normalized_path(raw: str) -> str:
    raw = unicodedata.normalize("NFC", raw.replace("\\", "/"))
    parts = raw.rstrip("/").split("/")
    if raw.startswith("/") or any(
        not p or p in {".", ".."} or ":" in p or p != p.rstrip(" .")
        or any(ord(c) < 32 or ord(c) == 127 for c in p)
        or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
        for p in parts
    ):
        raise ArchiveValidationError("Unsafe ZIP entry path")
    if len(parts) - 1 > MAX_ARCHIVE_DEPTH or len(raw) > 512 or any(len(p.encode("utf-8")) > 200 for p in parts):
        raise ArchiveValidationError("ZIP path is too long or too deep")
    return "/".join(parts)


def validate_signature(path: Path, extension: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(4096)
    if not header:
        raise ArchiveValidationError("Empty child file")
    signatures = {"pdf": b"%PDF-", "png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "bmp": b"BM"}
    if extension in signatures and not header.startswith(signatures[extension]):
        raise ArchiveValidationError("File content does not match its extension")
    if extension in {"doc", "xls", "ppt", "wps", "dps", "et"} and not header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise ArchiveValidationError("Invalid legacy Office document")
    if extension in {"docx", "xlsx", "pptx", "ofd"}:
        required = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml", "ofd": "OFD.xml"}[extension]
        with path.open("rb") as document:
            check_central_directory(document, max_entries=10000, max_bytes=2 * 1024 * 1024)
        with zipfile.ZipFile(path) as office:
            if required not in office.namelist():
                raise ArchiveValidationError("Invalid document container")
            # Keep nested document parsers bounded too; do not read XML here.
            infos = office.infolist()
            if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
                raise ArchiveValidationError("Document container expands beyond the limit")
            if any(i.flag_bits & 1 or i.file_size / max(i.compress_size, 1) > MAX_ARCHIVE_RATIO for i in infos):
                raise ArchiveValidationError("Encrypted or excessive document container")
    if extension in {"txt", "md", "html", "htm", "csv"}:
        if header.startswith((b"PK", b"MZ", b"\x7fELF")) or b"\x00" in header:
            raise ArchiveValidationError("Binary payload presented as text")


def expand_archive(stream, directory: Path, allowed: set[str], max_file_bytes: int, stop: threading.Event) -> tuple[list[ExpandedFile], list[str]]:
    """Preflight all entries, then stream each to a generated local filename."""
    started = time.monotonic()

    def check_deadline():
        if stop.is_set() or time.monotonic() - started > 15:
            raise ArchiveValidationError("ZIP processing timed out or was cancelled")

    stream.seek(0)
    try:
        check_central_directory(stream)
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ArchiveValidationError("Too many ZIP entries")
            files, ignored, names, directories = [], [], set(), set()
            total = 0
            for info in infos:
                check_deadline()
                if info.orig_filename != info.filename:
                    raise ArchiveValidationError("Invalid ZIP filename")
                name = normalized_path(info.filename)
                if not info.flag_bits & 0x800 and any(ord(c) > 127 for c in info.filename):
                    raise ArchiveValidationError("Use UTF-8 ZIP filenames for non-ASCII names")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or info.flag_bits & 1:
                    raise ArchiveValidationError("Links, special files and encrypted ZIPs are not supported")
                if kind and (kind == stat.S_IFDIR) != info.is_dir():
                    raise ArchiveValidationError("ZIP directory metadata conflicts with its filename")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ArchiveValidationError("Unsupported ZIP compression method")
                folded = name.casefold()
                parents = {str(p).casefold() for p in PurePosixPath(name).parents if str(p) != "."}
                if info.is_dir():
                    if folded in names:
                        raise ArchiveValidationError("File/directory name collision")
                    directories.add(folded)
                    directories.update(parents)
                    continue
                if "__MACOSX" in name.split("/") or PurePosixPath(name).name == ".DS_Store":
                    ignored.append(name)
                    continue
                if folded in names or folded in directories or parents & names:
                    raise ArchiveValidationError("Duplicate or conflicting ZIP paths")
                names.add(folded)
                directories.update(parents)
                extension = PurePosixPath(name).suffix.lower().lstrip(".")
                if extension not in allowed or extension not in ARCHIVE_EXTENSIONS:
                    raise ArchiveValidationError(f"Unsupported file in ZIP: {name}")
                total += info.file_size
                if len(files) >= MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES or info.file_size > max_file_bytes:
                    raise ArchiveValidationError("ZIP file count or expanded size exceeds the limit")
                if info.file_size / max(info.compress_size, 1) > MAX_ARCHIVE_RATIO:
                    raise ArchiveValidationError("ZIP compression ratio exceeds the limit")
                files.append((info, name, extension))
            if not files:
                raise ArchiveValidationError("ZIP contains no supported files")
            expanded, actual_total = [], 0
            for info, name, extension in files:
                check_deadline()
                file_id = uuid4().hex
                local = directory / f"{file_id}.{extension}"
                actual = 0
                with archive.open(info) as src, local.open("xb") as dst:
                    while chunk := src.read(65536):
                        check_deadline()
                        actual += len(chunk)
                        actual_total += len(chunk)
                        if actual > max_file_bytes or actual_total > MAX_ARCHIVE_BYTES:
                            raise ArchiveValidationError("Actual expanded size exceeds the limit")
                        dst.write(chunk)
                if actual != info.file_size:
                    raise ArchiveValidationError("ZIP entry length mismatch")
                validate_signature(local, extension)
                expanded.append(ExpandedFile(file_id, name, local, actual))
            return expanded, ignored
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError) as exc:
        raise ArchiveValidationError("Invalid, corrupt or unsupported ZIP") from exc
