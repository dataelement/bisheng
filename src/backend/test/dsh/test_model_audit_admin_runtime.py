"""AC-18/AC-19/AC-29: real composition reuses administrator authority and shared adapters."""

import base64

import pytest

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.dsh.config import DshSettings
from bisheng.dsh.infrastructure.model_audit_storage import BishengMinioAuditObjects
from test.dsh.test_model_audit_flow import fixture


async def test_administration_factory_reuses_scope_authority_and_shared_storage(monkeypatch):
    import bisheng.dsh.audit_admin_runtime as composition

    async with fixture() as (harness, _client, _objects):
        monkeypatch.setattr(composition, "authorize_admin", harness.authorize)
        monkeypatch.setattr(composition, "repository_scope", harness.scope)
        monkeypatch.setenv("BS_DSH_MODEL_AUDIT_KEYS", '{"fixture":"' + base64.b64encode(bytes(32)).decode() + '"}')
        admin = composition.build_audit_administration(DshSettings(audit_active_key_id="fixture"))
        assert (await admin.modes.read_admin(2, 2)).mode == "CONTENT"
        assert (await admin.queries.page(2, 2))["items"] == []
        with pytest.raises(PermissionDeniedError):
            await admin.modes.change_admin(2, 2, None)
        assert admin.queries.authorize_admin == admin.modes.authorize_admin == harness.authorize
        assert admin.bodies.queries is admin.queries
        assert isinstance(admin.bodies.storage_factory().objects, BishengMinioAuditObjects)
