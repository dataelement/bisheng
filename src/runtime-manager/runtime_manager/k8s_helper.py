"""Trusted material entry points. No application source is imported or executed.

The download/install/upload Pods have separate identities and mounts. This module
runs with Python isolated mode from an installed, pinned helper image.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime_manager.bundle_inputs import (
    archive_directory,
    dependency_input_key,
    environment_key,
    extract_archive,
    safe_relative,
    startup_command,
)
from runtime_manager.material_client import MaterialClient, MaterialClientError

_RESULT = "BISHENG_RUNTIME_RESULT "
_LANGUAGES = {"python3.11", "node20", "static"}


def _directory(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("helper_directory_invalid")
    path.mkdir(parents=True, exist_ok=True)
    return path


def verify_volume(volume=Path("/volume"), *, guard):
    """Read-only admission for a mounted bounded filesystem; never creates paths."""
    from runtime_manager.k8s_capabilities import mounted_filesystem, volume_capacity

    root = Path(volume)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("volume_unavailable")
    if (
        not isinstance(guard, dict)
        or set(guard) != {"namespace", "installation_id", "filesystem", "capacity_bytes", "marker_required"}
        or type(guard["marker_required"]) is not bool
        or any(not isinstance(guard[key], str) or not guard[key] for key in ("namespace", "installation_id"))
    ):
        raise ValueError("volume_guard_invalid")
    if mounted_filesystem(root) != guard["filesystem"] or guard["filesystem"] not in {"ext4", "xfs"}:
        raise ValueError("volume_filesystem_incompatible")
    requested = guard["capacity_bytes"]
    if type(requested) is not int or requested <= 0 or not 0.8 * requested <= volume_capacity(root) <= 1.1 * requested:
        raise ValueError("volume_capacity_unbounded")
    if guard["marker_required"]:
        marker = root / ".bisheng-volume.json"
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
            raise ValueError("volume_marker_missing")
        try:
            identity = json.loads(marker.read_text())
        except (OSError, ValueError):
            raise ValueError("volume_marker_invalid") from None
        if not isinstance(identity, dict) or any(
            identity.get(key) != guard[key] for key in ("namespace", "installation_id")
        ):
            raise ValueError("volume_marker_scope_refused")
    return {"verified": True}


def initialize_data_layout(volume=Path("/volume"), *, guard=None):
    if guard is not None:
        verify_volume(volume, guard=guard)
    root = _directory(volume)
    for name in ("business", "platform", "platform/backups", "platform/journal"):
        directory = _directory(root / name)
        directory.chmod(0o700 if name.startswith("platform") else 0o770)
    return {"layout": 1}


def _manifest(client, artifact_id):
    clock = getattr(client, "clock", time.time)
    sleep = getattr(client, "sleep", time.sleep)
    deadline = min(getattr(client, "deadline", clock() + 60), clock() + 60)
    for attempt in range(120):
        try:
            return client.describe(artifact_id)
        except MaterialClientError as exc:
            remaining = deadline - clock()
            if exc.status != 409 or remaining <= 0 or attempt == 119:
                raise
            # Pod creation and the manager's observed-UID commit can race init.
            sleep(min(0.5, remaining))
    raise ValueError("helper_material_binding_unavailable")


def _fetch(
    client, artifact_id, destination, *, compressed=2048 * 1024**2, unpacked=8 * 1024**3, entries=200000, links=True
):
    if not isinstance(artifact_id, str) or not artifact_id or len(artifact_id) > 36:
        raise ValueError("helper_artifact_invalid")
    destination = _directory(destination)
    manifest = _manifest(client, artifact_id)
    with TemporaryDirectory(prefix="helper-material-") as directory:
        archive = Path(directory) / "material.tar.gz"
        client.download(
            artifact_id,
            archive,
            expected_sha256=manifest["sha256"],
            expected_size=manifest["size_bytes"],
            max_bytes=compressed,
        )
        extract_archive(archive, destination, max_bytes=unpacked, max_entries=entries, internal_links=links)
    return manifest


def environment_script(language):
    if language == "python3.11":
        return """#!/bin/sh
