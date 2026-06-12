"""Unit tests for OpenFGAConf (F013 T03).

Verifies dual-model gray release fields exist with safe defaults.
"""

from bisheng.core.config.openfga import OpenFGAConf


def test_dual_model_mode_default_false():
    conf = OpenFGAConf()
    assert conf.dual_model_mode is False


def test_legacy_model_id_default_none():
    conf = OpenFGAConf()
    assert conf.legacy_model_id is None


def test_existing_defaults_preserved():
    """T03 must not regress existing default values."""
    conf = OpenFGAConf()
    assert conf.enabled is True
    assert conf.api_url == 'http://localhost:8080'
    assert conf.store_name == 'bisheng'
    assert conf.store_id is None
    assert conf.model_id is None
    assert conf.timeout == 5


def test_dual_mode_with_legacy_accepts():
    conf = OpenFGAConf(dual_model_mode=True, legacy_model_id='abc-123')
    assert conf.dual_model_mode is True
    assert conf.legacy_model_id == 'abc-123'


def test_legacy_id_optional_even_when_dual_true():
    """Pydantic accepts dual_mode=True without legacy_id; runtime treats as no-op."""
    conf = OpenFGAConf(dual_model_mode=True)
    assert conf.dual_model_mode is True
    assert conf.legacy_model_id is None
