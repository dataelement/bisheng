"""Version 1 offline bundle contract. Validation never executes plugin code."""

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_FILES = 50000
TARGETS = {f"{os}-{arch}" for os in ("darwin", "linux", "win32") for arch in ("arm64", "x64")}
NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
HASH = re.compile(r"^[a-f0-9]{64}$")
HOST_PACKAGES = {"react", "react-dom"}


class BundleError(ValueError):
    pass


def safe_path(path: str) -> bool:
    parts = path.split("/")
    return (
        bool(path)
        and not any(p in ("", ".", "..") for p in parts)
        and not any(c in path for c in ("\\", ":", "\x00"))
        and all(
            not p.endswith((".", " ")) and not re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
            for p in parts
        )
    )


def host_package(name: str) -> bool:
    return name in HOST_PACKAGES or name.startswith("@deepseek-ai/")


def _require(condition: bool, message: str):
    if not condition:
        raise BundleError(message)


def _text(obj: dict, key: str, limit: int, required: bool = True):
    value = obj.get(key, "")
    _require(isinstance(value, str) and len(value) <= limit and (bool(value.strip()) or not required), key)


def _validate_dependencies(files: dict[str, bytes], root: str):
    packages = {}
    for path, data in files.items():
        if path.startswith(root) and path.endswith("/package.json"):
            try:
                pkg = json.loads(data)
            except (ValueError, UnicodeError) as exc:
                raise BundleError("Invalid package.json") from exc
            if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
                packages[str(PurePosixPath(path).parent)] = pkg
    for directory, pkg in packages.items():
        for name in {**pkg.get("dependencies", {}), **pkg.get("peerDependencies", {})}:
            _require(bool(NAME.fullmatch(name)), "Invalid dependency name")
            if (
                host_package(name)
                or name in pkg.get("optionalDependencies", {})
                or (pkg.get("peerDependenciesMeta", {}).get(name, {}).get("optional") is True)
            ):
                continue
            cursor = PurePosixPath(directory)
            found = False
            while str(cursor).startswith(root.rstrip("/")):
                if str(cursor / "node_modules" / name) in packages:
                    found = True
                    break
                cursor = cursor.parent
            _require(found, f"Missing bundled dependency: {name}")


def validate_bundle(data: bytes) -> dict:
    _require(len(data) <= MAX_UPLOAD_BYTES, "Upload exceeds 256 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        with archive:
            infos = archive.infolist()
            _require(len(infos) <= MAX_FILES, "Too many entries")
            _require(sum(i.file_size for i in infos) <= MAX_EXPANDED_BYTES, "Expanded bundle exceeds 1 GiB")
            files = {}
            folded = set()
            for info in infos:
                path = info.filename.rstrip("/") if info.is_dir() else info.filename
                _require(safe_path(path), "Unsafe archive path")
                _require(not info.flag_bits & 1, "Encrypted archives are unsupported")
                kind = stat.S_IFMT(info.external_attr >> 16)
                _require(kind in (0, stat.S_IFREG, stat.S_IFDIR), "Only regular files and directories are supported")
                _require(path.casefold() not in folded, "Duplicate archive path")
                folded.add(path.casefold())
                if not info.is_dir():
                    files[path] = archive.read(info)
        _require("manifest.json" in files and len(files["manifest.json"]) <= 8 * 1024 * 1024, "Missing manifest")
        manifest = json.loads(files["manifest.json"])
        _require(isinstance(manifest, dict) and manifest.get("schema_version") == 1, "Unsupported bundle contract")
        plugin = manifest["plugin"]
        _require(isinstance(plugin, dict), "Invalid plugin metadata")
        _require(bool(NAME.fullmatch(plugin["name"])) and not host_package(plugin["name"]), "Invalid plugin name")
        _require(
            not plugin["name"].startswith("dsh-desktop-") and plugin["name"] != "dshmarket", "Reserved host package"
        )
        _require(bool(VERSION.fullmatch(plugin["version"])), "Version must use major.minor.patch")
        for key, limit in (("display_name", 128), ("description", 2000), ("publisher", 128), ("license", 128)):
            _text(plugin, key, limit)
        _text(plugin, "changelog", 8000, False)
        _require(bool(VERSION.fullmatch(plugin["desktop_min"])), "Invalid desktop_min")
        _require(
            isinstance(plugin["permissions"], list)
            and all(isinstance(v, str) and len(v) <= 128 for v in plugin["permissions"]),
            "Invalid permissions",
        )
        _require(
            isinstance(plugin["services"], list)
            and all(isinstance(v, str) and v.startswith("https://") and len(v) <= 512 for v in plugin["services"]),
            "Services must use HTTPS",
        )
        targets = manifest["targets"]
        _require(isinstance(targets, dict) and 0 < len(targets) <= len(TARGETS), "Missing platform bundle")
        expected = {"manifest.json"}
        for target, inventory in targets.items():
            _require(target in TARGETS and isinstance(inventory, dict) and bool(inventory), "Invalid target")
            root = f"bundles/{target}/"
            for relative, digest in inventory.items():
                _require(safe_path(relative) and relative.startswith("node_modules/"), "Invalid bundle file")
                path = root + relative
                _require(isinstance(digest, str) and bool(HASH.fullmatch(digest)), "Invalid digest")
                _require(path in files and hashlib.sha256(files[path]).hexdigest() == digest, "File digest mismatch")
                expected.add(path)
            pkg_path = root + "node_modules/" + plugin["name"] + "/package.json"
            pkg = json.loads(files[pkg_path])
            _require(
                pkg.get("name") == plugin["name"] and pkg.get("version") == plugin["version"],
                "Package identity mismatch",
            )
            _validate_dependencies(files, root)
        _require(set(files) == expected, "Unlisted bundle files")
        return manifest
    except (zipfile.BadZipFile, KeyError, TypeError, ValueError, UnicodeError, NotImplementedError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError("Invalid offline plugin bundle") from exc
