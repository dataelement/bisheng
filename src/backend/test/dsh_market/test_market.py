import base64
import hashlib
import io
import json
import stat
import time
import zipfile
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.dsh_market.api.auth import MarketActor, market_actor, market_admin
from bisheng.dsh_market.api.endpoints import router
from bisheng.dsh_market.domain.bundle import BundleError, validate_bundle
from bisheng.dsh_market.domain.lease import sign_policy
from bisheng.dsh_market.domain.models import MarketVersion
from bisheng.dsh_market.domain.repository import ConflictError, MarketRepository
from bisheng.dsh_market.domain.service import MarketService
from bisheng.dsh_market.infrastructure import get_market_service


def bundle(version="1.0.0", dependencies=None, extra=None):
    package = {
        "name": "company-demo",
        "version": version,
        "type": "module",
        "main": "index.js",
        "dependencies": dependencies or {},
    }
    contents = {
        "node_modules/company-demo/package.json": json.dumps(package).encode(),
        "node_modules/company-demo/index.js": b"export function apply(ctx) { return undefined }",
    }
    manifest = {
        "schema_version": 1,
        "plugin": {
            "name": "company-demo",
            "version": version,
            "display_name": "Company Demo",
            "description": "Internal reporting",
            "publisher": "Company",
            "license": "MIT",
            "desktop_min": "0.1.1",
            "permissions": [],
            "services": [],
            "changelog": "First release",
        },
        "targets": {"darwin-arm64": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}},
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in contents.items():
            archive.writestr("bundles/darwin-arm64/" + name, data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return stream.getvalue()


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, tenant, digest, data):
        self.objects[tenant, digest] = data

    def get(self, tenant, digest):
        return self.objects[tenant, digest]


@pytest.fixture
def service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(
        engine, tables=[table for name, table in SQLModel.metadata.tables.items() if name.startswith("dsh_market_")]
    )

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    return MarketService(MarketRepository(sessions), MemoryStorage())


def published(service, tenant=2, version="1.0.0"):
    job = service.import_bundle(tenant, 20, bundle(version))
    plugin = service.repository.list(tenant)["data"][0]
    assert job["status"] == "completed"
    assert plugin["current_version_id"] == job["version_id"]
    return plugin


def test_offline_bundle_and_dependency_closure():
    assert validate_bundle(bundle())["plugin"]["name"] == "company-demo"
    with pytest.raises(BundleError, match="Missing bundled dependency"):
        validate_bundle(bundle(dependencies={"left-pad": "1.3.0"}))


def test_market_tables_are_discovered_by_online_schema_bootstrap():
    assert "bisheng.dsh_market.domain.models" in discover_sqlmodel_module_names()


