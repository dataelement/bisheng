from types import SimpleNamespace

import pytest

import bisheng.shougang_portal_config.api.endpoints.portal_config as endpoint_module
from bisheng.shougang_portal_config.api.endpoints.portal_config import (
    save_shougang_portal_config,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


@pytest.mark.asyncio
async def test_save_endpoint_delegates_complete_domain_config_and_returns_redacted_result(monkeypatch):
    payload = SimpleNamespace(portal=SimpleNamespace(domains=[SimpleNamespace(department_ids=[10])]))
    admin = SimpleNamespace(tenant_id=5, user_id=8)
    saved = SimpleNamespace(version=12)
    captured = {}

    async def save_config(received_payload, **kwargs):
        captured["payload"] = received_payload
        captured.update(kwargs)
        return saved

    monkeypatch.setattr(ShougangPortalConfigService, "save_config", save_config)
    monkeypatch.setattr(endpoint_module, "get_current_tenant_id", lambda: None)
    monkeypatch.setattr(
        endpoint_module,
        "redact_portal_admin_config",
        lambda config: {"version": config.version},
    )

    response = await save_shougang_portal_config(payload, admin)

    assert captured == {
        "payload": payload,
        "tenant_id": 5,
        "create_user": 8,
    }
    assert response.status_code == 200
    assert response.data == {"version": 12}
