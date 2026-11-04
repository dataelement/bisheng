"""F119 AC-02, AC-03, AC-04, AC-05: input defaults never reinterpret stored versions."""

from types import SimpleNamespace

import pytest
import yaml

BASE = {"name": "example", "runtime": "python3.11", "port": 8080}


@pytest.fixture
def manifest_validator(monkeypatch):
    from bisheng.app_publish.domain.services import manifest_validator

    async def tier(_code):
        return SimpleNamespace(code="light")

    monkeypatch.setattr(manifest_validator.ResourceTierService, "resolve_tier", tier)
    return manifest_validator


async def test_new_input_defaults_to_bundle_but_stored_document_stays_legacy(manifest_validator):
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    outcome = await manifest_validator.validate_manifest(yaml.safe_dump(BASE))
    assert outcome.manifest.manifest_version == 2
    assert outcome.manifest.model_dump()["delivery"]["mode"] == "bundle"
    stored = AppManifest.model_validate(BASE)
    assert stored.manifest_version == 1
    assert stored.delivery_mode == "source-image"
    assert "delivery" not in stored.model_dump()


async def test_explicit_legacy_input_keeps_source_image(manifest_validator):
    outcome = await manifest_validator.validate_manifest(yaml.safe_dump({**BASE, "manifest_version": 1}))
    assert outcome.manifest.delivery_mode == "source-image"


@pytest.mark.parametrize("version", [None, 0, -1, 3, "unknown"])
async def test_invalid_explicit_version_is_not_a_default(manifest_validator, version):
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError):
        await manifest_validator.validate_manifest(yaml.safe_dump({**BASE, "manifest_version": version}))


@pytest.mark.parametrize("mode", ["bundle", "source-image", "image"])
async def test_explicit_v2_modes_are_preserved(manifest_validator, mode):
    declaration = {"mode": mode}
    if mode == "image":
        declaration["image"] = "example/app@sha256:" + "a" * 64
    outcome = await manifest_validator.validate_manifest(
        yaml.safe_dump({**BASE, "manifest_version": 2, "delivery": declaration})
    )
    assert outcome.manifest.delivery_mode == mode