set -eu
umask 077
export PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
python -I -m venv --system-site-packages /opt/venv
/opt/venv/bin/python -I -m pip install --no-index --find-links=/materials/wheels --require-hashes -r /materials/runtime.lock
/opt/venv/bin/python -I -m pip check
/opt/venv/bin/python -I -c 'import bisheng_sdk'
"""
    if language in {"node20", "static"}:
        # Compiled Node bundles contain their exact node_modules; static is HTML.
        return "#!/bin/sh\nset -eu\nexit 0\n"
    raise ValueError("helper_language_invalid")


def fetch_runtime(
    client, delivery, *, code=Path("/workspace/app"), materials=Path("/materials"), tools=Path("/runtime/tools")
):
    if delivery.get("mode") != "bundle":
        raise ValueError("helper_bundle_required")
    profile = delivery.get("profile") or {}
    language = profile.get("language")
    if language not in _LANGUAGES:
        raise ValueError("helper_language_invalid")
    code, materials, tools = map(_directory, (code, materials, tools))
    _fetch(client, delivery["compiled_artifact_id"], code)
    _fetch(client, delivery["dependency_artifact_id"], materials)
    script = tools / "environment.sh"
    script.write_text(environment_script(language))
    script.chmod(0o500)
    (tools / "runtime.json").write_text(
        json.dumps({"profile": profile, "environment_key": delivery.get("environment_key", "")}, sort_keys=True)
    )
    return {"materialized": True, "language": language}


def _input_key(document, original):
    dependencies = document.get("delivery", {}).get("dependencies", {})
    profile = document["profile"]
    return dependency_input_key(
        original,
        tenant_id=document["tenant_id"],
        app_id=document["app_id"],
        profile=profile,
        language=profile["language"],
        offline_artifacts=dependencies.get("offline_artifacts", []),
        install_inputs=[
            *dependencies.get("install_inputs", []),
            *([dependencies["lock"]] if dependencies.get("lock") else []),
        ],
    )


def _source_root(root):
    if (root / "bisheng-app.yaml").is_file():
        return root
    children = list(root.iterdir())
    if (
        len(children) == 1
        and children[0].is_dir()
        and not children[0].is_symlink()
        and (children[0] / "bisheng-app.yaml").is_file()
    ):
        return children[0]
    raise ValueError("helper_source_manifest_missing")


def _load_download_tool():
    spec = importlib.util.spec_from_file_location("bisheng_download_tool", "/opt/bisheng/prepare.py")
    if spec is None or spec.loader is None:
        raise ValueError("helper_download_tool_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_download(document, source, offline, output):
    """Only wheel/metadata and ignore-scripts npm resolution runs with identity."""
    module = _load_download_tool()
    module.SOURCE, module.MATERIALS, module.OUTPUT, module.WHEELS = source, offline, output, output / "wheels"

    def run(*args, cwd=None, env=None):
        args = list(args)
        # A source/pip.py must not replace the trusted package downloader.
        if args[:2] == ["python", "-m"]:
            args.insert(1, "-I")
        subprocess.run(args, cwd=cwd or source, env=env, check=True)

    module.run = run
    lock = document.get("delivery", {}).get("dependencies", {}).get("lock", "")
    previous = os.environ.get("BISHENG_DEPENDENCY_LOCK")
    os.environ["BISHENG_DEPENDENCY_LOCK"] = lock
    try:
        module.download(document["profile"]["language"])
    finally:
        if previous is None:
            os.environ.pop("BISHENG_DEPENDENCY_LOCK", None)
        else:
            os.environ["BISHENG_DEPENDENCY_LOCK"] = previous


def prepare_download(client, document, *, work=Path("/work"), resolver=resolve_download):
    work = _directory(work)
    profile = document["profile"]
    if profile.get("language") not in _LANGUAGES or document.get("phase") not in {"inputs", "resolve"}:
        raise ValueError("helper_prepare_contract_invalid")
    original, source, materials, output, tools = [
        work / name for name in ("original", "source", "materials", "output", "tools")
    ]
    if document["phase"] == "inputs":
        if any(path.exists() for path in (original, source, materials, output, tools)):
            raise ValueError("helper_scratch_not_empty")
        for path in (original, source, materials, output, tools, work / "environment"):
            _directory(path)
        with TemporaryDirectory(prefix="helper-source-") as directory:
            root = Path(directory) / "source"
            limits = document.get("source_limits") or {}
            _fetch(
                client,
                document["source_artifact_id"],
                root,
                compressed=limits.get("compressed", 50 * 1024**2),
                unpacked=limits.get("unpacked", 200 * 1024**2),
                entries=limits.get("entries", 20000),
                links=False,
            )
            for item in _source_root(root).iterdir():
                target = original / item.name
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copyfile(item, target)
        shutil.copytree(original, source, dirs_exist_ok=True)
        shutil.copyfile(Path(__file__).with_name("k8s_prepare.py"), tools / "k8s_prepare.py")
        key = _input_key(document, original)
        (work / "inputs.json").write_text(
            json.dumps({"source_artifact_id": document["source_artifact_id"], "input_key": key}, sort_keys=True)
        )
        return {"input_key": key, "phase": "inputs"}
    for path in (original, source, materials, output, tools):
        _directory(path)
    key = _input_key(document, original)
    selected = document.get("dependency_resolution") or {}
    marker = json.loads(safe_relative(work, "inputs.json").read_text())
    if selected.get("input_key") != key or marker != {
        "source_artifact_id": document["source_artifact_id"],
        "input_key": key,
    }:
        raise ValueError("helper_dependency_selection_changed")
    cached = bool(selected.get("artifact_id"))
    if cached:
        _fetch(client, selected["artifact_id"], materials)
    else:
        offline = _directory(work / "offline")
        for reference in document.get("delivery", {}).get("dependencies", {}).get("offline_artifacts", []):
            _fetch(client, reference, offline / reference)
        resolved = work / "resolved"
        if resolved.exists():
            raise ValueError("helper_resolution_already_present")
        previous = dict(os.environ)
        try:
            environment = document.get("package_environment", {})
            if not isinstance(environment, dict) or set(environment) - {
                "PIP_INDEX_URL",
                "PIP_EXTRA_INDEX_URL",
                "npm_config_registry",
            }:
                raise ValueError("helper_package_environment_invalid")
            os.environ.update(environment)
            os.environ["PIP_NO_INDEX"] = "1" if document.get("offline") else "0"
            os.environ["npm_config_offline"] = "true" if document.get("offline") else "false"
            proxy = getattr(client, "package_proxy", None)
            if proxy:
                os.environ.update(dict.fromkeys(("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"), proxy))
                os.environ.update(NO_PROXY="", no_proxy="")
            resolver(document, source, offline, resolved)
        finally:
            os.environ.clear()
            os.environ.update(previous)
        if not resolved.is_dir() or resolved.is_symlink():
            raise ValueError("helper_resolution_missing")
        shutil.copytree(resolved, materials, dirs_exist_ok=True, symlinks=True)
    config = {
        "language": profile["language"],
        "cached": cached,
        "source_image": document.get("delivery", {}).get("mode") == "source-image",
        "lock": document.get("delivery", {}).get("dependencies", {}).get("lock", ""),
    }
    (tools / "prepare.json").write_text(json.dumps(config, sort_keys=True))
    return {"input_key": key, "cached": cached, "phase": "resolve"}


def _verified(result):
    if result.get("state") != "verified" or not result.get("confirmed_at") or not result.get("artifact_id"):
        raise ValueError("helper_material_not_confirmed")
    return result["artifact_id"]


def prepare_upload(client, document, *, work=Path("/work")):
    work = _directory(work)
    source, original, output, materials = [work / name for name in ("source", "original", "output", "materials")]
    for path in (source, original, output, materials):
        _directory(path)
    key = _input_key(document, original)
    marker = json.loads(safe_relative(work, "inputs.json").read_text())
    if marker != {"source_artifact_id": document["source_artifact_id"], "input_key": key}:
        raise ValueError("helper_dependency_inputs_changed")
    profile = document["profile"]
    for startup_file in ("Procfile", "package.json"):
        safe_relative(source, startup_file)
    selected = document.get("dependency_resolution") or {}
    dependency_id = selected.get("artifact_id")
    if dependency_id:
        if selected.get("input_key") != key:
            raise ValueError("helper_dependency_selection_changed")
        dependency_root = materials
    else:
        dependency_root = output
    lock = safe_relative(dependency_root, "runtime.lock").read_bytes()
    with TemporaryDirectory(prefix="helper-outputs-") as directory:
        directory = Path(directory)
        if not dependency_id:
            archive = archive_directory(dependency_root, directory / "dependencies.tar.gz")
            dependency_id = _verified(
                client.upload(
                    archive,
                    kind="dependencies",
                    platform=profile["platform"],
                    metadata={"input_key": key, "profile_id": profile["profile_id"]},
                )
            )
        language = profile["language"]
        if language == "static" and document.get("source_image"):
            code = next(
                (
                    source / part
                    for part in (".", "dist", "build", "public")
                    if (source / part / "index.html").is_file()
                ),
                source,
            )
        else:
            code = source / "dist" if language == "static" and (source / "dist/index.html").is_file() else source
        if code.is_symlink() or not code.resolve().is_relative_to(work.resolve()):
            raise ValueError("helper_output_path_escape")
        archive = archive_directory(
            code,
            directory / "compiled.tar.gz",
            exclude={".git", ".venv", "__pycache__"} | ({"node_modules"} if language != "node20" else set()),
        )
        compiled_id = _verified(
            client.upload(
                archive,
                kind="compiled",
                platform=profile["platform"],
                metadata={"source_artifact_id": document["source_artifact_id"]},
            )
        )
    return {
        "mode": "bundle",
        "profile": profile,
        "platform": profile["platform"],
        "source_artifact_id": document["source_artifact_id"],
        "dependency_artifact_id": dependency_id,
        "compiled_artifact_id": compiled_id,
        "startup": {
            "command": document.get("delivery", {}).get("startup", {}).get("command", [])
            if document.get("delivery", {}).get("mode") == "source-image"
            else startup_command(
                source, profile["language"], document.get("delivery", {}).get("startup", {}).get("command")
            )
        },
        "environment_key": environment_key(profile, lock, tenant_id=document["tenant_id"], app_id=document["app_id"]),
        "dependency_input_key": key,
    }


def client_from_identity(path=Path("/run/material/identity.json"), *, clock=time.time):
    path = Path(path)
    identity = json.loads(path.read_text())
    if set(identity) - {
        "base_url",
        "delegation_id",
        "key_id",
        "private_key",
        "scope_kind",
        "expires_at",
        "phase_timeout_seconds",
        "proxy_url",
    }:
        raise ValueError("helper_identity_fields_invalid")
    if identity.get("scope_kind") not in {"operation", "deployment-init"} or (
        identity["scope_kind"] == "operation" and identity.get("expires_at") is None
    ):
        raise ValueError("helper_identity_scope_invalid")
    phase = identity.get("phase_timeout_seconds", 300)
    if type(phase) is not int or not 1 <= phase <= 1800:
        raise ValueError("helper_phase_limit_invalid")
    deadline = clock() + phase
    if identity.get("expires_at") is not None:
        expiry = identity["expires_at"]
        if type(expiry) not in {int, float} or not math.isfinite(expiry):
            raise ValueError("helper_identity_expiry_invalid")
        deadline = min(deadline, expiry)
    private = identity["private_key"]
    if not isinstance(private, str) or len(private) != 64:
        raise ValueError("helper_private_key_invalid")
    ca = path.with_name("ca.crt")
    client = MaterialClient(
        identity["base_url"],
        delegation_id=identity["delegation_id"],
        key_id=identity["key_id"],
        pod_uid=os.environ["MATERIAL_POD_UID"],
        private_key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private)),
        deadline=deadline,
        ca_file=ca if ca.is_file() else None,
        proxy_url=identity.get("proxy_url"),
        clock=clock,
    )

    client.package_proxy = identity.get("proxy_url")
    return client


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "storage-guard":
        result = verify_volume(guard=json.loads(os.environ["VOLUME_GUARD"]))
    elif action == "data-layout":
        result = initialize_data_layout(
            guard=json.loads(os.environ["VOLUME_GUARD"]) if os.getenv("VOLUME_GUARD") else None
        )
    elif action in {"material-fetch", "prepare-download", "prepare-upload"}:
        document = json.loads(os.environ["MATERIAL_PLAN"])
        client = client_from_identity()
        try:
            if action == "material-fetch":
                result = fetch_runtime(client, document)
            elif action == "prepare-download":
                result = prepare_download(client, document)
            else:
                result = prepare_upload(client, document)
        finally:
            client.close()
    else:
        raise ValueError("helper_action_invalid")
    print(_RESULT + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print source, identity, proxy address, or storage response details.
        print("runtime helper failed (" + type(exc).__name__ + ")", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
