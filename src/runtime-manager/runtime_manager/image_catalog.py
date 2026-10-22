"""Native image evidence and immutable offline release inventory (no registry credentials)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

IMAGE_NAMES = (
    "runtime-manager",
    "app-proxy",
    "runtime-helper",
    "runtime-assembler",
    "app-python",
    "app-python-preparer",
    "app-node",
    "app-node-preparer",
    "app-static",
)
SERVICE_INDEX_NAMES = ("runtime-manager", "app-proxy", "runtime-helper", "runtime-assembler")
ROLES = {
    "manager": "runtime-manager",
    "egress-proxy": "runtime-manager",
    "admission": "runtime-manager",
    "app-proxy": "app-proxy",
    "helper": "runtime-helper",
    "assembler": "runtime-assembler",
}
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
REVISION = re.compile(r"[a-f0-9]{40,64}")
RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}")


def create_inventory(metadata, *, platform, release, source_revision, published, native_arch, smoke_passed):
    if platform not in {"linux/amd64", "linux/arm64"} or native_arch != platform.split("/")[1]:
        raise ValueError("target must match the native Linux engine architecture")
    if not RELEASE.fullmatch(release) or not REVISION.fullmatch(source_revision):
        raise ValueError("invalid release or source revision")
    if set(metadata) != set(IMAGE_NAMES) or set(smoke_passed) != set(IMAGE_NAMES):
        raise ValueError("complete image and successful smoke evidence required")
    images = {}
    for name in IMAGE_NAMES:
        item = metadata[name]
        if f"{item.get('Os')}/{item.get('Architecture')}" != platform or not DIGEST.fullmatch(item.get("Id", "")):
            raise ValueError("image architecture or image ID mismatch")
        labels = item.get("Config", {}).get("Labels") or {}
        if (
            labels.get("org.opencontainers.image.revision") != source_revision
            or labels.get("org.opencontainers.image.version") != release
        ):
            raise ValueError("image source revision or release mismatch")
        tags = [value for value in item.get("RepoTags", []) if value.endswith(f":{release}-{native_arch}")]
        if len(tags) != 1 or not tags[0].rsplit(":", 1)[0].endswith("bisheng-" + name):
            raise ValueError("image release tag missing or ambiguous")
        tag = tags[0]
        repository = tag.rsplit(":", 1)[0]
        digests = {
            value
            for value in item.get("RepoDigests", [])
            if value.startswith(repository + "@") and DIGEST.fullmatch(value.split("@", 1)[1])
        }
        if published and len(digests) != 1:
            raise ValueError("published repository digest missing or ambiguous")
        tools = (
            {
                "python-abi": "3.11",
                "runtime-package": "3.0.0",
                "python-packages": "/usr/share/licenses/bisheng/python-packages.json",
            }
            if name in {"runtime-helper", "runtime-assembler"}
            else {}
        )
        if name == "runtime-assembler":
            tools.update({"crane": "v0.22.1", "go-builder": "1.27.3", "licenses": "/usr/share/licenses/crane"})
        images[name] = {
            "image": next(iter(digests)) if published else None,
            "image_id": item["Id"],
            "tag": tag,
            "platform": platform,
            "native_smoke": True,
            "tools": tools,
        }
    return {
        "schema_version": 2,
        "state": "published-native-verified" if published else "local-native-verified",
        "platform": platform,
        "release": release,
        "source_revision": source_revision,
        "native_arch": native_arch,
        "roles": ROLES,
        "images": images,
    }


def merge_inventories(inventories):
    if len(inventories) != 2 or {item.get("platform") for item in inventories} != {"linux/amd64", "linux/arm64"}:
        raise ValueError("both native platform inventories required")
    if (
        len({item.get("release") for item in inventories}) != 1
        or len({item.get("source_revision") for item in inventories}) != 1
    ):
        raise ValueError("one release and source revision required")
    release, source_revision = inventories[0].get("release", ""), inventories[0].get("source_revision", "")
    if not RELEASE.fullmatch(release) or not REVISION.fullmatch(source_revision):
        raise ValueError("invalid release or source revision")
    platforms = {}
    for item in inventories:
        if item.get("schema_version") != 2 or item.get("state") != "published-native-verified":
            raise ValueError("published native evidence required")
        arch = item["platform"].split("/")[1]
        if item.get("native_arch") != arch or set(item.get("images", {})) != set(IMAGE_NAMES):
            raise ValueError("incomplete native inventory")
        for name, image in item["images"].items():
            if not image.get("native_smoke") or image.get("platform") != item["platform"]:
                raise ValueError("image native smoke required")
            address = image.get("image") or ""
            if "@" not in address or not DIGEST.fullmatch(address.split("@", 1)[1]):
                raise ValueError("published digest required")
            if not address.split("@", 1)[0].endswith("bisheng-" + name):
                raise ValueError("image repository mismatch")
        platforms[item["platform"]] = item["images"]
    return {
        "schema_version": 2,
        "release": inventories[0]["release"],
        "source_revision": inventories[0]["source_revision"],
        "roles": ROLES,
        "platforms": platforms,
        "offline_layers": {
            "runtime_images": [
                image["image"] for platform in sorted(platforms) for image in platforms[platform].values()
            ],
            "build_dependencies": {
                "application-bundle": "Pre-supply per-profile, per-architecture wheels/npm cache and frontend build inputs; image availability alone does not supply new dependencies.",
                "source-image": "Also supply a reachable internal OCI registry, scoped registry identity, exact base images and registry endpoints. No Docker daemon is used in the assembler.",
                "service-images": "Building this release requires the Dockerfile build bases, Python build requirements and pinned Go/crane modules. These are not needed to start prebuilt service images.",
            },
            "platform_apis": [
                "backend material TLS and scoped identity",
                "backend route, authorization and policy APIs",
                "backend model/retrieval/attachment APIs requested by the application",
            ],
            "preload_requirement": "Import every target-platform image into the actual CRI and verify the exact frozen reference using the installer; docker load alone is not a CRI or dependency check.",
        },
    }


def attach_indexes(document, indexes):
    if set(indexes) != set(SERVICE_INDEX_NAMES):
        raise ValueError("all service indexes required")
    document = json.loads(json.dumps(document))
    result = {}
    for name, (digest, manifest) in indexes.items():
        if not DIGEST.fullmatch(digest):
            raise ValueError("invalid index digest")
        expected = {
            platform: images[name]["image"].split("@", 1)[1] for platform, images in document["platforms"].items()
        }
        actual = {}
        for item in manifest.get("manifests", []):
            platform = item.get("platform", {})
            key = f"{platform.get('os')}/{platform.get('architecture')}"
            if key in actual:
                raise ValueError("duplicate index platform")
            actual[key] = item.get("digest")
        if actual != expected:
            raise ValueError("index must contain exactly the verified native manifests")
        tag = document["platforms"]["linux/amd64"][name]["tag"].removesuffix("-amd64")
        result[name] = {"tag": tag, "image": tag.rsplit(":", 1)[0] + "@" + digest, "platform_digests": actual}
    document["service_indexes"] = result
    return document


def python_packages():
    import importlib.metadata
    import platform
    import ssl

    packages = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        packages.append(
            {
                "name": metadata["Name"],
                "version": distribution.version,
                "license": (metadata.get("License-Expression") or metadata.get("License") or "not-declared")[:4096],
                "license_files": sorted(
                    str(path)
                    for path in distribution.files or []
                    if any(part.lower().startswith(("license", "copying", "notice")) for part in path.parts)
                ),
            }
        )
    return {
        "python": platform.python_version(),
        "openssl": ssl.OPENSSL_VERSION,
        "packages": sorted(packages, key=lambda item: item["name"].lower()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    for name in ("metadata-dir", "platform", "release", "source-revision", "native-arch", "output"):
        inventory.add_argument("--" + name, required=True)
    inventory.add_argument("--published", action="store_true")
    merge = commands.add_parser("merge")
    merge.add_argument("--inventory", action="append", required=True)
    merge.add_argument("--output", required=True)
    indexes = commands.add_parser("indexes")
    indexes.add_argument("--release-manifest", required=True)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--release-manifest", required=True)
    finalize.add_argument("--index-dir", required=True)
    finalize.add_argument("--output", required=True)
    packages = commands.add_parser("python-packages")
    packages.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "python-packages":
        result = python_packages()
    elif args.command == "inventory":
        directory = Path(args.metadata_dir)
        metadata = {name: json.loads((directory / f"{name}.json").read_text())[0] for name in IMAGE_NAMES}
        smoke = json.loads((directory / "native-smoke.json").read_text())
        result = create_inventory(
            metadata,
            platform=args.platform,
            release=args.release,
            source_revision=args.source_revision,
            published=args.published,
            native_arch=args.native_arch,
            smoke_passed=smoke,
        )
    elif args.command == "merge":
        result = merge_inventories([json.loads(Path(path).read_text()) for path in args.inventory])
    elif args.command == "finalize":
        directory = Path(args.index_dir)
        indexes = {}
        for name in SERVICE_INDEX_NAMES:
            manifest = json.loads((directory / f"{name}-index.json").read_text())
            indexes[name] = (manifest.get("digest", ""), manifest)
        result = attach_indexes(json.loads(Path(args.release_manifest).read_text()), indexes)
    else:
        document = json.loads(Path(args.release_manifest).read_text())
        for name in SERVICE_INDEX_NAMES:
            amd = document["platforms"]["linux/amd64"][name]
            arm = document["platforms"]["linux/arm64"][name]
            index = amd["tag"].removesuffix("-amd64")
            if arm["tag"] != index + "-arm64":
                raise ValueError("service index tags do not share one repository")
            print("\t".join([name, index, amd["image"], arm["image"]]))
        return
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
