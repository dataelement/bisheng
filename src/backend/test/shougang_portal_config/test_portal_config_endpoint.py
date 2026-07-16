from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bisheng.shougang_portal_config.api.endpoints.portal_config import (
    save_shougang_portal_config,
)
from bisheng.shougang_portal_config.domain.services.department_business_domain_service import (
    DepartmentBusinessDomainValidationError,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


@pytest.mark.asyncio
async def test_missing_department_is_mapped_to_http_422(monkeypatch):
    async def reject(*_args, **_kwargs):
        raise DepartmentBusinessDomainValidationError("missing department")

    monkeypatch.setattr(ShougangPortalConfigService, "save_config", reject)
    payload = SimpleNamespace()
    admin = SimpleNamespace(tenant_id=1, user_id=8)

    with pytest.raises(HTTPException) as exc_info:
        await save_shougang_portal_config(payload, admin)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "missing department"
