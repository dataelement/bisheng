"""F022 employee market endpoints only serve visible items.

覆盖 AC: AC-03, AC-06, AC-07, AC-08, AC-09, AC-10, AC-15, AC-17, AC-18.
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.dsh_market.api.auth import MarketActor, market_actor, market_admin
from bisheng.dsh_market.api.endpoints import router
from bisheng.dsh_market.domain import permission as market_permission
from bisheng.dsh_market.domain.repository import MarketRepository
from bisheng.dsh_market.domain.service import MarketService
from bisheng.dsh_market.domain.workbench_repository import WorkbenchRepository
from bisheng.dsh_market.domain.workbench_service import WorkbenchService
from bisheng.dsh_market.infrastructure import get_market_service, get_workbench_service
from test.dsh_market.test_market import MemoryStorage, bundle
from test.dsh_market.test_market_permission import add_plugin, add_workbench, hex_id, sessions  # noqa: F401
from test.dsh_market.test_workbench import archive

ROOT = "/api/v1/dsh/market"
EMPLOYEE = MarketActor(2, 30)
ADMIN = MarketActor(2, 20)


class Grants:
    """Item ids visible to the employee; administrators see everything."""

    def __init__(self, monkeypatch):
        self.visible = set()
        self.decided = 0
        self.registered = []
        self.fail_registration = False
        monkeypatch.setattr(market_permission, "_visible_ids", self.visible_ids)
        monkeypatch.setattr(market_permission, "ensure_registered", self.ensure_registered)

    async def visible_ids(self, actor, resource_type, records):
        self.decided += 1
        if actor.user_id == ADMIN.user_id:
            return {record.id for record in records}
        return {record.id for record in records if record.id in self.visible}

    async def ensure_registered(self, resource_type, *, tenant_id, resource_id, operator_id):
        if self.fail_registration:
            from bisheng.common.errcode.permission import PermissionPublishNotReadyError

            raise PermissionPublishNotReadyError()
        self.registered.append((resource_type, tenant_id, resource_id, operator_id))


@pytest.fixture
def grants(monkeypatch):
    return Grants(monkeypatch)


@pytest.fixture
def client(sessions):  # noqa: F811
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(BaseErrorCode)
    async def error_handler(request, error):
        return JSONResponse(error.to_dict())

    plugins = MarketService(MarketRepository(sessions), MemoryStorage())
    workbenches = WorkbenchService(WorkbenchRepository(sessions), MemoryStorage())
    app.dependency_overrides[get_market_service] = lambda: plugins
    app.dependency_overrides[get_workbench_service] = lambda: workbenches
    app.dependency_overrides[market_actor] = lambda: EMPLOYEE
    app.dependency_overrides[market_admin] = lambda: ADMIN
    with TestClient(app) as test_client:
        test_client.app = app
        test_client.plugins = plugins
        test_client.workbenches = workbenches
        yield test_client


def as_admin(client):
    client.app.dependency_overrides[market_actor] = lambda: ADMIN


# --- employee plugin endpoints -----------------------------------------------------


def test_catalog_pages_only_visible_plugins(client, grants, sessions):  # noqa: F811
    ids = [add_plugin(sessions, number, age=number) for number in range(1, 6)]
    grants.visible = {ids[1], ids[3], ids[4]}
    first = client.get(f"{ROOT}/catalog", params={"size": 2}).json()["data"]
    second = client.get(f"{ROOT}/catalog", params={"size": 2, "page": 2}).json()["data"]
    assert [row["id"] for row in first["data"]] == [ids[1], ids[3]]
    assert [row["id"] for row in second["data"]] == [ids[4]]
    assert first["total"] == 3


def test_new_grants_show_on_the_next_request(client, grants, sessions):  # noqa: F811
    plugin_id = add_plugin(sessions, 1)
    assert client.get(f"{ROOT}/catalog").json()["data"]["total"] == 0
    grants.visible.add(plugin_id)
    assert [row["id"] for row in client.get(f"{ROOT}/catalog").json()["data"]["data"]] == [plugin_id]


def test_hidden_plugin_download_is_refused_like_a_missing_one(client, grants):
    response = client.post(f"{ROOT}/admin/imports", files={"file": ("plugin.zip", bundle(), "application/zip")})
    assert response.json()["data"]["status"] == "completed"
    as_admin(client)
    row = client.get(f"{ROOT}/admin/plugins").json()["data"]["data"][0]
    client.app.dependency_overrides[market_actor] = lambda: EMPLOYEE
    url = f"{ROOT}/plugins/{row['id']}/versions/{row['current_version_id']}/artifact"
    hidden = client.get(url)
    missing = client.get(f"{ROOT}/plugins/{hex_id(999)}/versions/{row['current_version_id']}/artifact")
    assert hidden.json() == missing.json()
    assert hidden.json()["status_code"] != 200
    assert "Company Demo" not in hidden.text
    grants.visible.add(row["id"])
    assert client.get(url).headers["content-type"] == "application/zip"


def test_sync_policies_drop_hidden_plugins(client, grants, sessions):  # noqa: F811
    shown, hidden = add_plugin(sessions, 1), add_plugin(sessions, 2)
    deleted = add_plugin(sessions, 3, deleted=True)
    grants.visible = {shown, deleted}
    receipt = client.post(f"{ROOT}/sync", json={"device_id": "device-1", "plugins": []}).json()["data"]
    assert {policy["plugin_id"] for policy in receipt["policies"]} == {shown, deleted}
    assert hidden not in str(receipt)


# --- employee workbench endpoints -------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/workbenches/{id}",
        "/workbenches/{id}/versions/{version}/screenshots/{image}",
        "/workbenches/{id}/versions/{version}/artifact",
    ],
)
def test_hidden_workbench_items_are_refused_like_missing_ones(client, grants, sessions, path):  # noqa: F811
    workbench_id = add_workbench(sessions, 1)
    version, image = hex_id(3001), "c" * 64
    hidden = client.get(ROOT + path.format(id=workbench_id, version=version, image=image))
    missing = client.get(ROOT + path.format(id=hex_id(999), version=version, image=image))
    assert hidden.json() == missing.json()
    assert hidden.json()["status_code"] != 200
    assert "Workbench 1" not in hidden.text


def test_workbench_list_pages_only_visible_items(client, grants, sessions):  # noqa: F811
    ids = [add_workbench(sessions, number, age=number) for number in range(1, 4)]
    grants.visible = {ids[0], ids[2]}
    data = client.get(f"{ROOT}/workbenches").json()["data"]
    assert [row["id"] for row in data["data"]] == [ids[0], ids[2]]
    assert data["total"] == 2
    detail = client.get(f"{ROOT}/workbenches/{ids[0]}").json()
    assert detail["data"]["id"] == ids[0]


def test_installed_workbench_access_answers_booleans(client, grants, sessions):  # noqa: F811
    shown, hidden = add_workbench(sessions, 1), add_workbench(sessions, 2)
    deleted = add_workbench(sessions, 3, deleted=True)
    grants.visible = {shown, deleted}
    response = client.post(f"{ROOT}/workbenches/access", json={"workbench_ids": [shown, hidden, deleted, hex_id(9)]})
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {shown: True, hidden: False, deleted: True, hex_id(9): False}


def test_installed_workbench_access_is_bounded(client, grants):
    too_many = [hex_id(number) for number in range(501)]
    assert client.post(f"{ROOT}/workbenches/access", json={"workbench_ids": too_many}).status_code == 422
    assert client.post(f"{ROOT}/workbenches/access", json={"workbench_ids": ["x" * 65]}).status_code == 422


# --- administrators -------------------------------------------------------------------


def test_admin_lists_are_never_filtered(client, grants, sessions):  # noqa: F811
    plugin_id, workbench_id = add_plugin(sessions, 1), add_workbench(sessions, 1)
    grants.visible = set()
    plugins = client.get(f"{ROOT}/admin/plugins").json()["data"]["data"]
    workbenches = client.get(f"{ROOT}/admin/workbenches").json()["data"]["data"]
    assert [row["id"] for row in plugins] == [plugin_id]
    assert [row["id"] for row in workbenches] == [workbench_id]


def test_install_policy_and_capabilities_ignore_item_grants(client, grants):
    assert client.get(f"{ROOT}/capabilities").json()["data"]["allow_third_party_plugins"] is False
    assert client.get(f"{ROOT}/admin/install-policy").json()["data"]["allow_third_party_workbenches"] is False
    assert grants.decided == 0


# --- registration after import ----------------------------------------------------------


def plugin_import(client, data=None):
    return client.post(f"{ROOT}/admin/imports", files={"file": ("plugin.zip", data or bundle(), "application/zip")})


def workbench_import(client, data=None):
    return client.post(
        f"{ROOT}/admin/workbenches/imports", files={"file": ("workbench.tgz", data or archive(), "application/gzip")}
    )


def test_plugin_import_registers_the_imported_plugin(client, grants):
    task = plugin_import(client).json()["data"]
    plugin_id = client.plugins.repository.item_for_version(2, task["version_id"])
    assert grants.registered == [("dsh_market_plugin", 2, plugin_id, ADMIN.user_id)]
    resumed = client.post(f"{ROOT}/admin/imports/{task['id']}/resume").json()["data"]
    assert resumed["status"] == "completed"
    assert grants.registered[-1] == ("dsh_market_plugin", 2, plugin_id, ADMIN.user_id)


def test_workbench_import_registers_the_imported_workbench(client, grants):
    task = workbench_import(client).json()["data"]
    workbench_id = client.workbenches.repository.item_for_version(2, task["version_id"])
    assert grants.registered == [("dsh_market_workbench", 2, workbench_id, ADMIN.user_id)]
    resumed = client.post(f"{ROOT}/admin/workbenches/imports/{task['id']}/resume").json()["data"]
    assert resumed["status"] == "completed"
    assert grants.registered[-1] == ("dsh_market_workbench", 2, workbench_id, ADMIN.user_id)


def test_failed_import_registers_nothing(client, grants):
    response = plugin_import(client, b"not a bundle")
    assert response.json()["status_code"] != 200 or response.json()["data"]["status"] == "failed"
    assert grants.registered == []


def test_registration_failure_fails_the_import_request(client, grants):
    grants.fail_registration = True
    assert plugin_import(client).json()["status_code"] != 200
    # A retry of the same file runs the registration again.
    grants.fail_registration = False
    assert plugin_import(client).json()["data"]["status"] == "completed"
    assert len(grants.registered) == 1


def test_restoring_reimport_targets_the_same_records(client, grants):
    first = plugin_import(client).json()["data"]
    plugin_id = client.plugins.repository.item_for_version(2, first["version_id"])
    as_admin(client)
    row = client.get(f"{ROOT}/admin/plugins").json()["data"]["data"][0]
    client.delete(f"{ROOT}/admin/plugins/{plugin_id}", params={"revision": row["revision"]})
    assert client.get(f"{ROOT}/admin/plugins").json()["data"]["total"] == 0
    restored = plugin_import(client).json()["data"]
    assert restored["status"] == "completed"
    assert client.plugins.repository.item_for_version(2, restored["version_id"]) == plugin_id
    assert {entry[2] for entry in grants.registered} == {plugin_id}

    workbench = workbench_import(client).json()["data"]
    workbench_id = client.workbenches.repository.item_for_version(2, workbench["version_id"])
    revision = client.get(f"{ROOT}/admin/workbenches").json()["data"]["data"][0]["revision"]
    client.delete(f"{ROOT}/admin/workbenches/{workbench_id}", params={"revision": revision})
    again = workbench_import(client).json()["data"]
    assert client.workbenches.repository.item_for_version(2, again["version_id"]) == workbench_id
