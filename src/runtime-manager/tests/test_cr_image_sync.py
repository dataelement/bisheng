"""Exercise native CR publication and failure boundaries without registry writes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime_manager.image_catalog import IMAGE_NAMES, create_inventory, merge_inventories

ROOT = Path(__file__).resolve().parents[3]
REVISION = "a" * 40


def sync_images(tmp_path, monkeypatch, arch="amd64", failure=""):
    metadata = {}
    for number, name in enumerate(IMAGE_NAMES, 1):
        tag = f"dataelement/bisheng-{name}:v-test-{arch}"
        metadata[name] = {
            "Id": "sha256:" + f"{number:064x}",
            "Os": "linux",
            "Architecture": arch,
            "RepoTags": [tag],
            "RepoDigests": [tag.split(":")[0] + "@sha256:" + f"{number + 100:064x}"],
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": REVISION,
                    "org.opencontainers.image.version": "v-test",
                }
            },
        }
    document = create_inventory(
        metadata,
        platform=f"linux/{arch}",
        release="v-test",
        source_revision=REVISION,
        published=True,
        native_arch=arch,
        smoke_passed=IMAGE_NAMES,
    )
    if failure == "stale-source":
        document["source_revision"] = "b" * 40
    if failure == "unpublished":
        document["state"] = "local-native-verified"
    native = tmp_path / f"dist/runtime-metadata-{arch}"
    native.mkdir(parents=True)
    (native / "native-smoke.json").write_text(json.dumps(IMAGE_NAMES))
    inventory = tmp_path / f"dist/runtime-images-{arch}.json"
    inventory.write_text(json.dumps(document))
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    tool = tmp_path / "src/runtime-manager/runtime_manager"
    tool.mkdir(parents=True)
    (tool / "image_catalog.py").write_text((ROOT / "src/runtime-manager/runtime_manager/image_catalog.py").read_text())
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "git").write_text(f"#!/bin/sh\nprintf '%s\\n' '{REVISION}'\n")
    (binary / "docker").write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with Path("commands.jsonl").open("a") as stream:stream.write(json.dumps(args)+"\\n")
failure=os.environ.get("SYNC_TEST_FAILURE","")
if args[:3]==["buildx","imagetools","inspect"]:
 if failure=="existing" and "bisheng-app-static:" in args[3]:sys.exit(0)
 print("unauthorized: manifest not found (authentication required)" if failure=="auth" else "manifest unknown",file=sys.stderr)
 sys.exit(1)
elif args[0]=="push":
 if failure=="push":sys.exit(42)
elif args[:2]==["image","inspect"]:
 tag=args[-1]; name=tag.split("bisheng-")[1].split(":")[0]
 metadata=json.loads(Path("metadata.json").read_text())[name]
 metadata["RepoTags"].append(tag)
 metadata["RepoDigests"].append(tag.split(":")[0]+"@sha256:"+"e"*64)
 print(json.dumps([metadata]))
elif args[0]!="tag":sys.exit(99)
""")
    for item in binary.iterdir():
        item.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("SYNC_TEST_FAILURE", failure)
    monkeypatch.setenv("RUNTIME_RELEASE", "v-test")
    monkeypatch.setenv("TARGET_ARCH", arch)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/sync_runtime_images_cr.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    log = tmp_path / "commands.jsonl"
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert json.loads(inventory.read_text()) == document
    return result, commands, metadata


@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_sync_preserves_native_image_ids_and_records_only_cr_digests(tmp_path, monkeypatch, arch):
    result, commands, metadata = sync_images(tmp_path, monkeypatch, arch)
    assert result.returncode == 0, result.stderr
    tags = [item for item in commands if item[0] == "tag"]
    assert len(tags) == 9
    assert {item[1] for item in tags} == {image["Id"] for image in metadata.values()}
    assert all(item[2].startswith("cr.dataelem.com/dataelement/") for item in tags)
    assert not any(item[0] in {"build", "pull", "run"} for item in commands)
    pushes = [item for item in commands if item[0] == "push"]
    assert len(pushes) == 9
    inventory = json.loads((tmp_path / f"dist/cr/runtime-images-{arch}.json").read_text())
    assert inventory["state"] == "published-native-verified"
    assert inventory["platform"] == f"linux/{arch}"
    for name, image in inventory["images"].items():
        assert image["image_id"] == metadata[name]["Id"]
        assert image["image"].startswith(f"cr.dataelem.com/dataelement/bisheng-{name}@sha256:")
        assert image["tag"].endswith(f":v-test-{arch}")


@pytest.mark.parametrize("failure", ["existing", "auth", "push", "stale-source", "unpublished"])
def test_sync_failure_cannot_produce_a_published_cr_inventory(tmp_path, monkeypatch, failure):
    result, commands, _ = sync_images(tmp_path, monkeypatch, failure=failure)
    assert result.returncode != 0
    assert not (tmp_path / "dist/cr/runtime-images-amd64.json").exists()
    if failure != "push":
        assert not any(item[0] in {"tag", "push"} for item in commands)


def test_both_cr_architectures_produce_a_release_and_domestic_profile_catalog(tmp_path, monkeypatch):
    paths = []
    for arch in ("amd64", "arm64"):
        directory = tmp_path / arch
        result, _, _ = sync_images(directory, monkeypatch, arch)
        assert result.returncode == 0, result.stderr
        paths.append(directory / f"dist/cr/runtime-images-{arch}.json")
    release = merge_inventories([json.loads(path.read_text()) for path in paths])
    assert len(release["offline_layers"]["runtime_images"]) == 18
    assert all(image.startswith("cr.dataelem.com/") for image in release["offline_layers"]["runtime_images"])
    output = tmp_path / "runtime-profiles.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src/runtime-manager/tools/runtime_materials.py"),
            "catalog",
            "--inventory",
            str(paths[0]),
            "--inventory",
            str(paths[1]),
            "--output",
            str(output),
            "--revision",
            "17",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    profiles = json.loads(output.read_text())["profiles"]
    assert len(profiles) == 3
    for profile in profiles:
        assert set(profile["platforms"]) == {"linux/amd64", "linux/arm64"}
        for platform in profile["platforms"].values():
            assert platform["runtime_image"].startswith("cr.dataelem.com/")
            assert platform["preparer_image"].startswith("cr.dataelem.com/")
