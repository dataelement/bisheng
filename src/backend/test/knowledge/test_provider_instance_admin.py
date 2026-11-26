"""A sealed instance key follows that instance's private origin and is not the YAML pin."""

import pytest

from bisheng.common.errcode.knowledge_space import ProviderInstanceInvalidError
from bisheng.common.services import config_service
from bisheng.core.config.settings import encrypt_token
from bisheng.knowledge.application.provider_instance_admin import normalize_connection, seal_api_key
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable, _client_parameters

ORIGIN = "http://192.168.106.243:18080"


def test_sealed_key_accepts_its_private_origin(monkeypatch):
    monkeypatch.setattr(config_service, "settings", config_service.ConfigService())
    ref = seal_api_key("fixture-key")
    params = _client_parameters(ORIGIN + "/api/v1", ref)
    assert params["base_url"] == ORIGIN + "/api/v1/"
    assert params["headers"] == {"X-API-Key": "fixture-key"}
    assert params["trust_env"] is params["follow_redirects"] is False
    assert ref.startswith("fernet:")
    assert "fixture-key" not in ref


def test_sealed_key_rejects_a_public_origin():
    ref = "fernet:" + encrypt_token("fixture-key").decode()
    with pytest.raises(ProviderFeatureUnavailable):
        _client_parameters("http://8.8.8.8:18080", ref)


def test_connection_form_rejects_a_non_numeric_workspace():
    endpoint, scope = normalize_connection(ORIGIN + "/api/v1/", "10000")
    assert (endpoint, scope) == (ORIGIN, "10000")
    with pytest.raises(ProviderInstanceInvalidError):
        normalize_connection(ORIGIN, "workspace")


def test_connection_form_accepts_optional_upload_secret_without_template_field():
    from pydantic import ValidationError

    from bisheng.knowledge.domain.schemas.provider_instance import ProviderInstanceWrite

    form = {"endpoint": ORIGIN, "remote_scope_id": "10000", "api_key": "k"}
    assert ProviderInstanceWrite(**form).model_dump() == form | {"upload_signed_token_secret": None}
    sealed = ProviderInstanceWrite(**form, upload_signed_token_secret="hmac-secret")
    assert sealed.upload_signed_token_secret == "hmac-secret"
    with pytest.raises(ValidationError):
        ProviderInstanceWrite(**form, template_kb_id="kb-1")
