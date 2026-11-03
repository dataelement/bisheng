"""The new default is bundle; old manifests never silently change delivery mode."""

import pytest
from pydantic import ValidationError


def base(version):
    return {"manifest_version": version, "name": "example", "runtime": "python3.11", "port": 8080}


def test_v2_source_defaults_to_bundle():
    """AC-11: the platform default does not construct a new OCI image per change."""
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    manifest = AppManifest.model_validate(base(2))
    assert manifest.delivery_mode == "bundle"
    assert manifest.model_dump()["delivery"]["mode"] == "bundle"


def test_v1_is_legacy_and_dump_does_not_add_delivery():
    """AC-13, AC-60: existing v1 public manifest shape stays readable by old consumers."""
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    manifest = AppManifest.model_validate(base(1))
    assert manifest.delivery_mode == "source-image"
    assert "delivery" not in manifest.model_dump()
    with pytest.raises(ValidationError):
        AppManifest.model_validate({**base(1), "delivery": {"mode": "bundle"}})


def test_full_image_uses_runtime_contract_not_source_template():
    """AC-12, AC-17: an immutable image can contain a different application language."""
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest
    from bisheng.app_publish.domain.services.manifest_validator import _check_runtime

    manifest = AppManifest.model_validate(
        {**base(2), "runtime": "custom-image", "delivery": {"mode": "image", "image": "example/app@sha256:" + "a" * 64}}
    )
    _check_runtime(manifest)
    assert manifest.delivery_mode == "image"
    with pytest.raises(ValidationError):
        AppManifest.model_validate({**base(2), "delivery": {"mode": "image", "image": "example/app:latest"}})


@pytest.mark.parametrize(
    "delivery",
    [
        {"mode": "invalid"},
        {"mode": "bundle", "startup": {"command": []}},
        {"mode": "bundle", "dependencies": {"lock": "../escape"}},
        {"mode": "bundle", "unexpected": "x"},
    ],
)
def test_invalid_delivery_is_refused(delivery):
    """AC-07, AC-13, AC-17: ambiguous or escaping runtime inputs are rejected."""
    from bisheng.app_publish.domain.schemas.app_manifest import AppManifest

    with pytest.raises(ValidationError):
        AppManifest.model_validate({**base(2), "delivery": delivery})
