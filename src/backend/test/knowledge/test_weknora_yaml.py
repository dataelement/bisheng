"""Read real YAML without contacting a server, registering a tenant or using live secrets."""

import json

import pytest
from pydantic import ValidationError

from bisheng.common.services import config_service
from bisheng.knowledge.application.provider_provision_runtime import _deployment
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, _client_parameters


@pytest.fixture
def load(tmp_path, monkeypatch):
    def apply(**fields):
        cfg = {
            "tenant_id": 31,
            "instance_id": 4,
            "remote_scope_id": "7",
            "endpoint": "http://192.168.106.243:18080/api/v1/",
            "api_key": "fixture-secret",
            **fields,
        }
        path = tmp_path / "config.yaml"
        path.write_text(json.dumps({"weknora": cfg}))
        settings = config_service.ConfigService.load_settings_from_yaml(str(path))
        monkeypatch.setattr(config_service, "settings", settings)
        return settings

    return apply


def params(tenant=31, instance=4, scope="7"):
    return _client_parameters(
        "https://registered.example.invalid",
        "env:BS_WEKNORA_FIXTURE",
        tenant_id=tenant,
        instance_id=instance,
        scope=scope,
    )


def test_yaml_profile_supplies_transport_and_redacts_key(load, monkeypatch):
    settings = load(timeout_seconds=42, connect_timeout_seconds=8)
    monkeypatch.delenv("BS_WEKNORA_FIXTURE", raising=False)
    result = params()
    assert result["base_url"] == "http://192.168.106.243:18080/api/v1/"
    assert result["headers"]["X-API-Key"] == "fixture-secret"
    assert (result["timeout"].read, result["timeout"].connect) == (42, 8)
    assert result["trust_env"] is result["follow_redirects"] is False
    assert "fixture-secret" not in str(settings.weknora)
    assert "weknora" not in settings.model_dump()


def test_yaml_key_never_used_by_another_binding(load, monkeypatch):
    load()
    monkeypatch.setenv("BS_WEKNORA_FIXTURE", "old-instance-key")
    for args in [(31, 3), (32, 4)]:
        result = params(*args)
        assert result["headers"]["X-API-Key"] == "old-instance-key"
        assert result["base_url"] == "https://registered.example.invalid/api/v1/"
    with pytest.raises(ProviderFeatureUnavailable):
        params(scope="8")
    load(api_key="")
    with pytest.raises(ProviderFeatureUnavailable):
        params()


@pytest.mark.parametrize(
    "invalid",
    [
        {"tenant_id": None},
        {"endpoint": "http://8.8.8.8/api/v1"},
        {"endpoint": "http://192.168.106.243:18080/a/../api/v1"},
        {"endpoint": "https://user@wk.invalid/api/v1"},
    ],
)
def test_deny_invalid_yaml_profile(load, invalid):
    with pytest.raises(ValidationError):
        load(**invalid)


def test_yaml_provisioning_uses_verified_preset_shape(load, monkeypatch):
    doc = {
        "preset": {
            "tenant_id": 31,
            "instance_id": 4,
            "scope": "7",
            "revision": 1,
            "summary": "s",
            "embedding": "e",
            "vision": "v",
            "chunk_size": 400,
            "overlap": 20,
        },
        "template_id": "tpl",
        "extract_digest": "a" * 64,
    }
    load(deployment=doc)
    monkeypatch.delenv("BS_WEKNORA_PRESET_31", raising=False)
    assert _deployment(31)[1] == doc
    load(deployment={**doc, "preset": {**doc["preset"], "instance_id": 9}})
    with pytest.raises(ValueError):
        _deployment(31)