def test_large_manifest_catalog_keeps_order_and_current_employee_version(service):
    plugin = published(service, version="1.0.0")
    latest = service.import_bundle(2, 20, bundle(version="1.1.0"))
    with service.repository.sessions() as db:
        versions = db.exec(select(MarketVersion)).all()
        expected = [v.id for v in sorted(versions, key=lambda v: (-v.created_at.timestamp(), v.id))]
        for version in versions:
            version.manifest = {
                **version.manifest,
                "targets": {"darwin-arm64": {f"node_modules/dep/file-{i}.js": "a" * 64 for i in range(14000)}},
            }
            db.add(version)
        db.commit()
        engine = db.get_bind()

    def require_scalar_sort(_conn, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower()
        if "dsh_market_version" in sql and "order by" in sql:
            assert "dsh_market_version.manifest" not in sql, "Large JSON manifests exceed MySQL sort memory"

    event.listen(engine, "before_cursor_execute", require_scalar_sort)
    try:
        admin = service.repository.get(2, plugin["id"])
        assert [v["id"] for v in admin["versions"]] == expected
        employee = service.list_plugins(2, employee=True)["data"][0]
        assert [v["id"] for v in employee["versions"]] == [latest["version_id"]]
        assert employee["versions"][0]["manifest"]["targets"] == {"darwin-arm64": {}}
        assert service.repository.get(3, plugin["id"]) is None
    finally:
        event.remove(engine, "before_cursor_execute", require_scalar_sort)


@pytest.mark.parametrize(
    "path", ["../escape", "/escape", "bundles/darwin-arm64/../escape", "C:/escape", "foo\\bar", "extra.txt"]
)
def test_rejects_unsafe_or_unlisted_files(path):
    with pytest.raises(BundleError):
        validate_bundle(bundle(extra={path: b"bad"}))


def test_rejects_symlinks():
    stream = io.BytesIO(bundle())
    with zipfile.ZipFile(stream, "a") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(BundleError):
        validate_bundle(stream.getvalue())


def test_idempotent_import_and_immutable_version(service):
    data = bundle()
    first = service.import_bundle(2, 20, data)
    assert service.import_bundle(2, 20, data)["id"] == first["id"]
    modified = data + b"different container bytes"
    other = service.import_bundle(2, 20, modified)
    assert other["status"] == "failed"
    assert service.repository.list(2)["total"] == 1
    assert len(service.repository.list(2)["data"][0]["versions"]) == 1


def test_tenant_isolation_on_list_detail_download_and_mutation(service):
    plugin = published(service)
    assert service.repository.list(3)["total"] == 0
    assert service.repository.get(3, plugin["id"]) is None
    assert service.repository.audits(3, plugin["id"]) == []
    with pytest.raises(LookupError):
        service.download(3, plugin["id"], plugin["current_version_id"])
    with pytest.raises(LookupError):
        service.change(3, 30, plugin["id"], plugin["revision"], "disable")


def test_new_import_publishes_atomically_and_stale_changes_fail(service):
    plugin = published(service)
    old = plugin["current_version_id"]
    job = service.import_bundle(2, 20, bundle("1.1.0"))
    current = service.repository.get(2, plugin["id"])
    with pytest.raises(ConflictError):
        service.change(2, 20, plugin["id"], plugin["revision"], "publish", job["version_id"])
    assert current["current_version_id"] == job["version_id"]
    assert current["current_version_id"] != old
    new_version = next(v for v in current["versions"] if v["id"] == job["version_id"])
    service.storage.objects[2, new_version["digest"]] = b"corrupt"
    with pytest.raises(BundleError):
        service.change(2, 20, plugin["id"], current["revision"], "publish", job["version_id"])
    assert service.repository.get(2, plugin["id"])["current_version_id"] == job["version_id"]


def test_unpublish_usage_and_plugin_wide_disable(service):
    plugin = published(service)
    version = plugin["current_version_id"]
    plugin = service.change(2, 20, plugin["id"], plugin["revision"], "unpublish")
    assert service.repository.list(2, employee=True)["total"] == 0
    assert not service.repository.policies(2)[0]["disabled"]
    assert service.repository.policies(2)[0]["versions"][0]["id"] == version
    with pytest.raises(LookupError):
        service.download(2, plugin["id"], version)
    plugin = service.change(2, 20, plugin["id"], plugin["revision"], "disable")
    assert service.repository.policies(2)[0]["disabled"]
    plugin = service.change(2, 20, plugin["id"], plugin["revision"], "publish", version)
    assert not plugin["disabled"]
    assert len(service.download(2, plugin["id"], version)[0]) > 0


def test_search_and_publication_status(service):
    published(service)
    service.import_bundle(2, 20, bundle("1.1.0"))
    assert service.repository.list(2, "company", status="published")["total"] == 1
    assert service.repository.list(2, status="unpublished")["total"] == 0
    assert service.repository.list(2, "REPORTING", employee=True)["total"] == 1
    assert service.repository.list(2, "%")["total"] == 0


def test_recover_persisted_validation_task(service):
    data = bundle()
    digest = hashlib.sha256(data).hexdigest()
    service.storage.put(2, digest, data)
    task = service.repository.create_import(2, 20, digest)
    replacement_worker = MarketService(service.repository, service.storage)
    assert replacement_worker.validate_import(2, task["id"])["status"] == "completed"
    plugin = service.repository.list(2, employee=True)["data"][0]
    assert replacement_worker.validate_import(2, task["id"])["status"] == "completed"
    assert service.repository.get(2, plugin["id"])["revision"] == plugin["revision"]


def test_api_contract_and_admin_boundary(service):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    app.dependency_overrides[get_market_service] = lambda: service
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    client = TestClient(app)
    assert client.get("/api/v1/dsh/market/admin/plugins").json()["status_code"] == 26204
    app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)
    result = client.post(
        "/api/v1/dsh/market/admin/imports", files={"file": ("plugin.zip", bundle(), "application/zip")}
    )
    assert result.json()["data"]["status"] == "completed"
    assert client.get("/api/v1/dsh/market/catalog").json()["data"]["total"] == 1
    row = client.get("/api/v1/dsh/market/admin/plugins").json()["data"]["data"][0]
    response = client.get(f"/api/v1/dsh/market/plugins/{row['id']}/versions/{row['current_version_id']}/artifact")
    assert response.headers["content-type"] == "application/zip"
    assert hashlib.sha256(response.content).hexdigest() == row["versions"][0]["digest"]
    app.dependency_overrides[market_actor] = lambda: MarketActor(3, 30)
    assert client.get("/api/v1/dsh/market/catalog").json()["data"]["total"] == 0


