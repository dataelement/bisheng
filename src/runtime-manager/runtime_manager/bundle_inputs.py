"""Untrusted bundle boundaries, immutable input keys and reproducible artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
import tomllib
from pathlib import Path, PurePosixPath

from runtime_manager.platform_protocol import content_digest


class BundleInputError(ValueError):
    pass


def safe_relative(root: Path, name: str) -> Path:
    if (
        not name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or any(x in {"", ".", ".."} for x in name.split("/"))
    ):
        raise BundleInputError("invalid_package_path")
    root = Path(root).resolve()
    try:
        path = (root / name).resolve()
    except (OSError, RuntimeError) as exc:
        raise BundleInputError("archive_link_cycle") from exc
    if not path.is_relative_to(root):
        raise BundleInputError("archive_path_escape")
    return path


def extract_archive(
    archive: Path, destination: Path, *, max_bytes=200 * 1024 * 1024, max_entries=20000, internal_links=False
):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    seen = set()
    size = 0
    count = 0
    with tarfile.open(archive, "r|*") as stream:
        for member in stream:
            count += 1
            if count > max_entries:
                raise BundleInputError("archive_entry_limit")
            name = member.name.rstrip("/")
            target = safe_relative(destination, name)
            if name in seen and not member.isdir():
                raise BundleInputError("archive_duplicate_path")
            seen.add(name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                if not internal_links:
                    raise BundleInputError("archive_link_refused")
                if "\\" in member.linkname or PurePosixPath(member.linkname).is_absolute():
                    raise BundleInputError("archive_link_escape")
                linked = (target.parent / member.linkname).resolve()
                if not linked.is_relative_to(destination.resolve()):
                    raise BundleInputError("archive_link_escape")
                target.symlink_to(member.linkname)
                continue
            if not member.isfile():
                raise BundleInputError("archive_special_file_refused")
            size += member.size
            if member.size < 0 or size > max_bytes:
                raise BundleInputError("archive_size_limit")
            source = stream.extractfile(member)
            if source is None:
                raise BundleInputError("archive_content_missing")
            actual = 0
            with target.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    actual += len(chunk)
                    output.write(chunk)
            if actual != member.size:
                raise BundleInputError("archive_content_truncated")
            target.chmod(member.mode & 0o777)
    return destination


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise BundleInputError("source_symlink_refused")
        if not path.is_file():
            continue
        digest.update(relative.encode() + b"\0")
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def dependency_input_key(
    source: Path, *, tenant_id, app_id, profile, language, offline_artifacts=(), install_inputs=()
):
    files = [
        "requirements.txt",
        "runtime.lock",
        "pyproject.toml",
        "uv.lock",
        "poetry.lock",
        "setup.py",
        "setup.cfg",
        "package.json",
        "package-lock.json",
        "frontend/package.json",
        "frontend/package-lock.json",
        *install_inputs,
    ]
    inputs = {}
    for name in files:
        path = safe_relative(source, name)
        if path.is_file():
            inputs[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    sensitive = False
    pyproject = source / "pyproject.toml"
    if language == "python3.11" and pyproject.exists():
        document = tomllib.loads(pyproject.read_text())
        sensitive = "project" in document or "build-system" in document
    requirements = source / "requirements.txt"
    if requirements.exists():
        sensitive = sensitive or any(
            x.strip().startswith(("-e", "file:", ".", "/", "-r", "-c", "--requirement", "--constraint"))
            for x in requirements.read_text().splitlines()
            if x.strip() and not x.lstrip().startswith("#")
        )
    for directory in [source, source / "frontend"]:
        package = directory / "package.json"
        lock = directory / "package-lock.json"
        if package.exists():
            document = json.loads(package.read_text())
            scripts = document.get("scripts", {})
            sensitive = (
                sensitive
                or bool(document.get("workspaces"))
                or any(x in scripts for x in ["preinstall", "install", "postinstall", "prepare"])
            )
            if lock.exists():
                entries = json.loads(lock.read_text()).get("packages", {})
                sensitive = sensitive or any(entry.get("hasInstallScript") for entry in entries.values())
            else:
                sensitive = True
    return content_digest(
        {
            "format": 1,
            "scope": [int(tenant_id), app_id],
            "profile": profile,
            "language": language,
            "inputs": inputs,
            "source": tree_digest(source) if sensitive else None,
            "offline_artifacts": sorted(offline_artifacts),
        }
    )


def environment_key(profile, lock: bytes, *, tenant_id, app_id):
    return content_digest(
        {"format": 1, "scope": [int(tenant_id), app_id], "profile": profile, "lock": hashlib.sha256(lock).hexdigest()}
    )


def startup_command(root: Path, language, declared=None):
    if declared:
        if not isinstance(declared, list) or not all(isinstance(x, str) and x and "\x00" not in x for x in declared):
            raise BundleInputError("startup_command_invalid")
        return declared
    proc = Path(root) / "Procfile"
    if proc.exists():
        commands = [line.split(":", 1)[1].strip() for line in proc.read_text().splitlines() if line.startswith("web:")]
        if len(commands) != 1 or not commands[0]:
            raise BundleInputError("procfile_web_ambiguous")
        return ["/bin/sh", "-c", commands[0]]
    if language == "static":
        return ["nginx", "-g", "daemon off;"]
    if language == "node20":
        package = Path(root) / "package.json"
        if package.exists() and json.loads(package.read_text()).get("scripts", {}).get("start"):
            return ["npm", "start"]
        if (Path(root) / "server.js").is_file():
            return ["node", "server.js"]
    raise BundleInputError("startup_command_required")


def archive_directory(root: Path, path: Path, *, exclude=()):
    root = Path(root).resolve()
    path = Path(path)
    with (
        path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for source in sorted(root.rglob("*")):
            relative = source.relative_to(root)
            if any(part in exclude for part in relative.parts):
                continue
            if source.is_symlink() and not source.resolve().is_relative_to(root):
                raise BundleInputError("archive_link_escape")
            info = archive.gettarinfo(str(source), arcname=relative.as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode &= 0o777
            info.pax_headers = {}
            if source.is_file() and not source.is_symlink():
                if info.islnk():
                    info.type = tarfile.REGTYPE
                    info.linkname = ""
                    info.size = source.stat().st_size
                with source.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)
    return path
