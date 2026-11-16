"""F133 durable audit intent, fail closed before writes, no secret capture."""

import importlib
from types import SimpleNamespace

import pytest


def module():
    name = "bisheng.open_api.application.kunlian_audit"
    assert importlib.util.find_spec(name) is not None, "Kunlian audit port missing"
    return importlib.import_module(name)


class Store:
    def __init__(self):
        self.rows = {}
        self.fail_begin = self.fail_finish = False

    async def begin(self, values):
        if self.fail_begin:
            raise RuntimeError("secret driver message")
        self.rows["audit"] = values
        return "audit"

    async def finish(self, audit_id, http_status):
        if self.fail_finish:
            raise RuntimeError("secret driver message")
        self.rows[audit_id]["audit_metadata"] |= {"state": "FINISHED", "http_status": http_status}


async def test_audit_allowlist_and_failure_semantics():
    api = module()
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    store = Store()
    service = api.KunlianAuditService(store)
    access = SimpleNamespace(
        credential=SimpleNamespace(credential_id=3, integration_id="integration", secret="hidden"),
        user=SimpleNamespace(user_id=11, tenant_id=7, password="hidden"),
        external_tenant_id="external",
        external_user_id="external-user",
        headers={"Authorization": "hidden"},
        body="hidden",
    )
    audit_id = await service.begin(access, "POST", "/api/v2/kunlian/workflows/{workflow_id}", "target", "trace")
    row = store.rows[audit_id]
    assert row["audit_metadata"] == {
        "credential_id": 3,
        "integration_id": "integration",
        "external_tenant_id": "external",
        "tenant_id": 7,
        "user_id": 11,
        "method": "POST",
        "route": "/api/v2/kunlian/workflows/{workflow_id}",
        "target_id": "target",
        "trace_id": "trace",
        "state": "INTENT",
    }
    assert "hidden" not in repr(row)
    store.fail_finish = True
    assert await service.finish(audit_id, 200) is False
    assert row["audit_metadata"]["state"] == "INTENT"
    store.fail_finish = False
    assert await service.finish(audit_id, 200) is True
    assert row["audit_metadata"]["http_status"] == 200
    store.fail_begin = True
    with pytest.raises(KunlianAccessError, match="UNAVAILABLE"):
        await service.begin(access, "POST", "/route", None, "trace")
    with pytest.raises(KunlianAccessError, match="INVALID_INPUT"):
        await service.begin(access, "POST", "/route?api_key=hidden", None, "trace")


async def test_control_audit_is_platform_scoped_and_runs_after_fresh_admin(monkeypatch):
    from starlette.requests import Request

    from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError
    from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
    from bisheng.open_api.api.endpoints import kunlian_credentials as endpoint
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    store = Store()
    service = module().KunlianAuditService(store)
    user = SimpleNamespace(user_id=42, tenant_id=99, secret="hidden")
    with tenant_execution_scope(99):
        audit_id = await service.begin_control(
            user, "POST", "/identity-integrations/kunlian/api-keys/{key_id}/rotate", "3", "trace"
        )
        assert get_current_tenant_id() == 99
    row = store.rows[audit_id]
    assert row["tenant_id"] == 1 and row["operator_id"] == 42
    assert row["target_type"] == "kunlian_credential"
    assert row["audit_metadata"]["control_plane"] is True
    assert "hidden" not in repr(row)
    store.fail_begin = True
    with pytest.raises(KunlianAccessError, match="UNAVAILABLE"):
        await service.begin_control(user, "POST", "/route", None, "trace")
    store.fail_begin = False
    from bisheng.user.application import external_identity

    async def fresh(self, user_id):
        assert get_current_tenant_id() == 1
        raise KunlianIdentityUnavailableError()

    monkeypatch.setattr(external_identity.KunlianExternalIdentityApplication, "require_current_global_super", fresh)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/route",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(kunlian_audit_service=service)),
            "route": SimpleNamespace(path="/route"),
            "path_params": {},
        }
    )
    before = repr(store.rows)
    with pytest.raises(KunlianIdentityUnavailableError):
        await endpoint.get_kunlian_key_admin(user=user, request=request)
    assert repr(store.rows) == before

    async def allowed(self, user_id):
        assert get_current_tenant_id() == 1

    monkeypatch.setattr(external_identity.KunlianExternalIdentityApplication, "require_current_global_super", allowed)
    assert await endpoint.get_kunlian_key_admin(user=user, request=request) is user
    assert request.state.kunlian_audit_id == "audit"
    assert request.state.kunlian_audit_service is service


async def test_repository_commits_intent_before_completion(open_api_db, monkeypatch):
    api = module()
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.domain.repositories import kunlian_audit as repo

    async with open_api_db() as session:
        await session.run_sync(lambda sync: AuditLog.__table__.create(sync.connection()))
    monkeypatch.setattr(repo, "get_async_db_session", open_api_db)
    service = api.KunlianAuditService()
    access = SimpleNamespace(
        credential=SimpleNamespace(credential_id=3, integration_id="integration"),
        user=SimpleNamespace(user_id=11, tenant_id=1),
        external_tenant_id="ext",
    )
    audit_id = await service.begin(access, "POST", "/route", "target", "trace")
    async with open_api_db() as session:
        assert (await session.get(AuditLog, audit_id)).audit_metadata["state"] == "INTENT"
    assert await service.finish(audit_id, 409)
    async with open_api_db() as session:
        row = await session.get(AuditLog, audit_id)
        assert row.audit_metadata["http_status"] == 409
        assert row.audit_metadata["state"] == "FINISHED"
