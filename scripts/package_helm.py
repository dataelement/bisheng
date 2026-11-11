#!/usr/bin/env python3
"""Package an immutable Helm release from release-owned image/catalog artifacts.

Does not build images, contact registries, or deploy. Artifact provenance and
native-architecture execution are responsibilities of the image release job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
SOURCE_IMAGES = {
    "backend",
    "worker",
    "linsight",
    "beat",
    "frontend",
    "sandbox",
    "manager",
    "entry",
    "egress",
    "admission",
    "helper",
    "assembler",
}
IMAGE_PATHS = {
    name: (name, "image")
    for name in (
        "backend",
        "worker",
        "linsight",
        "beat",
        "frontend",
        "mysql",
        "redis",
        "minio",
        "elasticsearch",
        "milvus",
        "openfga",
        "gateway",
    )
}
IMAGE_PATHS.update(
    {"etcd": ("milvus", "etcd", "image"), "sandbox": ("sandbox", "image")}
)
RUNTIME_IMAGES = {"manager", "entry", "egress", "admission", "helper", "assembler"}
ARCHITECTURES = {"linux/amd64", "linux/arm64"}


def validate(image_set, catalog_raw, catalog_lock, *, version):
    if (
        image_set.get("schema_version") != 1
        or image_set.get("release") != version
        or not re.fullmatch(r"[a-f0-9]{40}", str(image_set.get("source_revision", "")))
    ):
        raise ValueError("image_set_release_or_source_invalid")
    if (
        image_set.get("runtime_contract") != 2
        or image_set.get("gateway_sql_contract") != "1.8.0"
    ):
        raise ValueError("image_set_contract_mismatch")
    images = image_set.get("images", {})
    required = set(IMAGE_PATHS) | RUNTIME_IMAGES
    if not isinstance(images, dict) or not required <= images.keys():
        raise ValueError("image_set_missing_workload_job_or_helper")
    for name in required:
        row = images[name]
        if (
            not isinstance(row, dict)
            or not DIGEST.fullmatch(str(row.get("reference", "")))
            or set(row.get("platforms", [])) != ARCHITECTURES
        ):
            raise ValueError("image_set_digest_or_architecture_invalid")
        if (
            name in SOURCE_IMAGES
            and row.get("source_revision") != image_set["source_revision"]
        ):
            raise ValueError("image_set_source_mismatch")
    if (
        catalog_lock.get("schema_version") != 1
        or catalog_lock.get("release") != version
        or catalog_lock.get("catalog_sha256") != hashlib.sha256(catalog_raw).hexdigest()
    ):
        raise ValueError("catalog_lock_mismatch")
    catalog = json.loads(catalog_raw)
    profile_schema = json.loads(
        (ROOT / "docker/helm/bisheng/files/runtime-profile.schema.json").read_text()
    )
    identities = {}
    materials = set()
    for profile in catalog.get("profiles", []):
        try:
            jsonschema.validate(profile, profile_schema)
        except jsonschema.ValidationError:
            raise ValueError("catalog_profile_schema_invalid") from None
        if (
            profile.get("official") is not True
            or set(profile.get("platforms", {})) != ARCHITECTURES
        ):
            raise ValueError("catalog_not_official_dual_architecture")
        identity = f"{profile['code']}@{profile['revision']}"
        if identity in identities:
            raise ValueError("catalog_duplicate_revision")
        identities[identity] = profile["language"]
        for platform in profile["platforms"].values():
            for role in ("runtime", "preparer"):
                ref = platform.get(role + "_image", "")
                digest = platform.get(role + "_digest")
                if not DIGEST.fullmatch(ref) or ref.rsplit("@", 1)[1] != digest:
                    raise ValueError("catalog_image_digest_invalid")
                materials.add(ref)
    defaults = catalog.get("defaults", {})
    if (
        not identities
        or not isinstance(defaults, dict)
        or not {"python3.11", "node20", "static"} <= defaults.keys()
    ):
        raise ValueError("catalog_language_defaults_missing")
    if any(identities.get(ref) != language for language, ref in defaults.items()):
        raise ValueError("catalog_default_invalid")
    declared = image_set.get("catalog_images", [])
    if set(declared) != materials:
        raise ValueError("catalog_material_coverage_mismatch")
    return images


def source_gate(image_set):
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if revision != image_set["source_revision"]:
        raise ValueError("image_set_source_is_not_this_checkout")
    changed = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            "src/backend",
            "src/runtime-manager",
            "docker/helm",
            "deploy/kubernetes/app-runtime",
            "scripts/package_helm.py",
        ],
        cwd=ROOT,
        text=True,
    )
    if changed:
        raise ValueError("release_source_checkout_must_be_clean")


def chart_sources(root):
    paths = (
        "docker/helm/bisheng",
        "docker/helm/bisheng-sandbox",
        "deploy/kubernetes/app-runtime",
    )
    output = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *paths,
        ],
        cwd=root,
        text=True,
    )
    for relative in output.split("\0"):
        if not relative:
            continue
        source = Path(root) / relative
        if source.is_symlink():
            raise ValueError("release_chart_symlink_refused")
        if (
            source.is_file()
            and "charts" not in Path(relative).parts
            and not source.name.endswith(".tgz")
        ):
            yield relative


def package(
    image_set_path, catalog_directory, output, *, helm="helm", validate_only=False
):
    chart = ROOT / "docker/helm/bisheng"
    metadata = yaml.safe_load((chart / "Chart.yaml").read_text())
    image_set = json.loads(Path(image_set_path).read_text())
    catalog_directory = Path(catalog_directory)
    raw = (catalog_directory / "catalog.json").read_bytes()
    lock = json.loads((catalog_directory / "catalog.lock.json").read_text())
    images = validate(image_set, raw, lock, version=metadata["appVersion"])
    source_gate(image_set)
    if validate_only:
        return None
    with tempfile.TemporaryDirectory(prefix="bisheng-helm-") as directory:
        stage = Path(directory)
        # Copy only Git-visible source files. Ignored customer values/keys and
        # generated dependency archives must never enter a public release.
        for relative in chart_sources(ROOT):
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        target = stage / "docker/helm/bisheng"
        values = yaml.safe_load((target / "values.yaml").read_text())
        for name, path in IMAGE_PATHS.items():
            cursor = values
            for key in path:
                cursor = cursor[key]
            repository, digest = images[name]["reference"].rsplit("@", 1)
            cursor.update(repository=repository, digest=digest, tag="")
        for name in RUNTIME_IMAGES:
            values["runtime"]["images"][name] = images[name]["reference"]
        (target / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False))
        bundled = target / "files/runtime-catalog"
        bundled.mkdir(parents=True)
        (bundled / "catalog.json").write_bytes(raw)
        (bundled / "catalog.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
        (target / "files/image-set.json").write_text(
            json.dumps(image_set, indent=2) + "\n"
        )
        subprocess.run(
            [helm, "dependency", "build", str(target), "--skip-refresh"],
            check=True,
            capture_output=True,
        )
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [helm, "package", str(target), "--destination", str(output)],
            check=True,
            capture_output=True,
        )
        artifact = output / f"bisheng-{metadata['version']}.tgz"
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_suffix(".tgz.sha256").write_text(f"{checksum}  {artifact.name}\n")
        return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-set", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", default="dist/helm")
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        artifact = package(
            args.image_set,
            args.catalog,
            args.output,
            helm=args.helm,
            validate_only=args.validate_only,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(
            "Helm release validation failed: "
            + (str(error) if isinstance(error, ValueError) else type(error).__name__)
        ) from None
    print(
        str(artifact)
        if artifact
        else "Release artifact metadata validated; images were not built or executed"
    )


if __name__ == "__main__":
    main()
