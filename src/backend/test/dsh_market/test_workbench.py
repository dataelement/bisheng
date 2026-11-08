"""Workbench archive validation and tenant-scoped distribution contracts."""

import hashlib
import io
import json
import os
import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

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


PATCH = "- insert:\n    - id: example-workbench\n      name: dsh-example-workbench\n"


@pytest.mark.parametrize(
    "config",
    [
        "",
        "      config: {}\n",
        "      config:\n        root: !!js dshHomePath('mind-workbench')\n",
        '      config:\n        root: !!js dshHomePath("mind-workbench")\n',
    ],
)
def test_config_preview_import_preserves_archive(service, config):
    """AC-01/02: Old and configured bundles preview/import without changing bytes."""
    data = archive(extra={"package/cordis.patch.yml": (PATCH + config).encode()})
    assert service.preview(2, data)["allowed"]
    assert service.import_bundle(2, 20, data)["status"] == "completed"
    row = service.list(2)["data"][0]
    version = service.detail(2, row["id"])["current_version"]
    assert service.download(2, row["id"], version["id"])[0] == data


@pytest.mark.parametrize(
    "patch,code,field",
    [
        (PATCH.replace("dsh-example-workbench", "other"), "NAME_MISMATCH", ".name"),
        (PATCH.replace("    - id: example-workbench\n      name:", "    - name:"), "MISSING_FIELD", ".id"),
        (PATCH.replace("id: example-workbench", "id: '   '"), "INVALID_ID", ".id"),
        (PATCH + "      extra: true\n", "UNSUPPORTED_FIELD", ".extra"),
        (PATCH + "      config: []\n", "INVALID_CONFIG", ".config"),
        (PATCH + "      config: null\n", "INVALID_CONFIG", ".config"),
        (PATCH + "      config:\n        root: !!js process.exit()\n", "UNSUPPORTED_EXPRESSION", ".root"),
        (PATCH + "      config:\n        root: !!js dshHomePath('../escape')\n", "UNSUPPORTED_EXPRESSION", ".root"),
        (
            PATCH + "      config:\n        root: !!js dshHomePath('mind-workbench');evil()\n",
            "UNSUPPORTED_EXPRESSION",
            ".root",
        ),
        (
            PATCH + "      config:\n        other: !!js dshHomePath('mind-workbench')\n",
            "UNSUPPORTED_EXPRESSION",
            ".other",
        ),
        (PATCH + "      config:\n        root: !unknown test\n", "UNSUPPORTED_TAG", ".root"),
        (PATCH + "      config: &loop {self: *loop}\n", "INVALID_CONFIG", ".self"),
        (PATCH + "      config: {root: a, root: b}\n", "INVALID_CONFIG", ".config"),
        (PATCH + "      config: {nested: " + "[" * 20 + "0" + "]" * 20 + "}\n", "DEPTH_LIMIT", "patch"),
        (PATCH + "      config: {values: [" + ",".join(["0"] * 2050) + "]}\n", "NODE_LIMIT", "patch"),
        (PATCH + PATCH, "INSERT_COUNT", "patch"),
    ],
)
def test_patch_rejection_details(patch, code, field):
    """AC-03: Unsafe and unsupported patches retain precise rejection details."""
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(archive(extra={"package/cordis.patch.yml": patch.encode()}))
    details = caught.value.details()
    assert details["code"] == "WORKBENCH_PATCH_" + code
    assert details["rule"] == "WB-08"
    assert details["field"].endswith(field)
    assert details["message"]


def test_patch_never_constructs_yaml_objects(monkeypatch):
    """AC-02: Even accepted !!js nodes must never invoke a YAML constructor."""
    import yaml

    def reject_construction(*args, **kwargs):
        pytest.fail("Static preview attempted to construct a YAML object")

    monkeypatch.setattr(yaml.SafeLoader, "construct_object", reject_construction)
    data = archive(
        extra={
            "package/cordis.patch.yml": (
                PATCH + "      config:\n        root: !!js dshHomePath('mind-workbench')\n"
            ).encode()
        }
    )
    assert validate_workbench_bundle(data)["package_metadata"]["patch_entry_id"] == "example-workbench"


