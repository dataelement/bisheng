"""Scan release sources and every Docker-save layer, without extracting files.

Run from src/backend:
    python scripts/check_image_secrets.py --source-root . --image-archive /secure/image.tar
Optional --keyring supplies known keys to match, without putting them in argv.
This is an offline artifact checker; it never loads runtime settings or connects
to services. Missing archives and unsupported formats are failures, not skips.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tarfile
from pathlib import Path

_FIXED_KEY = re.compile(rb'(?:secret_key|fernet_key)\s*=\s*["\'][A-Za-z0-9_-]{43}=["\']')
_KEY_DOCUMENT = re.compile(rb'["\']keys["\']\s*:\s*\[\s*["\'][A-Za-z0-9_-]{43}=')
_SKIP = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}


def _sensitive_name(name: str) -> bool:
    parts = Path(name).parts
    return (
        "secrets" in parts or ".generated" in parts or name.endswith("bisheng/config.yaml") or Path(name).name == ".env"
    )


def _contains_secret(stream, known_keys: tuple[bytes, ...]) -> bool:
    tail = b""
    while chunk := stream.read(1024 * 1024):
        window = tail + chunk
        if _FIXED_KEY.search(window) or _KEY_DOCUMENT.search(window):
            return True
        if any(key in window for key in known_keys):
            return True
        tail = window[-4096:]
    return False


def scan_source(root: Path, known_keys: tuple[bytes, ...] = ()) -> list[str]:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source directory required")
    findings = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in _SKIP)
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root)
            if path.is_symlink():
                if _sensitive_name(str(relative)):
                    findings.append(f"source:{relative}:runtime-input")
                continue
            if not path.is_file():
                continue
            with path.open("rb") as stream:
                if _sensitive_name(str(relative)) or _contains_secret(stream, known_keys):
                    findings.append(f"source:{relative}:secret-material")
    return findings


def scan_image(archive: Path, known_keys: tuple[bytes, ...] = ()) -> list[str]:
    findings = []
    try:
        with tarfile.open(archive, "r:*") as image:
            manifest_file = image.extractfile("manifest.json")
            if manifest_file is None:
                raise ValueError("Docker-save manifest required")
            with manifest_file:
                manifest = json.load(manifest_file)
            if not isinstance(manifest, list) or not manifest:
                raise ValueError("Docker-save manifest required")
            layers = []
            for entry in manifest:
                names = entry.get("Layers") if isinstance(entry, dict) else None
                if not isinstance(names, list) or not names or not all(isinstance(x, str) for x in names):
                    raise ValueError("image layer list required")
                layers.extend(names)
                config_name = entry.get("Config")
                if config_name is not None:
                    if not isinstance(config_name, str):
                        raise ValueError("image config name required")
                    config_member = image.getmember(config_name)
                    if not config_member.isfile():
                        raise ValueError("regular image config required")
                    with image.extractfile(config_member) as stream:
                        if _contains_secret(stream, known_keys):
                            findings.append(f"image-config:{config_name}:secret-material")
            for name in dict.fromkeys(layers):
                member = image.getmember(name)
                if not member.isfile():
                    raise ValueError("regular image layer required")
                with image.extractfile(member) as content:
                    with tarfile.open(fileobj=content, mode="r|*") as layer:
                        for entry in layer:
                            if not entry.isfile():
                                continue
                            with layer.extractfile(entry) as stream:
                                if _sensitive_name(entry.name) or _contains_secret(stream, known_keys):
                                    findings.append(f"image:{name}:{entry.name}:secret-material")
    except (OSError, KeyError, tarfile.TarError, ValueError, TypeError):
        raise ValueError("image archive cannot be verified") from None
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--image-archive", type=Path, required=True)
    parser.add_argument("--keyring", type=Path)
    args = parser.parse_args(argv)
    try:
        keys = ()
        if args.keyring:
            data = json.loads(args.keyring.read_text())
            values = data["keys"]
            if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x for x in values):
                raise ValueError("invalid known key file")
            keys = tuple(x.encode("ascii") for x in values)
        findings = scan_source(args.source_root, keys) + scan_image(args.image_archive, keys)
    except (OSError, ValueError, KeyError, TypeError):
        print("FAIL: artifact inputs cannot be verified")
        return 2
    for location in findings:
        print(f"FAIL: {location}")
    if not findings:
        print("PASS: release sources and all image layers checked")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
