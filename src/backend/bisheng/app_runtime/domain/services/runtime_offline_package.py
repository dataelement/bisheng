"""Validate bounded offline material manifests without running package code."""

import hashlib
import json
import tarfile
from pathlib import PurePosixPath

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict


def validate_offline_package(path, profile, *, limit=8 * 1024 * 1024 * 1024):
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > 200000:
            raise RuntimeConflict("offline_entry_limit")
        files = {}
        total = 0
        for item in members:
            name = item.name.removeprefix("./")
            parts = PurePosixPath(name)
            if (
                name in files
                or parts.is_absolute()
                or ".." in parts.parts
                or "\\" in name
                or (not item.isfile() and not item.isdir())
            ):
                raise RuntimeConflict("offline_path_invalid")
            if any(part in {".npmrc", ".netrc", ".pypirc", "pip.conf", "config.yaml"} for part in parts.parts):
                raise RuntimeConflict("offline_credential_file_refused")
            if item.isdir():
                continue
            total += item.size
            if total > limit:
                raise RuntimeConflict("offline_size_limit")
            stream = archive.extractfile(item)
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            files[name] = {"size": item.size, "sha256": digest.hexdigest()}
        entry = next((m for m in members if m.name.removeprefix("./") == "offline.json"), None)
        if entry is None or entry.size > 1024 * 1024:
            raise RuntimeConflict("offline_manifest_required")
        manifest = json.load(archive.extractfile(entry))
        if manifest.get("schema_version") != 1 or any(
            manifest.get(key) != profile.get(key) for key in ("profile_id", "profile_digest", "platform", "abi")
        ):
            raise RuntimeConflict("offline_profile_incompatible")
        declared = manifest.get("files", {})
        if declared != {name: value for name, value in files.items() if name != "offline.json"}:
            raise RuntimeConflict("offline_content_mismatch")
        return manifest
