"""Read community plugin archives using their npm package metadata."""

import gzip
import io
import json
import re
import stat
import tarfile
import zipfile

from .bundle import (
    MAX_EXPANDED_BYTES,
    MAX_FILES,
    MAX_UPLOAD_BYTES,
    NAME,
    TARGETS,
    BundleError,
    _require,
    host_package,
    safe_path,
)

IDENTIFIER = re.compile(r"^[0-9A-Za-z-]+$")


class LimitedReader:
    def __init__(self, source):
        self.source = source
        self.total = 0

    def read(self, size=-1):
        limit = MAX_EXPANDED_BYTES + MAX_FILES * 1024
        chunk = self.source.read(min(65536 if size < 0 else size, limit + 1 - self.total))
        self.total += len(chunk)
        _require(self.total <= limit, "Expanded archive exceeds limit")
        return chunk


def semver_parts(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise BundleError("Invalid plugin SemVer version")
    core_and_pre = value.split("+", 1)[0]
    core, separator, prerelease = core_and_pre.partition("-")
    numbers = core.split(".")
    if (
        len(numbers) != 3
        or any(not part.isdigit() or (len(part) > 1 and part.startswith("0")) for part in numbers)
        or (separator and not prerelease)
    ):
        raise BundleError("Invalid plugin SemVer version")
    identifiers = []
    if prerelease:
        for identifier in prerelease.split("."):
            if not IDENTIFIER.fullmatch(identifier) or (
                len(identifier) > 1 and identifier.isdigit() and identifier.startswith("0")
            ):
                raise BundleError("Invalid plugin SemVer version")
            identifiers.append(int(identifier) if identifier.isdigit() else identifier)
    return tuple(int(part) for part in numbers), tuple(identifiers)


def compare_semver(left, right):
    left_core, left_pre = semver_parts(left)
    right_core, right_pre = semver_parts(right)
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)
    if left_pre == right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    for left_id, right_id in zip(left_pre, right_pre, strict=False):
        if left_id == right_id:
            continue
        if isinstance(left_id, int) and isinstance(right_id, int):
            return (left_id > right_id) - (left_id < right_id)
        if isinstance(left_id, int):
            return -1
        if isinstance(right_id, int):
            return 1
        return (left_id > right_id) - (left_id < right_id)
    return (len(left_pre) > len(right_pre)) - (len(left_pre) < len(right_pre))


def read_package_files(data):
    _require(len(data) <= MAX_UPLOAD_BYTES, "Upload exceeds 512 MiB")
    files, folded = {}, set()
    expanded = 0

    def add(path, size, regular, read):
        nonlocal expanded
        path = path.rstrip("/")
        _require(safe_path(path), "Unsafe archive path")
        _require(path.casefold() not in folded, "Duplicate archive path")
        folded.add(path.casefold())
        _require(len(folded) <= MAX_FILES, "Too many entries")
        expanded += size
        _require(0 <= size and expanded <= MAX_EXPANDED_BYTES, "Expanded archive exceeds 1 GiB")
        if regular:
            if path.endswith("package.json"):
                _require(size <= 1024 * 1024, "Package metadata exceeds 1 MiB")
                files[path] = read()
            else:
                files[path] = None

    try:
        if data.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    _require(not item.flag_bits & 1, "Encrypted archives are unsupported")
                    _require(
                        stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                        "Unsupported archive entry",
                    )
                    add(item.filename, item.file_size, not item.is_dir(), lambda item=item: archive.read(item))
        else:
            with (
                gzip.GzipFile(fileobj=io.BytesIO(data)) as source,
                tarfile.open(fileobj=LimitedReader(source), mode="r|") as archive,
            ):
                for item in archive:
                    _require(item.isfile() or item.isdir(), "Only regular files and directories are supported")
                    add(item.name, item.size, item.isfile(), lambda item=item: archive.extractfile(item).read())
        return files
    except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile, ValueError, UnicodeError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError("Invalid plugin archive") from exc


def validate_community_bundle(data):
    files = read_package_files(data)
    roots = [
        path for path in files if path == "package.json" or (path.count("/") == 1 and path.endswith("/package.json"))
    ]
    _require(len(roots) == 1, "Archive must contain one plugin package.json")
    metadata_path = roots[0]
    prefix = metadata_path.removesuffix("package.json")
    _require(all(path.startswith(prefix) for path in files), "Files must belong to the plugin package")
    try:
        pkg = json.loads(files[metadata_path])
        _require(isinstance(pkg, dict), "Invalid package.json")
        name, version = pkg.get("name"), pkg.get("version")
        _require(isinstance(name, str) and bool(NAME.fullmatch(name)) and not host_package(name), "Invalid plugin name")
        _require(not name.startswith("dsh-desktop-") and name != "dshmarket", "Reserved host package")
        semver_parts(version)
        dsh = pkg.get("dsh", {})
        _require(isinstance(dsh, dict), "Invalid dsh metadata")
        declaration = dsh.get("bundle")
        entry = pkg.get("exports")
        if isinstance(entry, dict) and "." in entry:
            entry = entry["."]
        while isinstance(entry, dict):
            entry = next((entry[key] for key in ("import", "node", "default", "require") if key in entry), None)
        entry = entry if isinstance(entry, str) else pkg.get("main") or "index.js"
        if isinstance(declaration, dict):
            entry = declaration.get("patch")
        entries = entry if isinstance(entry, list) else [entry]
        _require(bool(entries), "Missing plugin entry")
        for value in entries:
            relative = value.removeprefix("./") if isinstance(value, str) else ""
            _require(safe_path(relative) and prefix + relative in files, "Plugin entry is missing or unsafe")
        targets = {}
        for target in sorted(TARGETS):
            platform, architecture = target.split("-")
            compatible = True
            for key, actual in (("os", platform), ("cpu", architecture)):
                values = pkg.get(key, [])
                _require(isinstance(values, list) and all(isinstance(value, str) for value in values), f"Invalid {key}")
                positive = [value for value in values if not value.startswith("!")]
                compatible &= (not positive or actual in positive or "any" in positive) and f"!{actual}" not in values
            if compatible:
                targets[target] = {}
        _require(bool(targets), "Plugin has no supported platform")
        author = pkg.get("author", "")
        publisher = author.get("name", "") if isinstance(author, dict) else author
        plugin = {
            "name": name,
            "version": version,
            "display_name": pkg.get("displayName", name),
            "description": pkg.get("description", ""),
            "publisher": publisher if isinstance(publisher, str) else "",
            "license": pkg.get("license", ""),
            "desktop_min": "",
            "permissions": [],
            "services": [],
            "changelog": "",
        }
        for key, limit in (("display_name", 128), ("description", 2000), ("publisher", 128), ("license", 128)):
            _require(isinstance(plugin[key], str) and len(plugin[key]) <= limit, f"Invalid {key}")
        return {"schema_version": 2, "format": "npm", "plugin": plugin, "targets": targets}
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError("Invalid plugin package metadata") from exc
