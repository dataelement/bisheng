"""Read-only static site selection before/after an actual build."""

import json
from pathlib import Path

from runtime_manager.bundle_inputs import BundleInputError

STATIC_ROOT_CANDIDATES = (".", "dist", "build", "public")


def _regular_path(root, relative):
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise BundleInputError("static_path_escape")
    return target


def select_static_root(root, *, built):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise BundleInputError("static_path_escape")
    candidates = (*STATIC_ROOT_CANDIDATES[1:], ".") if built else STATIC_ROOT_CANDIDATES
    for name in candidates:
        directory = _regular_path(root, name)
        index = _regular_path(root, name + "/index.html")
        if index.is_file():
            return directory
    raise BundleInputError("static_entry_missing")


def has_static_build(root):
    """Match prepare.py's root/frontend node_projects before install overlays."""
    root = Path(root)
    built = False
    for name in ("package.json", "frontend/package.json"):
        path = _regular_path(root, name)
        if not path.is_file():
            continue
        try:
            package = json.loads(path.read_text())
        except (ValueError, UnicodeError) as exc:
            raise BundleInputError("package_json_invalid") from exc
        if not isinstance(package, dict) or not isinstance(package.get("scripts", {}), dict):
            raise BundleInputError("package_json_invalid")
        built |= bool(package.get("scripts", {}).get("build"))
    return built
