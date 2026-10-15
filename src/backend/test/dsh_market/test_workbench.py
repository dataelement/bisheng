"""Workbench archive validation and tenant-scoped distribution contracts."""

import hashlib
import io
import json
import tarfile
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.dsh_market.api.auth import MarketActor, market_actor, market_admin
from bisheng.dsh_market.api.endpoints import router
from bisheng.dsh_market.domain.workbench_bundle import (
    WorkbenchBundleError,
    compare_semver,
    validate_workbench_bundle,
)
from bisheng.dsh_market.domain.workbench_repository import WorkbenchRepository
from bisheng.dsh_market.domain.workbench_service import WorkbenchService
from bisheng.dsh_market.infrastructure import get_workbench_service
from bisheng.utils.http_middleware import owns_dsh_credential


def archive(version="0.12.6", repository=True, extra=None, patch_path="cordis.patch.yml", explicit_root=False):
    package = {
        "name": "dsh-example-workbench",
        "version": version,
        "description": "Example workbench",
        "main": "./desktop.js",
        "exports": {".": "./desktop.js", "./client": "./client.js"},
        "dsh": {
            "bundle": {"patch": "./" + patch_path},
            "client": {"platform": "web", "inject": ["dsh-desktop-workbenches"]},
        },
    }
    if repository:
        package["repository"] = "git+https://github.com/example/dsh-example-workbench.git"
    files = {
        "package/package.json": json.dumps(package).encode(),
        "package/desktop.js": b"export const apply = () => null",
        "package/client.js": b"export const client = true",
        "package/" + patch_path: b"- insert:\n    - id: example-workbench\n      name: dsh-example-workbench\n",
    }
    if not repository:
        files["package/workbench.json"] = json.dumps(
            {"id": "example", "title": "Example", "version": version, "entry": "./client.js"}
        ).encode()
    files.update(extra or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        if explicit_root:
            root = tarfile.TarInfo("package/")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
        for path, data in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return stream.getvalue()


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, tenant, digest, data):
        self.objects[tenant, digest] = data

    def get(self, tenant, digest):
        return self.objects.get((tenant, digest))


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

    return WorkbenchService(WorkbenchRepository(sessions), MemoryStorage())


def test_standard_legacy_and_semver():
    standard = validate_workbench_bundle(archive())
    assert standard["identity_kind"] == "repository"
    assert standard["workbench_key"] == "example/dsh-example-workbench"
    legacy = validate_workbench_bundle(archive("0.3.0-desktop.1", repository=False))
    assert legacy["identity_kind"] == "legacy"
    assert legacy["workbench_key"] is None
    assert legacy["legacy_id"] == "example"
    assert compare_semver("1.0.0", "1.0.0-rc.1") > 0
    assert compare_semver("1.0.0-rc.10", "1.0.0-rc.2") > 0


def test_nested_patch_and_explicit_package_root():
    result = validate_workbench_bundle(archive(patch_path="patches/workbench.yaml", explicit_root=True))
    assert result["package_metadata"]["bundle_patch"] == "patches/workbench.yaml"


@pytest.mark.parametrize(
    "extra,rule",
    [
        ({"package/../outside": b"bad"}, "WB-03"),
        ({"package/.env": b"secret"}, "WB-04"),
        ({"package/secrets/token.txt": b"secret"}, "WB-04"),
        ({"package/DESKTOP.js": b"collision"}, "WB-03"),
        ({"package/unsafe:name": b"bad"}, "WB-03"),
        ({"package/unsafe\x7fname": b"bad"}, "WB-03"),
    ],
)
def test_rejects_unsafe_archives(extra, rule):
    with pytest.raises(WorkbenchBundleError, match=rule):
        validate_workbench_bundle(archive(extra=extra))


def test_rejects_symlink():
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        info = tarfile.TarInfo("package/desktop.js")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../etc/passwd"
        tar.addfile(info)
    with pytest.raises(WorkbenchBundleError, match="WB-03"):
        validate_workbench_bundle(stream.getvalue())


def test_import_idempotence_versions_and_tenant_scope(service):
    first = archive("1.0.0-rc.1")
    preview = service.preview(2, first)
    assert preview["allowed"] and preview["current_version"] is None
    task = service.import_bundle(2, 20, first)
    assert task["status"] == "completed"
    assert service.import_bundle(2, 20, first)["id"] == task["id"]
    row = service.list(2)["data"][0]
    assert service.list(3)["total"] == 0
    assert service.repository.get(3, row["id"]) is None
    assert service.preview(2, archive("0.9.0"))["reason"] == "lower_version"
    assert service.import_bundle(2, 20, archive("1.0.0"))["status"] == "completed"
    assert service.preview(2, archive("1.0.0+other"))["reason"] == "version_conflict"
    latest = service.detail(2, row["id"])
    assert latest["current_version"]["version"] == "1.0.0"
    with pytest.raises(LookupError):
        service.download(2, row["id"], task["version_id"])


def test_interrupted_import_resumes_from_stored_archive(service):
    data = archive()
    digest = hashlib.sha256(data).hexdigest()
    service.storage.put(2, digest, data)
    task = service.repository.create_import(2, 20, digest, "Custom workbench")
    resumed = service.resume(2, task["id"])
    assert resumed["status"] == "completed"
    assert service.list(2)["data"][0]["display_name"] == "Custom workbench"


def test_artifact_integrity_and_api_contract(service):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    app.dependency_overrides[get_workbench_service] = lambda: service
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    client = TestClient(app)
    assert client.get("/api/v1/dsh/market/admin/workbenches").json()["status_code"] == 26204
    app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)
    data = archive()
    preview = client.post(
        "/api/v1/dsh/market/admin/workbenches/imports/preview",
        files={"file": ("workbench.tgz", data, "application/gzip")},
    ).json()["data"]
    assert preview["workbench_key"] == "example/dsh-example-workbench"
    task = client.post(
        "/api/v1/dsh/market/admin/workbenches/imports",
        files={"file": ("workbench.tgz", data, "application/gzip")},
    ).json()["data"]
    assert task["status"] == "completed"
    row = client.get("/api/v1/dsh/market/workbenches").json()["data"]["data"][0]
    detail = client.get(f"/api/v1/dsh/market/workbenches/{row['id']}").json()["data"]
    path = detail["current_version"]["artifact_url"]
    artifact = client.get(path)
    assert artifact.headers["content-type"] == "application/gzip"
    assert artifact.headers["etag"] == '"' + hashlib.sha256(data).hexdigest() + '"'
    assert artifact.content == data
    service.storage.objects[2, hashlib.sha256(data).hexdigest()] = b"damaged"
    assert client.get(path).json()["status_code"] == 26208
    service.storage.objects.pop((2, hashlib.sha256(data).hexdigest()))
    assert client.get(path).json()["status_code"] == 26208
    app.dependency_overrides[market_actor] = lambda: MarketActor(3, 30)
    assert client.get(path).json()["status_code"] == 26207


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/dsh/market/workbenches",
        "/api/v1/dsh/market/workbenches/" + "a" * 32,
        "/api/v1/dsh/market/workbenches/" + "a" * 32 + "/versions/" + "b" * 32 + "/artifact",
    ],
)
def test_desktop_credential_ownership(path):
    assert owns_dsh_credential("GET", path)
    assert not owns_dsh_credential("POST", path)