def test_expanded_alias_budget():
    """AC-03: A small source graph must not bypass the expanded node budget."""
    config = (
        "      config:\n        small: &small [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]\n        many: &many ["
        + ",".join(["*small"] * 30)
        + "]\n        expanded: ["
        + ",".join(["*many"] * 30)
        + "]\n"
    )
    with pytest.raises(WorkbenchBundleError) as caught:
        validate_workbench_bundle(archive(extra={"package/cordis.patch.yml": (PATCH + config).encode()}))
    assert caught.value.code == "WORKBENCH_PATCH_NODE_LIMIT"


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
    rejected = client.post(
        "/api/v1/dsh/market/admin/workbenches/imports/preview",
        files={
            "file": (
                "workbench.tgz",
                archive(extra={"package/cordis.patch.yml": (PATCH + "      config: []\n").encode()}),
                "application/gzip",
            )
        },
    ).json()
    assert rejected["status_code"] == 26205
    assert rejected["data"]["code"] == "WORKBENCH_PATCH_INVALID_CONFIG"
    assert rejected["data"]["rule"] == "WB-08"
    assert rejected["data"]["field"] == "patch[0].insert[0].config"
    assert rejected["data"]["message"] == "Patch config must be a YAML mapping"
    data = archive(
        extra={
            "package/cordis.patch.yml": (
                PATCH + "      config:\n        root: !!js dshHomePath('mind-workbench')\n"
            ).encode()
        }
    )
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


def test_original_mind_workbench_preview_and_download(service):
    """AC-04: Opt-in original TGZ API preview/import/download regression, without repacking."""
    path = os.environ.get("WORKBENCH_ORIGINAL_TGZ")
    if not path:
        pytest.skip("Set WORKBENCH_ORIGINAL_TGZ to the original mind workbench 1.0.15 TGZ")
    data = Path(path).read_bytes()
    digest = "c293cd7554c239d61d0dd1d0672c9413b9c0e5a80ddf58b473886b4ee2952d07"
    assert hashlib.sha256(data).hexdigest() == digest
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_workbench_service] = lambda: service
    app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    client = TestClient(app)
    root = "/api/v1/dsh/market"
    upload = {"file": ("mind-workbench.tgz", data, "application/gzip")}
    preview = client.post(root + "/admin/workbenches/imports/preview", files=upload).json()
    assert preview["status_code"] == 200
    assert preview["data"]["allowed"]
    assert preview["data"]["workbench_key"] == "andoaidlaksldk/dsh-mind-workbench"
    assert client.post(root + "/admin/workbenches/imports", files=upload).json()["data"]["status"] == "completed"
    row = client.get(root + "/workbenches").json()["data"]["data"][0]
    detail = client.get(root + "/workbenches/" + row["id"]).json()["data"]
    assert detail["verification_level"] == "static"
    artifact = client.get(detail["current_version"]["artifact_url"])
    assert artifact.content == data
    assert artifact.headers["etag"] == '"' + digest + '"'
    assert Path(path).read_bytes() == data


