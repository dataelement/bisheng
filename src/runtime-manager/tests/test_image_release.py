"""覆盖 AC: AC-25、AC-27、AC-39、AC-42、AC-54、AC-56。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime_manager.image_catalog import IMAGE_NAMES, create_inventory, merge_inventories

ROOT = Path(__file__).resolve().parents[3]
REVISION = "a" * 40


def metadata(platform="linux/amd64", published=True):
    os_name, architecture = platform.split("/")
    result = {}
    for index, name in enumerate(IMAGE_NAMES):
        tag = f"example.test/bisheng-{name}:v-test-{architecture}"
        result[name] = {
            "Id": "sha256:" + f"{index + 1:064x}",
            "Os": os_name,
            "Architecture": architecture,
            "RepoTags": [tag],
            "RepoDigests": [tag.rsplit(":", 1)[0] + "@sha256:" + f"{index + 100:064x}"] if published else [],
            "Config": {
                "Labels": {"org.opencontainers.image.revision": REVISION, "org.opencontainers.image.version": "v-test"}
            },
        }
    return result


def inventory(platform="linux/amd64", published=True):
    return create_inventory(
        metadata(platform, published),
        platform=platform,
        release="v-test",
        source_revision=REVISION,
        published=published,
        native_arch=platform.split("/")[1],
        smoke_passed=IMAGE_NAMES,
    )


def test_inventory_freezes_correct_repository_digest_and_role_mapping():
    images = metadata()
    images["runtime-helper"]["RepoDigests"].insert(0, "another.test/not-the-helper@sha256:" + "f" * 64)
    result = create_inventory(
        images,
        platform="linux/amd64",
        release="v-test",
        source_revision=REVISION,
        published=True,
        native_arch="amd64",
        smoke_passed=IMAGE_NAMES,
    )
    assert result["images"]["runtime-helper"]["image"].startswith("example.test/bisheng-runtime-helper@sha256:")
    assert result["roles"]["egress-proxy"] == result["roles"]["admission"] == "runtime-manager"
    assert result["images"]["runtime-assembler"]["tools"]["crane"] == "v0.22.1"


@pytest.mark.parametrize(
    "change",
    [
        "wrong-image-arch",
        "emulated-runner",
        "missing-smoke",
        "missing-image",
        "wrong-source",
        "missing-digest",
        "wrong-digest-repository",
    ],
)
def test_inventory_rejects_incomplete_or_cross_architecture_evidence(change):
    images = metadata()
    native_arch = "amd64"
    smoke = list(IMAGE_NAMES)
    if change == "wrong-image-arch":
        images["runtime-helper"]["Architecture"] = "arm64"
    elif change == "emulated-runner":
        native_arch = "arm64"
    elif change == "missing-smoke":
        smoke.remove("runtime-helper")
    elif change == "missing-image":
        images.pop("runtime-assembler")
    elif change == "wrong-source":
        images["runtime-assembler"]["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
    elif change == "missing-digest":
        images["runtime-helper"]["RepoDigests"] = []
    else:
        images["runtime-helper"]["RepoDigests"] = ["another.test/helper@sha256:" + "f" * 64]
    with pytest.raises(ValueError):
        create_inventory(
            images,
            platform="linux/amd64",
            release="v-test",
            source_revision=REVISION,
            published=True,
            native_arch=native_arch,
            smoke_passed=smoke,
        )


def test_local_inventory_cannot_be_promoted_to_published_release():
    local = inventory(published=False)
    assert local["state"] == "local-native-verified"
    assert local["images"]["runtime-helper"]["image"] is None
    with pytest.raises(ValueError, match="published"):
        merge_inventories([local, inventory("linux/arm64")])


def test_release_requires_both_native_platforms_and_one_source_revision():
    amd, arm = inventory(), inventory("linux/arm64")
    with pytest.raises(ValueError, match="both native"):
        merge_inventories([amd])
    arm["source_revision"] = "b" * 40
    with pytest.raises(ValueError, match="source"):
        merge_inventories([amd, arm])
    arm["source_revision"] = REVISION
    result = merge_inventories([amd, arm])
    assert set(result["platforms"]) == {"linux/amd64", "linux/arm64"}
    assert len(result["offline_layers"]["runtime_images"]) == 18
    assert "build_dependencies" in result["offline_layers"]
    assert "platform_apis" in result["offline_layers"]


def test_helper_installs_trusted_package_and_assembler_uses_pinned_toolchain():
    helper = (ROOT / "src/runtime-manager/Dockerfile.helper").read_text()
    assert "--no-build-isolation" in helper
    assert "--no-index" in helper and "--no-deps" in helper
    assert "USER 10001:10001" in helper and '"-I"' in helper
    assembler = (ROOT / "src/runtime-manager/Dockerfile.assembler").read_text()
    assert "golang:1.27.3-bookworm" in assembler and "v0.22.1" in assembler
    assert "/usr/share/licenses/crane" in assembler


def test_ci_keeps_native_gate_and_immutable_digest_indexes():
    workflow = (ROOT / ".github/workflows/runtime-images.yml").read_text()
    assert "ubuntu-22.04-arm" in workflow and "needs: native" in workflow
    assert "setup-qemu" not in workflow
    assert "runtime-release.json" in workflow
    assert "RUNTIME_PUBLISH: '1'" in workflow
    builder = (ROOT / "scripts/build_runtime_images.sh").read_text()
    assert "--read-only" in builder and "--network none" in builder
    assert "runtime-helper" in builder and "runtime-assembler" in builder
    assert "Refusing to overwrite" in builder
    assert "--entrypoint uname" in builder
    assert "--build-arg MANAGER_IMAGE=" in builder
    assert "--build-arg HELPER_IMAGE=" in builder


def test_indexes_require_exactly_verified_platform_manifests():
    from runtime_manager.image_catalog import SERVICE_INDEX_NAMES, attach_indexes

    release = merge_inventories([inventory(), inventory("linux/arm64")])
    indexes = {
        name: (
            "sha256:" + "e" * 64,
            {
                "manifests": [
                    {
                        "platform": {"os": "linux", "architecture": platform.split("/")[1]},
                        "digest": images[name]["image"].split("@")[1],
                    }
                    for platform, images in release["platforms"].items()
                ]
            },
        )
        for name in SERVICE_INDEX_NAMES
    }
    result = attach_indexes(release, indexes)
    assert len(result["service_indexes"]) == 4
    assert "service_indexes" not in release
    indexes["runtime-helper"][1]["manifests"][0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="exactly"):
        attach_indexes(release, indexes)


def mock_builder(tmp_path, monkeypatch, *, publish=False, wrong_engine=False, existing=False):
    import os
    import subprocess

    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "docker.jsonl"
    docker = binary / "docker"
    docker.write_text("""#!/usr/bin/env python3
