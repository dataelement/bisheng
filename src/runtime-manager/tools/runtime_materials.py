#!/usr/bin/env python3
"""Offline packaging and human-authenticated catalog imports; no platform master key."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def catalog(inventories, output, revision):
    inputs = [json.loads(Path(path).read_text()) for path in inventories]
    if {x["platform"] for x in inputs} != {"linux/amd64", "linux/arm64"}:
        raise ValueError("both native platform inventories required")
    profiles = []
    for code, language, runtime, preparer, abi, toolchain in [
        (
            "python311-standard",
            "python3.11",
            "app-python",
            "app-python-preparer",
            "cp311",
            {"python": "3.11", "pip": "base-image"},
        ),
        ("node20-standard", "node20", "app-node", "app-node-preparer", "node-v115", {"node": "20", "npm": "10.8.2"}),
        ("static-standard", "static", "app-static", "app-node-preparer", "static", {"node": "20", "npm": "10.8.2"}),
    ]:
        platforms = {}
        for doc in inputs:
            run = doc["images"][runtime]
            prepare = doc["images"][preparer]
            platforms[doc["platform"]] = {
                "runtime_image": run["image"],
                "runtime_digest": run["image"].split("@")[1],
                "runtime_image_id": run["image_id"],
                "preparer_image": prepare["image"],
                "preparer_digest": prepare["image"].split("@")[1],
                "preparer_image_id": prepare["image_id"],
                "abi": abi,
                "toolchain": toolchain,
                "uid": 10001,
                "gid": 10001,
            }
        profiles.append(
            {
                "code": code,
                "revision": revision,
                "language": language,
                "contract_version": 1,
                "official": True,
                "platforms": platforms,
            }
        )
    Path(output).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": profiles,
                "defaults": {x["language"]: f"{x['code']}@{revision}" for x in profiles},
            },
            indent=2,
        )
        + "\n"
    )


def verify(path, profile):
    # The same fixed profile/ABI and per-file integrity contract is enforced again on backend import.
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
        files = {}
        total = 0
        if len(members) > 200000:
            raise ValueError("entry limit")
        for item in members:
            relative = Path(item.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or item.issym()
                or item.islnk()
                or not (item.isfile() or item.isdir())
            ):
                raise ValueError("unsafe archive")
            if item.isdir():
                continue
            if item.name in files:
                raise ValueError("duplicate entry")
            if any(part in {".npmrc", ".netrc", ".pypirc", "pip.conf", "config.yaml"} for part in relative.parts):
                raise ValueError("credential file refused")
            total += item.size
            if total > 8 * 1024 * 1024 * 1024:
                raise ValueError("unpacked limit")
            value = hashlib.sha256()
            stream = archive.extractfile(item)
            while chunk := stream.read(1024 * 1024):
                value.update(chunk)
            files[item.name] = {"sha256": value.hexdigest(), "size": item.size}
        entry = archive.getmember("offline.json")
        if entry.size > 1024 * 1024:
            raise ValueError("manifest limit")
        manifest = json.load(archive.extractfile(entry))
    if manifest.get("schema_version") != 1 or manifest.get("files") != {
        name: value for name, value in files.items() if name != "offline.json"
    }:
        raise ValueError("content mismatch")
    if any(manifest.get(key) != profile.get(key) for key in ["profile_id", "profile_digest", "platform", "abi"]):
        raise ValueError("profile mismatch")
    return manifest


def pack(directory, profile, output):
    directory = Path(directory).resolve()
    output = Path(output).resolve()
    if output.is_relative_to(directory):
        raise ValueError("output must be outside materials")
    files = {}
    for file in sorted(directory.rglob("*")):
        if file.is_symlink():
            raise ValueError("material links must be normalized before packing")
        if file.is_file():
            files[file.relative_to(directory).as_posix()] = {"sha256": digest(file), "size": file.stat().st_size}
    manifest = {
        "schema_version": 1,
        **{key: profile[key] for key in ["profile_id", "profile_digest", "platform", "abi"]},
        "files": files,
    }
    with tempfile.TemporaryDirectory(prefix="runtime-pack-") as tmp:
        metadata = Path(tmp) / "offline.json"
        metadata.write_text(json.dumps(manifest, sort_keys=True))
        with tarfile.open(output, "w:gz") as archive:
            for name in files:
                archive.add(directory / name, arcname=name, recursive=False)
            archive.add(metadata, arcname="offline.json")
    verify(output, profile)
    return {"path": str(output), "sha256": digest(output), "size_bytes": output.stat().st_size}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("management_redirect_refused")


def request(base, path, *, document=None, file=None, method="POST", _scope_only=False):
    address = urlsplit(base)
    if address.scheme not in {"http", "https"} or not address.netloc or address.username or address.password:
        raise ValueError("invalid_management_url")
    token = os.environ.get("BISHENG_MANAGEMENT_TOKEN", "")
    if not token:
        raise ValueError("set BISHENG_MANAGEMENT_TOKEN to the authorized human session token")
    headers = {"Cookie": "access_token_cookie=" + token}
    parts = urlsplit(path).path.strip("/").split("/")
    if (
        method != "GET"
        and len(parts) == 6
        and parts[:3] == ["api", "v1", "apps"]
        and parts[4:] == ["runtime", "materials"]
    ):
        # Freeze the server-verified view before opening or uploading the archive.
        scope = request(base, f"/api/v1/apps/{parts[3]}/runtime/state", method="GET", _scope_only=True)
        headers["X-Management-Tenant"] = str(scope)
    if file:
        stream = open(file, "rb")
        body = stream
        headers["Content-Type"] = "application/octet-stream"
        headers["Content-Length"] = str(Path(file).stat().st_size)
    else:
        stream = None
        body = json.dumps(document).encode() if document is not None else None
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=120) as response:
            answer = json.load(response)
            scope = response.headers.get("X-Management-Tenant")
        if answer.get("status_code", 200) not in {0, 200}:
            raise ValueError("platform import refused: " + str(answer.get("status_message", "unknown")))
        if _scope_only:
            if not scope or not scope.isdecimal() or int(scope) <= 0:
                raise ValueError("management_scope_unavailable")
            return int(scope)
        return answer.get("data", answer)
    finally:
        if stream:
            stream.close()


def export_profile(document, reference, platform):
    rows = [item for item in document["profiles"] if f"{item['code']}@{item['revision']}" == reference]
    if len(rows) != 1:
        raise ValueError("profile reference unavailable")
    definition = rows[0]
    normalized = {"contract_version": 1, "official": False, **definition}
    normalized["platforms"] = {
        key: {"uid": 10001, "gid": 10001, **value} for key, value in definition["platforms"].items()
    }
    sha = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return {
        "profile_id": sha[:32],
        "profile_digest": sha,
        "profile_revision": reference,
        "language": definition["language"],
        "platform": platform,
        **normalized["platforms"][platform],
    }


def import_catalog(base, document, *, set_defaults=False):
    imported = {}
    for definition in document["profiles"]:
        row = request(base, "/api/v1/runtime/profiles", document=definition)
        imported[f"{definition['code']}@{definition['revision']}"] = row
    if set_defaults:
        defaults = {row["language"]: row for row in request(base, "/api/v1/runtime/profiles/defaults", method="GET")}
        for language, reference in document.get("defaults", {}).items():
            row = imported[reference]
            previous = defaults.get(language, {})
            if previous.get("profile_id") == row["id"]:
                continue
            request(
                base,
                "/api/v1/runtime/profiles/default",
                method="PUT",
                document={
                    "language": language,
                    "profile_id": row["id"],
                    "expected_generation": previous.get("generation", 0),
                },
            )
    return {key: row["id"] for key, row in imported.items()}


def prepare_offline(source, materials, profile, image_id):
    if image_id != profile["preparer_image_id"]:
        raise ValueError("preparer image ID mismatch")
    source = Path(source).resolve()
    materials = Path(materials).resolve()
    if materials == source or materials.is_relative_to(source) or source.is_relative_to(materials):
        raise ValueError("materials must be separate from source")
    if materials.exists() and any(materials.iterdir()):
        raise ValueError("materials output must be empty")
    materials.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-prepare-") as tmp:
        work = Path(tmp) / "source"
        shutil.copytree(source, work, symlinks=False)
        # Installation hooks run only in the second, networkless container.
        common = [
            "docker",
            "run",
            "--rm",
            "--platform",
            profile["platform"],
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            "2g",
            "--pids-limit",
            "256",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=512m",
            "--env",
            "HOME=/tmp",
            "--mount",
            f"type=bind,src={work},dst=/workspace/app",
            "--mount",
            f"type=bind,src={source},dst=/original,readonly",
            "--mount",
            f"type=bind,src={materials},dst=/output",
        ]
        subprocess.run(
            [*common, image_id, "python", "/opt/bisheng/prepare.py", "download", profile["language"]], check=True
        )
        validation = Path(tmp) / "validated"
        shutil.copytree(materials, validation)
        isolated = [
            argument.replace(f"src={materials},dst=/output", f"src={validation},dst=/output") for argument in common
        ]
        subprocess.run(
            [
                *isolated,
                "--network",
                "none",
                image_id,
                "python",
                "/opt/bisheng/prepare.py",
                "lock",
                profile["language"],
            ],
            check=True,
        )
        # Ship registry materials, not source-dependent install outputs or node_modules links.
        for logs in (materials / "npm").glob("*/cache/_logs"):
            shutil.rmtree(logs, ignore_errors=True)
    return materials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    item = commands.add_parser("catalog")
    item.add_argument("--inventory", action="append", required=True)
    item.add_argument("--output", required=True)
    item.add_argument("--revision", type=int, default=1)
    item = commands.add_parser("export-profile")
    item.add_argument("--catalog", required=True)
    item.add_argument("--reference", required=True)
    item.add_argument("--platform", required=True)
    item.add_argument("--output", required=True)
    for name in ["pack-offline", "verify-offline", "prepare-offline"]:
        item = commands.add_parser(name)
        item.add_argument("--profile", required=True)
        if name == "verify-offline":
            item.add_argument("--file", required=True)
        else:
            item.add_argument("--materials", required=True)
            item.add_argument("--output", required=True)
        if name == "prepare-offline":
            item.add_argument("--source", required=True)
            item.add_argument("--image-id", required=True)
    item = commands.add_parser("import-profile")
    item.add_argument("--base-url", required=True)
    item.add_argument("--file", required=True)
    item.add_argument("--set-defaults", action="store_true", help="CAS-update the catalog defaults after import")
    for name in ["import-base", "import-app-pack"]:
        item = commands.add_parser(name)
        item.add_argument("--base-url", required=True)
        item.add_argument("--file", required=True)
        item.add_argument("--profile-reference", required=True)
        item.add_argument("--platform", required=True)
        if name == "import-app-pack":
            item.add_argument("--app-id", required=True)
    args = parser.parse_args()
    if args.command == "catalog":
        catalog(args.inventory, args.output, args.revision)
        return
    if args.command == "export-profile":
        Path(args.output).write_text(
            json.dumps(
                export_profile(json.loads(Path(args.catalog).read_text()), args.reference, args.platform), indent=2
            )
            + "\n"
        )
        return
    if args.command in {"pack-offline", "verify-offline", "prepare-offline"}:
        profile = json.loads(Path(args.profile).read_text())
        if args.command == "verify-offline":
            print(json.dumps(verify(args.file, profile)))
            return
        if args.command == "prepare-offline":
            prepare_offline(args.source, args.materials, profile, args.image_id)
        print(json.dumps(pack(args.materials, profile, args.output)))
        return
    if args.command == "import-profile":
        document = json.loads(Path(args.file).read_text())
        print(json.dumps(import_catalog(args.base_url, document, set_defaults=args.set_defaults)))
        return
    from urllib.parse import urlencode

    path = (
        "/api/v1/runtime/materials/public"
        if args.command == "import-base"
        else f"/api/v1/apps/{args.app_id}/runtime/materials"
    )
    query = urlencode({"profile": args.profile_reference, "platform": args.platform, "sha256": digest(args.file)})
    print(json.dumps(request(args.base_url, path + "?" + query, file=args.file)))


if __name__ == "__main__":
    main()