def test_multiselect_api_upgrade_and_partial_failures(service):
    """AC-MULTI-03/04: Per-file API calls keep valid upgrades after rejected/failed siblings."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    app.dependency_overrides[get_workbench_service] = lambda: service
    app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    client = TestClient(app)
    root = "/api/v1/dsh/market/admin/workbenches/imports"

    def post(path, data):
        return client.post(root + path, files={"file": ("workbench.tgz", data, "application/gzip")}).json()

    assert post("", archive("1.0.0"))["data"]["status"] == "completed"
    upgraded = archive("1.1.0")
    invalid = archive("1.5.0", extra={"package/cordis.patch.yml": (PATCH + "      config: []\n").encode()})
    conflict = archive("1.1.0", extra={"package/client.js": b"different bytes"})
    latest = archive("1.2.0")
    queue = [upgraded, invalid, conflict, latest, archive("0.9.0")]
    previews = [post("/preview", data) for data in queue]
    assert previews[0]["data"]["allowed"]
    assert previews[1]["status_code"] == 26205
    assert previews[1]["data"]["code"] == "WORKBENCH_PATCH_INVALID_CONFIG"
    assert previews[2]["data"]["allowed"]
    assert previews[3]["data"]["allowed"]
    assert not previews[4]["data"]["allowed"]
    assert previews[4]["data"]["reason"] == "lower_version"

    # The UI calls existing single-package APIs for ready entries, in selection order.
    outcomes = [
        post("", data)["data"]
        for data, preview in zip(queue, previews, strict=True)
        if preview["status_code"] == 200 and preview["data"]["allowed"]
    ]
    assert [task["status"] for task in outcomes] == ["completed", "completed", "completed"]
    row = service.list(2)["data"][0]
    assert row["current_version"]["version"] == "1.2.0"
    assert service.download(2, row["id"], row["current_version"]["id"])[0] == latest
    assert service.list(3)["total"] == 0


@pytest.fixture
def workbench_client(service, monkeypatch):
    """Use the real admin dependency; replace only identity and external lookups."""
    import bisheng.common.permission_identity as identity
    import bisheng.dsh_market.infrastructure as infrastructure

    async def tenant_admin(user_id, tenant_id):
        return user_id == 20 and tenant_id == 2

    async def tenant_active(tenant_id):
        return True

    monkeypatch.setattr(identity, "check_tenant_admin", tenant_admin)
    monkeypatch.setattr(infrastructure, "tenant_is_active", tenant_active)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    app.dependency_overrides[get_workbench_service] = lambda: service
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    with TestClient(app) as client:
        yield client, app


def test_router_overwrite_cycle_delete_restore(workbench_client, service):
    """AC-UPDATE-01/02/04/05: import, overwrite, delete and actively restore."""
    client, _app = workbench_client
    root = "/api/v1/dsh/market"
    imports = root + "/admin/workbenches/imports"
    first = archive("1.0.0")
    package = {
        "name": "dsh-example-workbench",
        "version": "1.0.0",
        "description": "Updated description",
        "main": "./desktop.js",
        "exports": {".": "./desktop.js", "./client": "./client.js"},
        "repository": "git+https://github.com/example/dsh-example-workbench.git",
        "license": "MIT",
        "dsh": {
            "bundle": {"patch": "./cordis.patch.yml"},
            "client": {"platform": "web", "inject": ["dsh-desktop-workbenches"]},
        },
    }
    changed = archive(
        "1.0.0",
        extra={
            "package/client.js": b"updated client with different size",
            "package/package.json": json.dumps(package).encode(),
        },
    )

    def upload(data, name=None):
        return client.post(
            imports,
            files={"file": ("workbench.tgz", data, "application/gzip")},
            data={"display_name": name} if name else {},
        ).json()["data"]

    first_task = upload(first)
    assert first_task["status"] == "completed"
    row = client.get(root + "/workbenches").json()["data"]["data"][0]
    path = root + "/workbenches/" + row["id"]
    original = client.get(path).json()["data"]
    artifact_path = original["current_version"]["artifact_url"]
    version_id = original["current_version"]["id"]
    preview = client.post(imports + "/preview", files={"file": ("workbench.tgz", changed)}).json()["data"]
    assert preview["allowed"] and preview["overwrite"] and not preview["duplicate"]
    changed_task = upload(changed, "Custom workbench")
    assert changed_task["status"] == "completed"
    assert changed_task["version_id"] == version_id
    detail = client.get(path).json()["data"]
    assert detail["description"] == "Updated description"
    assert detail["display_name"] == "Custom workbench"
    assert detail["revision"] == original["revision"] + 1
    assert detail["package_metadata"]["license"] == "MIT"
    assert detail["current_version"]["size_bytes"] == len(changed)
    artifact = client.get(artifact_path)
    assert artifact.content == changed
    assert artifact.headers["etag"] == '"' + hashlib.sha256(changed).hexdigest() + '"'
    assert detail["current_version"]["sha256"] == hashlib.sha256(changed).hexdigest()
    duplicate = client.post(imports + "/preview", files={"file": ("workbench.tgz", changed)}).json()["data"]
    assert duplicate["allowed"] and duplicate["duplicate"] and not duplicate["overwrite"]
    upload(changed)
    assert client.get(path).json()["data"]["revision"] == detail["revision"]
    upload(changed, "Renamed workbench")
    assert client.get(path).json()["data"]["display_name"] == "Renamed workbench"
    # The first digest's completed task must not short-circuit A -> B -> A.
    assert upload(first)["id"] == first_task["id"]
    assert client.get(artifact_path).content == first
    restored_a = client.get(path).json()["data"]
    assert restored_a["current_version"]["sha256"] == hashlib.sha256(first).hexdigest()
    assert restored_a["package_metadata"]["license"] is None
    delete_path = root + "/admin/workbenches/" + row["id"]
    assert client.delete(delete_path, params={"revision": original["revision"]}).json()["status_code"] == 26206
    assert client.get(artifact_path).content == first
    deleted = client.delete(delete_path, params={"revision": restored_a["revision"]}).json()
    assert deleted["data"] == {"id": row["id"], "deleted": True}
    assert client.get(root + "/workbenches").json()["data"]["total"] == 0
    assert client.get(root + "/admin/workbenches").json()["data"]["total"] == 0
    assert client.get(path).json()["status_code"] == 26207
    assert client.get(artifact_path).json()["status_code"] == 26207
    assert client.delete(delete_path, params={"revision": restored_a["revision"]}).json()["status_code"] == 26207
    assert upload(first)["status"] == "completed"
    restored = client.get(path).json()["data"]
    assert restored["current_version"]["id"] == version_id
    assert restored["revision"] == restored_a["revision"] + 2
    assert client.get(artifact_path).content == first
    assert len(service.storage.objects) == 2


def test_router_delete_permissions_and_tenant_isolation(workbench_client):
    client, app = workbench_client
    root = "/api/v1/dsh/market"
    task = client.post(root + "/admin/workbenches/imports", files={"file": ("a.tgz", archive())}).json()["data"]
    assert task["status"] == "completed"
    row = client.get(root + "/workbenches").json()["data"]["data"][0]
    detail_path = root + "/workbenches/" + row["id"]
    artifact_path = client.get(detail_path).json()["data"]["current_version"]["artifact_url"]
    delete_path = root + "/admin/workbenches/" + row["id"]
    assert client.delete(delete_path).status_code == 422
    assert client.delete(delete_path, params={"revision": 0}).status_code == 422
    assert (
        client.delete(delete_path, params={"revision": row["revision"]}, headers={"x-dsh-market-tenant": "3"}).json()[
            "status_code"
        ]
        == 26204
    )
    for actor in (MarketActor(2, 21), MarketActor(2, 20, desktop=True)):
        app.dependency_overrides[market_actor] = lambda actor=actor: actor
        assert client.delete(delete_path, params={"revision": row["revision"]}).json()["status_code"] == 26204
        assert client.get(detail_path).json()["data"]["id"] == row["id"]
    app.dependency_overrides[market_actor] = lambda: MarketActor(3, 30, global_super=True)
    assert client.delete(delete_path, params={"revision": row["revision"]}).json()["status_code"] == 26207
    assert client.get(detail_path).json()["status_code"] == 26207
    assert client.get(artifact_path).json()["status_code"] == 26207
    assert client.get(root + "/workbenches").json()["data"]["total"] == 0
    app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
    assert client.get(detail_path).json()["data"]["revision"] == row["revision"]


@pytest.mark.parametrize("mutation", ["overwrite", "delete", "upgrade"])
def test_download_detects_concurrent_changes(service, monkeypatch, mutation):
    from bisheng.dsh_market.domain.workbench_service import WorkbenchArtifactError

    first = archive("1.0.0")
    service.import_bundle(2, 20, first)
    row = service.list(2)["data"][0]
    read = service.storage.get

    def mutate_after_read(tenant, digest):
        data = read(tenant, digest)
        if mutation == "delete":
            service.delete(2, 20, row["id"], row["revision"])
        else:
            service.import_bundle(
                2,
                20,
                archive(
                    "1.1.0" if mutation == "upgrade" else "1.0.0", extra={"package/client.js": b"concurrent change"}
                ),
            )
        return data

    monkeypatch.setattr(service.storage, "get", mutate_after_read)
    with pytest.raises(WorkbenchArtifactError, match="changed"):
        service.download(2, row["id"], row["current_version"]["id"])


def test_identity_conflict_and_lower_version_still_rejected(service):
    service.import_bundle(2, 20, archive("1.0.0"))
    assert service.preview(2, archive("0.9.0"))["reason"] == "lower_version"
    assert service.preview(2, archive("1.0.0+build"))["reason"] == "version_conflict"
    assert service.preview(2, archive("1.0.0", repository=False))["reason"] == "identity_conflict"
    service.import_bundle(2, 20, archive("1.1.0"))
    historical = service.preview(2, archive("1.0.0", extra={"package/client.js": b"old version overwrite"}))
    assert historical["reason"] == "lower_version"
    assert not historical["allowed"] and not historical["overwrite"]


def test_deleted_equivalent_build_restore_preserves_history_and_tenant_isolation(service):
    from bisheng.dsh_market.domain.models import MarketWorkbenchVersion

    original = archive("0.2.1")
    variant = archive("0.2.1+enterprise.screenshots.1")
    original_task = service.import_bundle(2, 20, original)
    row = service.list(2)["data"][0]
    assert service.preview(2, variant)["reason"] == "version_conflict"
    service.delete(2, 20, row["id"], row["revision"])
    assert service.preview(2, archive("0.2.0"))["reason"] == "lower_version"
    assert service.preview(2, archive("0.2.1", repository=False))["reason"] == "identity_conflict"
    assert service.preview(2, variant)["allowed"]
    restored_task = service.import_bundle(2, 20, variant)
    assert restored_task["status"] == "completed"
    restored = service.detail(2, row["id"])
    assert restored["id"] == row["id"]
    assert restored["revision"] == row["revision"] + 2
    with pytest.raises(LookupError):
        service.download(2, row["id"], original_task["version_id"])
    assert restored["current_version"]["version"] == "0.2.1+enterprise.screenshots.1"
    assert restored_task["version_id"] != original_task["version_id"]
    assert service.download(2, row["id"], restored_task["version_id"])[0] == variant
    assert service.preview(2, variant)["allowed"]
    assert service.import_bundle(2, 20, variant)["status"] == "completed"
    changed = archive("0.2.1+enterprise.screenshots.1", extra={"package/client.js": b"changed bytes"})
    preview = service.preview(2, changed)
    assert preview["allowed"] and preview["overwrite"] and not preview["duplicate"]
    assert service.import_bundle(2, 20, changed)["status"] == "completed"
    assert service.download(2, row["id"], restored_task["version_id"])[0] == changed
    assert service.detail(2, row["id"])["revision"] == restored["revision"] + 1
    assert service.preview(2, original)["reason"] == "version_conflict"
    assert service.preview(2, archive("0.2.0"))["reason"] == "lower_version"
    assert service.list(3)["total"] == 0
    assert service.import_bundle(3, 30, original)["status"] == "completed"
    assert service.list(3)["data"][0]["id"] != row["id"]
    with service.repository.sessions() as db:
        versions = db.exec(
            select(MarketWorkbenchVersion).where(MarketWorkbenchVersion.workbench_id == row["id"])
        ).all()
        assert {v.version for v in versions} == {"0.2.1", "0.2.1+enterprise.screenshots.1"}


def test_real_archive_above_old_eight_mib_limit(workbench_client):
    client, _app = workbench_client
    data = archive(extra={"package/assets/payload.bin": os.urandom(8 * 1024 * 1024 + 1024)})
    assert 8 * 1024 * 1024 < len(data) < 100 * 1024 * 1024
    root = "/api/v1/dsh/market/admin/workbenches/imports"
    assert client.post(root + "/preview", files={"file": ("large.tgz", data)}).json()["data"]["allowed"]
    assert client.post(root, files={"file": ("large.tgz", data)}).json()["data"]["status"] == "completed"


def test_compressed_hundred_mib_boundary(workbench_client):
    """Actual valid gzip bytes at the boundary; zero padding is legal gzip padding."""
    from bisheng.dsh_market.domain.workbench_bundle import MAX_WORKBENCH_UPLOAD_BYTES

    assert MAX_WORKBENCH_UPLOAD_BYTES == 100 * 1024 * 1024
    client, _app = workbench_client
    data = archive()
    data += b"\0" * (MAX_WORKBENCH_UPLOAD_BYTES - len(data))
    assert validate_workbench_bundle(data)["version"] == "0.12.6"
    root = "/api/v1/dsh/market/admin/workbenches/imports"
    accepted = client.post(root + "/preview", files={"file": ("boundary.tgz", data)}).json()
    assert accepted["data"]["allowed"]
    imported = client.post(root, files={"file": ("boundary.tgz", data)}).json()
    assert imported["data"]["status"] == "completed"
    for endpoint in (root, root + "/preview"):
        rejected = client.post(endpoint, files={"file": ("too-large.tgz", data + b"\0")}).json()
        assert rejected["status_code"] == 26205
        assert rejected["data"]["code"] == "WORKBENCH_ARCHIVE_LIMIT"
        assert "100 MiB" in rejected["data"]["message"]
    with pytest.raises(WorkbenchBundleError, match="100 MiB"):
        validate_workbench_bundle(data + b"\0")


def test_expanded_limit_remains_256_mib():
    from bisheng.dsh_market.domain.workbench_bundle import MAX_WORKBENCH_EXPANDED_BYTES

    assert MAX_WORKBENCH_EXPANDED_BYTES == 256 * 1024 * 1024
    # Reject the declared expanded size before reading the body.
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        info = tarfile.TarInfo("package/assets/too-large.bin")
        info.size = MAX_WORKBENCH_EXPANDED_BYTES + 1
        tar.addfile(info)
    with pytest.raises(WorkbenchBundleError, match="Expanded archive exceeds 256 MiB"):
        validate_workbench_bundle(stream.getvalue())


def test_concurrent_duplicate_import_reapplies_after_insert_conflict(service, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    original = archive("1.0.0")
    replacement = archive("1.0.0", extra={"package/client.js": b"replacement"})
    commit = Session.commit
    inject_conflict = True

    def commit_after_concurrent_overwrite(db):
        nonlocal inject_conflict
        if not inject_conflict:
            return commit(db)
        inject_conflict = False
        db.rollback()
        # Another request completes A, then imports B before the losing A insert.
        assert service.import_bundle(2, 20, original)["status"] == "completed"
        assert service.import_bundle(2, 21, replacement)["status"] == "completed"
        raise IntegrityError("duplicate import digest", {}, RuntimeError("duplicate key"))

    monkeypatch.setattr(Session, "commit", commit_after_concurrent_overwrite)
    task = service.import_bundle(2, 22, original, "Winning custom name")
    assert task["status"] == "completed" and task["actor_id"] == 22
    row = service.list(2)["data"][0]
    assert row["display_name"] == "Winning custom name"
    assert service.download(2, row["id"], task["version_id"])[0] == original
