"""Unit tests for the F048 single-model OpenFGA configuration."""

import pytest

from bisheng.core.config.openfga import OpenFGAConf


def test_dual_model_mode_default_false():
    conf = OpenFGAConf()
    assert conf.dual_model_mode is False


def test_legacy_model_id_default_none():
    conf = OpenFGAConf()
    assert conf.legacy_model_id is None


def test_existing_defaults_preserved():
    conf = OpenFGAConf()
    assert conf.enabled is True
    assert conf.api_url == 'http://openfga:8080'
    assert conf.store_name == 'bisheng'
    assert conf.store_id is None
    assert conf.model_id is None
    assert conf.timeout == 5


@pytest.mark.parametrize(
    "updates, message",
    (
        ({"dual_model_mode": True}, "dual-model"),
        ({"legacy_model_id": "abc-123"}, "legacy model"),
        ({"force_write_model": True}, "auto-write"),
    ),
)
def test_production_runtime_rejects_retired_model_switches(updates, message):
    conf = OpenFGAConf(
        store_id="store-1",
        model_id="model-f048",
        model_checksum="a" * 64,
        current_catalog_release_id=1,
        current_catalog_checksum="b" * 64,
        **updates,
    )
    with pytest.raises(ValueError, match=message):
        conf.validate_production_runtime_pin()
