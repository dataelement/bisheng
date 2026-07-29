import inspect
import io
from types import SimpleNamespace

from fastapi import UploadFile
from fastapi.params import Depends

import bisheng.shougang_portal_config.api.endpoints.portal_asset as endpoint_module
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.shougang_portal_config.api.endpoints.portal_asset import (
    upload_shougang_portal_asset,
)
from bisheng.shougang_portal_config.domain.services.portal_asset_service import (
    ShougangPortalAssetService,
)


async def test_endpoint_uses_authenticated_tenant_and_returns_service_result(monkeypatch):
    captured = {}
    uploaded_file = UploadFile(file=io.BytesIO(b"image"), filename="hero.png")

    async def fake_upload(*, file, category, tenant_id):
        captured.update(file=file, category=category, tenant_id=tenant_id)
        return {
            "image_url": "https://assets.example.com/portal-assets/5/banner/id.png",
            "object_key": "portal-assets/5/banner/id.png",
        }

    monkeypatch.setattr(ShougangPortalAssetService, "upload", fake_upload)
    monkeypatch.setattr(endpoint_module, "get_current_tenant_id", lambda: None)

    response = await upload_shougang_portal_asset(
        category="banner",
        file=uploaded_file,
        admin_user=SimpleNamespace(tenant_id=5),
    )

    assert captured == {
        "file": uploaded_file,
        "category": "banner",
        "tenant_id": 5,
    }
    assert response.status_code == 200
    assert response.data["image_url"].startswith("https://assets.example.com/")


def test_endpoint_requires_admin_dependency():
    admin_parameter = inspect.signature(upload_shougang_portal_asset).parameters["admin_user"]
    dependency = admin_parameter.default.dependency

    assert isinstance(admin_parameter.default, Depends)
    assert dependency.__self__ is UserPayload
    assert dependency.__func__ is UserPayload.get_admin_user.__func__
