import io
import json
import tarfile
import zipfile

import pytest

from bisheng.dsh_market.domain.bundle import BundleError, validate_bundle
from bisheng.dsh_market.domain.community_bundle import compare_semver


def package_archive(kind="zip", fields=None, extra=None):
    package = {"name": "community-demo", "version": "1.2.0-beta.1", "main": "index.js", **(fields or {})}
    files = {"package.json": json.dumps(package).encode(), "index.js": b"export function apply() {}", **(extra or {})}
    stream = io.BytesIO()
    if kind == "zip":
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, value in files.items():
                archive.writestr(path, value)
    else:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for path, value in files.items():
                entry = tarfile.TarInfo("package/" + path)
                entry.size = len(value)
                archive.addfile(entry, io.BytesIO(value))
    return stream.getvalue()


@pytest.mark.parametrize("kind", ["zip", "tgz"])
def test_community_package_metadata_comes_from_package_json(kind):
    manifest = validate_bundle(package_archive(kind, {"author": {"name": "Community"}, "license": "MIT"}))
    assert manifest["schema_version"] == 2
    assert manifest["plugin"]["version"] == "1.2.0-beta.1"
    assert manifest["plugin"]["publisher"] == "Community"
    assert manifest["plugin"]["desktop_min"] == ""
    assert len(manifest["targets"]) == 6


def test_platform_is_derived_from_npm_os_and_cpu():
    manifest = validate_bundle(package_archive(fields={"os": ["win32"], "cpu": ["x64"]}))
    assert set(manifest["targets"]) == {"win32-x64"}


def test_prerelease_is_lower_than_the_same_release():
    assert compare_semver("1.2.0-beta.1", "1.2.0") < 0
    assert compare_semver("1.2.1", "1.2.0-beta.9") > 0


@pytest.mark.parametrize("kind", ["zip", "tgz"])
def test_community_archive_keeps_path_validation(kind):
    with pytest.raises(BundleError, match="Unsafe"):
        validate_bundle(package_archive(kind, extra={"../escape": b"bad"}))


def test_bundle_patch_entry_comes_from_community_declaration():
    manifest = validate_bundle(
        package_archive(
            fields={"dsh": {"bundle": {"patch": "cordis.patch.yml"}}}, extra={"cordis.patch.yml": b"- insert: []"}
        )
    )
    assert manifest["plugin"]["name"] == "community-demo"
    with pytest.raises(BundleError, match="entry"):
        validate_bundle(package_archive(fields={"dsh": {"bundle": {"patch": "missing.yml"}}}))
