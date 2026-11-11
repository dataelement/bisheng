"""Release metadata gates. All image references are fictitious local fixtures."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "package_helm", Path(__file__).parents[1] / "package_helm.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def artifacts():
    digest = "sha256:" + "a" * 64
    ref = "example.invalid/runtime@" + digest
    source = "b" * 40
    images = {
        name: {
            "reference": "example.invalid/" + name + "@" + digest,
            "platforms": sorted(mod.ARCHITECTURES),
            "source_revision": source,
        }
        for name in set(mod.IMAGE_PATHS) | mod.RUNTIME_IMAGES
    }
    platforms = {
        arch: {
            "runtime_image": ref,
            "runtime_digest": digest,
            "runtime_image_id": digest,
            "preparer_image": ref,
            "preparer_digest": digest,
            "preparer_image_id": digest,
            "abi": "fixture",
            "toolchain": {"fixture": "1"},
        }
        for arch in mod.ARCHITECTURES
    }
    profiles = [
        {
            "code": lang.replace(".", ""),
            "revision": 1,
            "language": lang,
            "official": True,
            "platforms": platforms,
        }
        for lang in ("python3.11", "node20", "static")
    ]
    raw = json.dumps(
        {
            "profiles": profiles,
            "defaults": {p["language"]: p["code"] + "@1" for p in profiles},
        }
    ).encode()
    lock = {
        "schema_version": 1,
        "release": "3.1.0-beta1",
        "catalog_sha256": hashlib.sha256(raw).hexdigest(),
    }
    image_set = {
        "schema_version": 1,
        "release": "3.1.0-beta1",
        "source_revision": source,
        "runtime_contract": 2,
        "gateway_sql_contract": "1.8.0",
        "images": images,
        "catalog_images": [ref],
    }
    return image_set, raw, lock


def test_complete_metadata_accepts_all_workloads_jobs_and_helpers():
    image_set, raw, lock = artifacts()
    assert len(mod.validate(image_set, raw, lock, version="3.1.0-beta1")) == 20


@pytest.mark.parametrize(
    "change",
    ["missing", "tag", "arch", "source", "contract", "hash", "material", "defaults"],
)
def test_incomplete_or_mixed_release_refused(change):
    image_set, raw, lock = artifacts()
    if change == "missing":
        del image_set["images"]["helper"]
    if change == "tag":
        image_set["images"]["backend"]["reference"] = "example.invalid/backend:latest"
    if change == "arch":
        image_set["images"]["sandbox"]["platforms"] = ["linux/amd64"]
    if change == "source":
        image_set["images"]["manager"]["source_revision"] = "c" * 40
    if change == "contract":
        image_set["runtime_contract"] = 1
    if change == "hash":
        lock["catalog_sha256"] = "d" * 64
    if change == "material":
        image_set["catalog_images"] = []
    if change == "defaults":
        document = json.loads(raw)
        document["defaults"].pop("node20")
        raw = json.dumps(document).encode()
        lock["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        mod.validate(image_set, raw, lock, version="3.1.0-beta1")


def test_package_stages_locked_sources_and_catalog_without_image_build(
    tmp_path, monkeypatch
):
    import os
    import shutil
    import tarfile
    import yaml

    image_set, raw, lock = artifacts()
    image_file = tmp_path / "image-set.json"
    image_file.write_text(json.dumps(image_set))
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "catalog.json").write_bytes(raw)
    (catalog / "catalog.lock.json").write_text(json.dumps(lock))
    helm = os.environ.get("HELM_BIN") or shutil.which("helm")
    assert helm
    # This test's declared images are deliberately fictional. Only the staging
    # and archive paths are exercised, never represented as a formal release.
    monkeypatch.setattr(mod, "source_gate", lambda _image_set: None)
    artifact = mod.package(image_file, catalog, tmp_path / "out", helm=helm)
    with tarfile.open(artifact) as archive:
        names = archive.getnames()
        assert "bisheng/files/image-set.json" in names
        assert "bisheng/files/runtime-catalog/catalog.json" in names
        assert any(
            name.startswith("bisheng/charts/runtime/") or "bisheng-app-runtime" in name
            for name in names
        )
        values = yaml.safe_load(archive.extractfile("bisheng/values.yaml").read())
        assert values["backend"]["image"]["digest"] == "sha256:" + "a" * 64
        assert (
            values["runtime"]["images"]["helper"]
            == image_set["images"]["helper"]["reference"]
        )
    assert artifact.with_suffix(".tgz.sha256").is_file()


def test_release_source_must_match_checkout_before_staging(monkeypatch):
    image_set, _, _ = artifacts()
    monkeypatch.setattr(
        mod.subprocess, "check_output", lambda *_args, **_kwargs: "c" * 40
    )
    with pytest.raises(ValueError, match="not_this_checkout"):
        mod.source_gate(image_set)
    monkeypatch.setattr(
        mod.subprocess,
        "check_output",
        lambda command, **_kwargs: (
            image_set["source_revision"] if "rev-parse" in command else " M source.py"
        ),
    )
    with pytest.raises(ValueError, match="must_be_clean"):
        mod.source_gate(image_set)


def test_ignored_local_deployment_values_are_not_packaged(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private-values.yaml\n")
    chart = tmp_path / "docker/helm/bisheng"
    chart.mkdir(parents=True)
    (chart / "values.yaml").write_text("public: example\n")
    (chart / "private-values.yaml").write_text("not-for-release: local-fixture\n")
    assert list(mod.chart_sources(tmp_path)) == ["docker/helm/bisheng/values.yaml"]
