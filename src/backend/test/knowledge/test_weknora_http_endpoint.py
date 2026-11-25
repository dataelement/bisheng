"""The local HTTP exception applies to one explicitly trusted private endpoint only."""

import pytest
from pydantic import ValidationError

from bisheng.common.services import config_service
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, _client_parameters

ORIGIN = "http://192.168.106.243:18080"
REF = "env:BS_WEKNORA_TEST_KEY"


@pytest.fixture
def configured(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"weknora_http_endpoint: {ORIGIN}/\n", encoding="utf-8")
    monkeypatch.setattr(config_service, "settings", config_service.ConfigService.load_settings_from_yaml(str(cfg)))
    monkeypatch.setenv(REF[4:], "fixture-key")


def test_configured_http_origin(configured):
    for address in (ORIGIN, ORIGIN + "/"):
        params = _client_parameters(address, REF)
        assert params["base_url"] == ORIGIN + "/api/v1/"
        assert params["headers"] == {"X-API-Key": "fixture-key"}
        assert not params["follow_redirects"] and not params["trust_env"]


@pytest.mark.parametrize(
    "address",
    [
        ORIGIN + "/extra",
        ORIGIN + "?q=1",
        ORIGIN + "#a",
        "http://192.168.106.243:18081",
        "http://192.168.106.244:18080",
        "http://user@192.168.106.243:18080",
    ],
)
def test_other_http_endpoints_stay_denied(configured, address):
    with pytest.raises(ProviderFeatureUnavailable):
        _client_parameters(address, REF)


def test_https_default_and_credential_gate(configured, monkeypatch):
    monkeypatch.delenv(REF[4:])
    with pytest.raises(ProviderFeatureUnavailable):
        _client_parameters(ORIGIN, REF)
    monkeypatch.setenv(REF[4:], "fixture-key")
    monkeypatch.setattr(config_service, "settings", config_service.ConfigService())
    with pytest.raises(ProviderFeatureUnavailable):
        _client_parameters(ORIGIN, REF)
    assert (
        _client_parameters("https://wk.example.invalid/proxy", REF)["base_url"]
        == "https://wk.example.invalid/proxy/api/v1/"
    )


@pytest.mark.parametrize(
    "address",
    ["http://8.8.8.8:18080", "http://169.254.169.254", "http://*.internal", ORIGIN + "/api/v1", ORIGIN + ":bad"],
)
def test_configuration_rejects_ambiguous_or_non_private_origin(address):
    with pytest.raises(ValidationError):
        config_service.ConfigService(weknora_http_endpoint=address)