def test_reimport_restores_legacy_unpublished_and_preserves_present_version(service):
    plugin = published(service)
    service.change(2, 20, plugin["id"], plugin["revision"], "unpublish")
    service.import_bundle(2, 20, bundle())
    assert service.repository.get(2, plugin["id"])["current_version_id"] == plugin["current_version_id"]
    newer = published(service, version="1.1.0")
    service.import_bundle(2, 20, bundle())
    assert service.repository.get(2, plugin["id"])["current_version_id"] == newer["current_version_id"]


def test_invalid_update_preserves_published_version_and_import_records_distribution(service):
    plugin = published(service)
    result = service.import_bundle(2, 20, bundle("1.1.0", dependencies={"missing-lib": "1.0.0"}))
    assert result["status"] == "failed"
    assert service.repository.get(2, plugin["id"]) == plugin
    audit = service.repository.audits(2, plugin["id"])[0]
    assert audit["action"] == "import"
    assert audit["before"]["current_version_id"] is None
    assert audit["after"]["current_version_id"] == plugin["current_version_id"]
    assert "audit" not in service.detail(2, plugin["id"])


def test_legacy_disabled_plugins_use_unpublished_state_and_remain_revoked(service):
    plugin = published(service)
    off = service.change(2, 20, plugin["id"], plugin["revision"], "disable")
    assert off["status"] == "unpublished"
    assert service.repository.list(2, status="unpublished")["total"] == 1
    assert service.repository.policies(2)[0]["disabled"]