import hashlib,json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ["MOCK_DOCKER_LOG"],"a") as stream:stream.write(json.dumps(args)+"\\n")
if args[0]=="info":print("linux/"+("arm64" if os.environ.get("MOCK_WRONG_ENGINE")=="1" else "amd64"))
elif args[:3]==["buildx","imagetools","inspect"]:
 if os.environ.get("MOCK_EXISTING")=="1":print("existing")
 else:print("manifest unknown",file=sys.stderr);sys.exit(1)
elif args[0]=="run":
 if "uname" in args:print("x86_64")
 elif "crane" in args and args[-1]=="version":print("v0.22.1")
elif args[:2]==["image","inspect"]:
 tag=args[-1];name=tag.split("bisheng-")[1].split(":")[0]
 print(json.dumps([{"Id":"sha256:"+hashlib.sha256(name.encode()).hexdigest(),"Os":"linux","Architecture":"amd64","RepoTags":[tag],"RepoDigests":[tag.rsplit(":",1)[0]+"@sha256:"+hashlib.sha256(tag.encode()).hexdigest()],"Config":{"Labels":{"org.opencontainers.image.revision":"a"*40,"org.opencontainers.image.version":"v-test"}}}]))
""")
    docker.chmod(0o755)
    for name, source in {
        "uname": "#!/bin/sh\nprintf 'x86_64\\n'\n",
        "git": "#!/bin/sh\nif [ \"$1\" = rev-parse ]; then printf '%040d\\n' 0 | tr 0 a; fi\n",
    }.items():
        item = binary / name
        item.write_text(source)
        item.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("MOCK_DOCKER_LOG", str(log))
    monkeypatch.setenv("MOCK_WRONG_ENGINE", str(int(wrong_engine)))
    monkeypatch.setenv("MOCK_EXISTING", str(int(existing)))
    monkeypatch.setenv("RUNTIME_RELEASE", "v-test")
    monkeypatch.setenv("RUNTIME_PUBLISH", str(int(publish)))
    monkeypatch.setenv("TARGET_ARCH", "amd64")
    # The mock checkout supplies only the read-only inventory tool; no real Docker is invoked.
    tool = tmp_path / "src/runtime-manager/runtime_manager"
    tool.mkdir(parents=True)
    (tool / "image_catalog.py").write_text((ROOT / "src/runtime-manager/runtime_manager/image_catalog.py").read_text())
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/build_runtime_images.sh")], cwd=tmp_path, capture_output=True, text=True
    )
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    return result, commands


def test_mock_builder_local_never_pushes_and_freezes_only_local_evidence(tmp_path, monkeypatch):
    import json

    result, commands = mock_builder(tmp_path, monkeypatch)
    assert result.returncode == 0, result.stderr
    assert not any(command[0] == "push" for command in commands)
    assert len([command for command in commands if command[:2] == ["buildx", "build"]]) == 9
    assert (tmp_path / "dist/runtime-images-amd64.json").is_file(), result.stdout + result.stderr
    document = json.loads((tmp_path / "dist/runtime-images-amd64.json").read_text())
    assert document["state"] == "local-native-verified"


def test_mock_builder_rejects_cross_architecture_before_build(tmp_path, monkeypatch):
    result, commands = mock_builder(tmp_path, monkeypatch, wrong_engine=True)
    assert result.returncode != 0
    assert not any(command[:2] == ["buildx", "build"] for command in commands)


def test_mock_builder_rejects_existing_release_before_build(tmp_path, monkeypatch):
    result, commands = mock_builder(tmp_path, monkeypatch, publish=True, existing=True)
    assert result.returncode != 0
    assert "Refusing to overwrite" in result.stderr
    assert not any(command[:2] == ["buildx", "build"] for command in commands)


def test_mock_publishing_happens_after_all_native_smokes(tmp_path, monkeypatch):
    result, commands = mock_builder(tmp_path, monkeypatch, publish=True)
    assert result.returncode == 0, result.stderr
    first_push = next(index for index, command in enumerate(commands) if command[0] == "push")
    assert all(index < first_push for index, command in enumerate(commands) if command[0] == "run")
    assert len([command for command in commands if command[0] == "push"]) == 9


def test_python_package_inventory_records_versions_and_license_locations():
    from runtime_manager.image_catalog import python_packages

    result = python_packages()
    assert result["python"]
    package = next(item for item in result["packages"] if item["name"].lower() == "httpx")
    assert package["version"] and package["license"]
    assert package["license_files"]


def test_generated_inventory_still_builds_original_profile_catalog(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "materials_release_test", ROOT / "src/runtime-manager/tools/runtime_materials.py"
    )
    materials = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(materials)
    paths = []
    for platform in ("linux/amd64", "linux/arm64"):
        path = tmp_path / (platform.split("/")[1] + ".json")
        path.write_text(json.dumps(inventory(platform)))
        paths.append(path)
    output = tmp_path / "profiles.json"
    materials.catalog(paths, output, 17)
    result = json.loads(output.read_text())
    assert len(result["profiles"]) == 3
    assert all(set(profile["platforms"]) == {"linux/amd64", "linux/arm64"} for profile in result["profiles"])
    assert result["defaults"]["python3.11"] == "python311-standard@17"
