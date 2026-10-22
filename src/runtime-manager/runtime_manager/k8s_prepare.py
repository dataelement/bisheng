"""Standalone untrusted install/build entry, copied to a readonly tools mount.

This file deliberately imports no manager package, network client or identity.
It runs in the profile preparer image with only the scoped scratch subdirectories.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath


def _safe(root, name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or PurePosixPath(name).is_absolute()
        or any(x in {"", ".", ".."} for x in name.split("/"))
    ):
        raise ValueError("prepare_relative_path_invalid")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("prepare_path_escape")
    return target


def _common():
    spec = importlib.util.spec_from_file_location("bisheng_image_preparer", "/opt/bisheng/prepare.py")
    if spec is None or spec.loader is None:
        raise ValueError("prepare_image_tool_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _overlay(source, materials):
    root = materials / "install-overlay"
    if root.exists():
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("prepare_overlay_link_refused")
            target = _safe(source, relative)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            else:
                raise ValueError("prepare_overlay_type_refused")
    deleted = materials / "install-deleted.json"
    if deleted.exists():
        if deleted.is_symlink():
            raise ValueError("prepare_delete_manifest_link_refused")
        values = json.loads(deleted.read_text())
        if not isinstance(values, list) or len(values) > 20000:
            raise ValueError("prepare_delete_manifest_invalid")
        for name in values:
            _safe(source, name).unlink(missing_ok=True)


def prepare(
    config,
    *,
    source=Path("/workspace/app"),
    original=Path("/original"),
    materials=Path("/materials"),
    output=Path("/output"),
    common=None,
):
    language = config.get("language")
    if language not in {"python3.11", "node20", "static"} or type(config.get("cached")) is not bool:
        raise ValueError("prepare_contract_invalid")
    lock = config.get("lock")
    if lock is None:
        lock = ""
    elif not isinstance(lock, str):
        raise ValueError("prepare_dependency_lock_invalid")
    source, original, materials, output = map(Path, (source, original, materials, output))
    module = common or _common()
    module.SOURCE, module.OUTPUT, module.MATERIALS, module.WHEELS = source, output, materials, output / "wheels"
    previous_environment = dict(os.environ)
    try:
        os.environ.update(
            {
                "PIP_NO_INDEX": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_CACHE_DIR": "1",
                "npm_config_offline": "true",
                "BISHENG_DEPENDENCY_LOCK": lock,
            }
        )
        if config["cached"]:
            _overlay(source, materials)
            # Cached install outputs are immutable; only application build runs again.
            module.MATERIALS = materials
        else:
            module.lock(language)
            module.MATERIALS = output
        module.build(language)
        if config.get("source_image") and language == "python3.11":
            subprocess.run(["python", "-I", "-m", "venv", "--system-site-packages", "/opt/venv"], check=True)
            subprocess.run(
                [
                    "/opt/venv/bin/python",
                    "-I",
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links=" + str(module.MATERIALS / "wheels"),
                    "--require-hashes",
                    "-r",
                    str(module.MATERIALS / "runtime.lock"),
                ],
                check=True,
            )
            subprocess.run(["/opt/venv/bin/python", "-I", "-m", "pip", "check"], check=True)
            subprocess.run(["/opt/venv/bin/python", "-I", "-c", "import bisheng_sdk"], check=True)
        if config.get("source_image") and language == "node20":
            subprocess.run(
                ["npm", "prune", "--omit=dev", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"],
                cwd=source,
                check=True,
            )
    finally:
        os.environ.clear()
        os.environ.update(previous_environment)


def main():
    config = json.loads(Path("/runtime/tools/prepare.json").read_text())
    prepare(config)


if __name__ == "__main__":
    main()