def test_policy_is_signed_by_deployment_key(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    monkeypatch.setenv("BISHENG_DSH_MARKET_SIGNING_KEY", pem)
    payload = {"tenant_id": "2", "user_id": "20", "expires_at": int(time.time()) + 3600}
    receipt = sign_policy(payload)

    def decode(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/dsh/market/capabilities").json()["data"]
        assert capabilities["enabled"] and capabilities["tenant_id"] == "2"
        assert "PRIVATE" not in capabilities["public_key"]
        advertised_key = load_pem_public_key(capabilities["public_key"].encode())
        advertised_key.verify(decode(receipt["signature"]), decode(receipt["payload"]))
        monkeypatch.delenv("BISHENG_DSH_MARKET_SIGNING_KEY")
        capabilities = client.get("/api/v1/dsh/market/capabilities").json()["data"]
        assert capabilities["enabled"] is False and capabilities["public_key"] is None
    assert json.loads(decode(receipt["payload"])) == payload


def test_admin_scope_requires_role_and_active_tenant(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from starlette.requests import Request

    from bisheng.common import permission_identity
    from bisheng.common.errcode.dsh_market import MarketPermissionError
    from bisheng.dsh_market import infrastructure

    active = AsyncMock(return_value=True)
    checker = AsyncMock(return_value=True)
    monkeypatch.setattr(infrastructure, "tenant_is_active", active)
    monkeypatch.setattr(permission_identity, "check_tenant_admin", checker)
    request = Request({"type": "http", "headers": [(b"x-dsh-market-tenant", b"3")]})
    with pytest.raises(MarketPermissionError):
        asyncio.run(market_admin(request, MarketActor(2, 20)))
    active.assert_not_called()
    with pytest.raises(MarketPermissionError):
        asyncio.run(market_admin(request, MarketActor(1, 10, True)))
    from bisheng.core.context.tenant import (
        get_is_management_api,
        get_visible_tenant_ids,
        set_admin_scope_tenant_id,
        set_is_management_api,
    )

    async def own_tenant():
        set_admin_scope_tenant_id(3)
        set_is_management_api(True)
        own = Request({"type": "http", "headers": []})
        own.state.market_management_tenant = 3
        result = await market_admin(own, MarketActor(1, 10, True))
        assert not get_is_management_api()
        assert get_visible_tenant_ids() == frozenset({1})
        return result

    assert asyncio.run(own_tenant()).tenant_id == 1
    active.assert_awaited_once_with(1)
    active.return_value = False
    with pytest.raises(MarketPermissionError):
        asyncio.run(own_tenant())


def test_market_transition_audit_records_old_and_new_distribution(service):
    plugin = published(service)
    service.change(2, 20, plugin["id"], plugin["revision"], "disable")
    audit = service.repository.audits(2, plugin["id"])[0]
    assert audit["before"] == {"current_version_id": plugin["current_version_id"], "disabled": False, "deleted": False}
    assert audit["after"] == {"current_version_id": None, "disabled": True, "deleted": False}
    assert audit["result"] == "succeeded"


def test_delete_hides_catalog_detail_and_download_but_retains_installed_policy(service):
    plugin = published(service)
    version = plugin["current_version_id"]
    service.change(2, 20, plugin["id"], plugin["revision"], "delete")
    assert service.list_plugins(2)["total"] == 0
    assert service.list_plugins(2, employee=True)["total"] == 0
    with pytest.raises(LookupError):
        service.detail(2, plugin["id"])
    with pytest.raises(LookupError):
        service.download(2, plugin["id"], version)
    with pytest.raises(LookupError):
        service.change(2, 20, plugin["id"], plugin["revision"] + 1, "publish", version)
    policy = service.repository.policies(2)[0]
    assert policy["current_version_id"] is None
    assert not policy["disabled"]
    assert policy["versions"][0]["id"] == version
    assert service.repository.audits(2, plugin["id"])[0]["action"] == "delete"


def test_delete_requires_current_revision_and_own_tenant(service):
    plugin = published(service)
    with pytest.raises(LookupError):
        service.change(3, 30, plugin["id"], plugin["revision"], "delete")
    with pytest.raises(ConflictError):
        service.change(2, 20, plugin["id"], plugin["revision"] - 1, "delete")
    assert service.detail(2, plugin["id"])["current_version_id"] == plugin["current_version_id"]


def test_deleted_plugin_can_be_reimported_with_same_bundle_or_new_version(service):
    data = bundle()
    first = service.import_bundle(2, 20, data)
    plugin = service.list_plugins(2)["data"][0]
    service.change(2, 20, plugin["id"], plugin["revision"], "delete")
    assert service.import_bundle(2, 21, data)["status"] == "completed"
    restored = service.detail(2, plugin["id"])
    assert restored["current_version_id"] == first["version_id"]
    assert len(restored["versions"]) == 1
    service.change(2, 20, plugin["id"], restored["revision"], "delete")
    invalid = service.import_bundle(2, 20, bundle("1.1.0", dependencies={"missing": "1.0.0"}))
    assert invalid["status"] == "failed"
    assert service.list_plugins(2)["total"] == 0
    new = service.import_bundle(2, 20, bundle("1.1.0"))
    assert service.detail(2, plugin["id"])["current_version_id"] == new["version_id"]


def test_delete_api_and_download_race(service):
    plugin = published(service)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_market_service] = lambda: service
    app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)
    client = TestClient(app)
    result = client.delete(f"/api/v1/dsh/market/admin/plugins/{plugin['id']}", params={"revision": plugin["revision"]})
    assert result.json()["data"] == {"id": plugin["id"], "deleted": True}
    assert client.get("/api/v1/dsh/market/admin/plugins").json()["data"]["total"] == 0
    restored = published(service)
    get = service.storage.get

    def delete_during_read(tenant, digest):
        data = get(tenant, digest)
        service.change(tenant, 20, restored["id"], restored["revision"], "delete")
        return data

    service.storage.get = delete_during_read
    with pytest.raises(ConflictError):
        service.download(2, restored["id"], restored["current_version_id"])


def test_deleted_column_migration_upgrades_old_rows_and_replays():
    import runpy
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_f064_enterprise_market.py")
    )
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE dsh_market_plugin (id VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO dsh_market_plugin (id) VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            migration["upgrade"]()
        assert connection.execute(text("SELECT id, deleted FROM dsh_market_plugin")).one() == ("existing", 0)
