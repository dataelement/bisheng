import json
import sqlite3
from contextlib import closing
from pathlib import Path
from secrets import token_bytes
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.api.services import flow as flow_api
from bisheng.api.services import workflow as workflow_api
from bisheng.api.v1 import workflow as browser
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import WorkflowRegistrationError
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.config.settings import WorkflowRegistrationConf
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion, FlowVersionRead
from bisheng.open_endpoints.api.endpoints import kunlian_registration as candidate
from bisheng.workflow.application import kunlian_workflow_management as management
from bisheng.workflow.application.kunlian_registration_sync import RegistrationSync
from bisheng.workflow.domain.repositories import kunlian_registration as storage
from bisheng.workflow.domain.services.kunlian_registration_cursor import RegistrationCursor
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, seed


def example_graph():
    file = Path(__file__).parents[4] / "features/v3.0.0/120-kunlian-knowledge-retrieval/mock-workflow.example.json"
    graph = json.loads(file.read_text())
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] != "platform_knowledge_example"]
    graph["edges"] = [edge for edge in graph["edges"] if edge["source"] != "platform_knowledge_example"]
    graph["edges"][1]["target"] = "output_example"
    graph["nodes"][2]["data"]["group_params"][0]["params"][1]["value"]["msg"] = "fixture output"
    return graph


async def test_management_routes_keep_create_and_editor_permissions_separate(monkeypatch):
    from bisheng.common.schemas.api import resp_200
    from bisheng.user.domain.services.auth import AuthJwt

    user = UserPayload(user_id=12, tenant_id=7, user_role=[])
    graph = {"nodes": [], "edges": []}
    visible = AsyncMock(return_value=resp_200({"id": FLOW_ID, "name": "visible", "data": graph}))
    monkeypatch.setattr(flow_api.FlowService, "get_one_flow", visible)
    monkeypatch.setattr(
        flow_api.FlowService, "get_version_list_by_flow", AsyncMock(return_value=resp_200({"data": []}))
    )
    monkeypatch.setattr(flow_api, "require_business_action", AsyncMock(side_effect=UnAuthorizedError()))
    login_dependency = UserPayload.get_login_user
    monkeypatch.setattr(UserPayload, "get_login_user", AsyncMock(return_value=user))
    assert_create = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_any", assert_create)
    app = FastAPI()
    app.include_router(browser.router)
    app.dependency_overrides[AuthJwt] = lambda: None
    app.dependency_overrides[login_dependency] = lambda: user
    app.dependency_overrides[browser.header_share_token_parser] = lambda: None

    async def deny(_request, error):
        return JSONResponse(error.to_dict(), status_code=403)

    app.add_exception_handler(UnAuthorizedError, deny)
    url = f"/workflow/get_one_flow/{FLOW_ID}?scope=workflow_management"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        summary = await client.get(url)
        assert summary.status_code == 200 and "data" not in summary.json()["data"]
        assert (await client.get(url + "&view=edit")).status_code == 403
        create = await client.post(
            "/workflow/create?scope=workflow_management",
            headers={"Idempotency-Key": "fixture"},
            json={"name": "denied"},
        )
        assert create.status_code == 403
        assert_create.assert_awaited_once_with(user.user_id, ("create_workflow", "create_app"))
        visible.side_effect = UnAuthorizedError()
        assert (await client.get(url)).status_code == 403


@pytest.mark.parametrize(("status", "required_action"), [(1, "unpublish"), (2, "publish")])
async def test_legacy_status_patch_requires_action_for_unregistered_workflow(monkeypatch, status, required_action):
    user = UserPayload(user_id=12, tenant_id=7, user_role=[])
    flow = Flow(id=FLOW_ID, name="fixture", tenant_id=7, status=3 - status)
    monkeypatch.setattr(browser.FlowDao, "aget_flow_by_id", AsyncMock(return_value=flow))
    update = AsyncMock(return_value=flow)
    monkeypatch.setattr(browser.FlowDao, "aupdate_flow", update)
    monkeypatch.setattr(management, "workflow_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "check_business_action", AsyncMock(return_value=True))
    authorize = AsyncMock(side_effect=[UnAuthorizedError(), None])
    monkeypatch.setattr(browser, "require_business_action", authorize)
    monkeypatch.setattr(browser.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(flow_api.FlowService, "update_flow_hook", AsyncMock())
    app = FastAPI()
    app.include_router(browser.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user

    async def deny(_request, error):
        return JSONResponse(error.to_dict(), status_code=403)

    app.add_exception_handler(UnAuthorizedError, deny)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        url = f"/workflow/update/{FLOW_ID}"
        assert (await client.patch(url, json={"status": status})).status_code == 403
        assert flow.status == 3 - status
        update.assert_not_awaited()
        assert (await client.patch(url, json={"status": status})).status_code == 200
    assert authorize.await_args.kwargs["action"] == required_action
    assert flow.status == status


@pytest.mark.parametrize(
    ("method", "path", "body", "version_tenant"),
    [
        ("GET", "/versions?flow_id=" + FLOW_ID, None, 7),
        ("GET", "/versions/1", None, 7),
        ("GET", "/versions/1", None, 8),
        ("GET", "/get_one_flow/" + FLOW_ID, None, 7),
        ("POST", "/versions?flow_id=" + FLOW_ID, {"name": "unauthorized"}, 7),
        ("PATCH", "/update/" + FLOW_ID, {"name": "unauthorized"}, 7),
    ],
)
async def test_registered_browser_routes_reject_cross_tenant_even_if_business_action_allows(
    registration_store, monkeypatch, method, path, body, version_tenant
):
    repo = registration_store
    seed(repo)
    config = WorkflowRegistrationConf(mode="mock", tenant_ids={7}, workflow_ids={FLOW_ID})
    monkeypatch.setattr(management, "settings", SimpleNamespace(kunlian_workflow_registration=config))
    monkeypatch.setattr(management, "RegistrationRepository", lambda: repo)
    monkeypatch.setattr(storage, "RegistrationRepository", lambda: repo)

    with repo.transaction() as session:
        flow, version = session.get(Flow, FLOW_ID), session.get(FlowVersion, 1)
        version.tenant_id = version_tenant
    monkeypatch.setattr(browser.FlowDao, "aget_flow_by_id", AsyncMock(return_value=flow))
    monkeypatch.setattr(browser.FlowDao, "aupdate_flow", AsyncMock(return_value=flow))
    monkeypatch.setattr(browser.FlowVersionDao, "get_version_by_id", lambda *_: version)
    monkeypatch.setattr(browser.FlowVersionDao, "get_version_by_name", lambda *_: None)
    monkeypatch.setattr(browser.FlowVersionDao, "get_list_by_flow", lambda *_: [version])
    monkeypatch.setattr(browser.FlowVersionDao, "count_list_by_flow", lambda *_, **__: 1)
    monkeypatch.setattr(browser.FlowVersionDao, "create_version", lambda value: value)
    monkeypatch.setattr(flow_api.FlowService, "update_flow_hook", AsyncMock())
    monkeypatch.setattr(flow_api.FlowService, "get_logo_share_link_async", AsyncMock(return_value=None))
    monkeypatch.setattr(flow_api.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(flow_api, "require_business_action", AsyncMock())
    monkeypatch.setattr(flow_api, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(browser, "check_business_action", AsyncMock(return_value=True))

    app = FastAPI()
    app.include_router(browser.router)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(user_id=11, tenant_id=8, user_role=[])
    app.dependency_overrides[browser.header_share_token_parser] = lambda: None

    async def deny(_request, error):
        return JSONResponse(error.to_dict(), status_code=403)

    app.add_exception_handler(UnAuthorizedError, deny)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.request(method, "/workflow" + path, json=body)
        assert response.status_code == 403
        assert FLOW_ID not in response.text and "unauthorized" not in response.text
    assert flow.name == "flow"


async def test_mock_editor_to_catalog_with_replay_and_offline(registration_store, monkeypatch, tmp_path):
    from bisheng.workflow.nodes.output import output
    from bisheng.workflow.nodes.start import start

    repo = registration_store
    a = UserPayload(user_id=11, tenant_id=7, user_role=[])
    b = UserPayload(user_id=12, tenant_id=7, user_role=[])
    scope_config = WorkflowRegistrationConf(mode="mock", tenant_ids={7})
    monkeypatch.setattr(management, "settings", SimpleNamespace(kunlian_workflow_registration=scope_config))
    monkeypatch.setattr(storage, "RegistrationRepository", lambda: repo)
    monkeypatch.setattr(management, "RegistrationRepository", lambda: repo)
    quota, project = AsyncMock(), AsyncMock()
    monkeypatch.setattr(browser.QuotaService, "check_quota", quota)
    monkeypatch.setattr(flow_api.FlowService, "create_flow_hook", project)
    monkeypatch.setattr(flow_api.FlowService, "update_flow_hook", AsyncMock())
    monkeypatch.setattr(workflow_api.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(output, "get_minio_storage_sync", lambda: None)
    for dao, name in (
        (start.UserDao, "get_user"),
        (start.UserGroupDao, "get_user_group"),
        (start.UserRoleDao, "get_user_roles"),
        (start.UserDepartmentDao, "get_user_primary_department"),
    ):
        monkeypatch.setattr(dao, name, lambda *_: None)

    def read(model, ident):
        with repo.transaction() as session:
            return session.get(model, ident)

    get_flow = AsyncMock(side_effect=lambda flow_id: read(Flow, flow_id))
    monkeypatch.setattr(browser.FlowDao, "aget_flow_by_id", get_flow)
    monkeypatch.setattr(browser.FlowVersionDao, "get_version_by_id", lambda version_id: read(FlowVersion, version_id))
    monkeypatch.setattr(browser.FlowVersionDao, "get_version_by_name", lambda *_: None)

    def insert_version(version):
        version.tenant_id = 7
        with repo.transaction() as session:
            session.add(version)
            session.flush()
            return version

    monkeypatch.setattr(browser.FlowVersionDao, "create_version", insert_version)
    monkeypatch.setattr(
        browser.FlowVersionDao,
        "aget_version_by_id",
        AsyncMock(side_effect=lambda version_id, **_: read(FlowVersion, version_id)),
    )
    authorized = {11: {"visible", "edit", "publish", "unpublish"}, 12: {"visible"}}

    async def check(user, *, resource_type, resource_id, action):
        return resource_type == "workflow" and action in authorized[user.user_id]

    async def require(user, **kwargs):
        if not await check(user, **kwargs):
            raise UnAuthorizedError()

    for module in (browser, flow_api, workflow_api, management):
        if hasattr(module, "require_business_action"):
            monkeypatch.setattr(module, "require_business_action", require)
    monkeypatch.setattr(management, "check_business_action", check)
    monkeypatch.setattr(browser, "check_business_action", check)
    sync = RegistrationSync(repo, management.mock_scope(7), RegistrationCursor(token_bytes(32)), lambda _: True)
    reader = management.WorkflowManagementReader(b, AsyncMock(), get_flow, repo)
    app = FastAPI()
    app.include_router(browser.router, prefix="/api/v1")
    app.include_router(candidate.router, prefix="/api/v2")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: a
    app.dependency_overrides[UserPayload.get_workflow_creator_user] = lambda: a
    app.dependency_overrides[candidate.read_identity] = lambda: reader
    app.dependency_overrides[candidate.sync_reader] = lambda: sync

    async def safe_error(_request, error):
        return JSONResponse(error.to_dict(), status_code=getattr(error, "http_status", 403))

    app.add_exception_handler(WorkflowRegistrationError, safe_error)
    app.add_exception_handler(UnAuthorizedError, safe_error)
    graph = example_graph()
    directory_db = tmp_path / "mock-directory.sqlite"

    def commit_directory(items, cursor, pending_receipt=None):
        with closing(sqlite3.connect(directory_db)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS checkpoint "
                "(id INTEGER PRIMARY KEY, catalog TEXT, cursor TEXT, pending_receipt TEXT)"
            )
            db.execute(
                "REPLACE INTO checkpoint VALUES (1, ?, ?, ?)",
                (json.dumps(items), cursor, json.dumps(pending_receipt)),
            )

    def recover_directory():
        with closing(sqlite3.connect(directory_db)) as db:
            items, cursor, pending = db.execute(
                "SELECT catalog, cursor, pending_receipt FROM checkpoint WHERE id=1"
            ).fetchone()
            return json.loads(items), cursor, json.loads(pending)

    def finish_receipt(receipt):
        with closing(sqlite3.connect(directory_db)) as db, db:
            db.execute(
                "UPDATE checkpoint SET pending_receipt = 'null' WHERE pending_receipt = ?", (json.dumps(receipt),)
            )

    api = "/api/v1/workflow"
    registration = "/api/v2/kunlian/workflow-registrations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:

        async def data(method, url, **kwargs):
            response = await client.request(method, url, **kwargs)
            assert response.is_success, response.text
            return response.json()["data"]

        request = {"json": {"name": "fixture", "data": graph}, "headers": {"Idempotency-Key": "fixture-key"}}
        created = await data("POST", api + "/create", **request)
        assert (await data("POST", api + "/create", **request))["id"] == created["id"]
        quota.assert_awaited_once()
        project.assert_awaited_once()
        flow_id, version_id = created["id"], created["version_id"]
        listed = read(Flow, flow_id)
        listing = browser.FlowDao._app_row_to_dict(
            (
                listed.id,
                listed.name,
                listed.description,
                listed.flow_type,
                None,
                listed.user_id,
                listed.status,
                listed.create_time,
                listed.update_time,
            )
        )
        foreign_id = "x" * 32
        with repo.transaction() as session:
            session.add(Flow(id=foreign_id, name="foreign", user_id=11, tenant_id=8))
        reader.list_flows.return_value = SimpleNamespace(
            data=[{**listing, "id": foreign_id, "name": "foreign"}, listing], next_cursor=None, has_more=False
        )
        items = (await data("GET", "/api/v2/kunlian/workflows"))["items"]
        assert [item["workflow_id"] for item in items] == [flow_id]
        detail_url = f"/api/v2/kunlian/workflows/{flow_id}"
        assert not (await data("GET", detail_url))["allowed_actions"]["edit"]
        authorized[12].clear()
        assert (await client.get(detail_url)).status_code == 403

        draft_url = f"{api}/versions/{version_id}"
        draft = await data("GET", draft_url)
        version_summary = FlowVersionRead.model_validate(read(FlowVersion, version_id).model_dump(exclude={"data"}))
        monkeypatch.setattr(browser.FlowVersionDao, "get_list_by_flow", lambda _: [version_summary])
        monkeypatch.setattr(browser.FlowVersionDao, "count_list_by_flow", lambda *_, **__: 1)
        version_list = await data("GET", api + "/versions", params={"flow_id": flow_id})
        revision = version_list["data"][0]["draft_revision"]
        assert revision == draft["draft_revision"]
        await data("PUT", draft_url, headers={"If-Match": revision}, json={"data": graph, "name": "v1"})
        start = await data("GET", registration + "/snapshot")
        await data("PATCH", api + "/status", json={"flow_id": flow_id, "version_id": version_id, "status": 2})
        changes_url = registration + "/changes"
        first = await data("GET", changes_url, params={"cursor": start["base_cursor"]})
        assert (await data("GET", changes_url, params={"cursor": start["base_cursor"]}))["items"] == first["items"]
        version_url = f"{registration}/{flow_id}/versions/{version_id}"
        assert (await data("GET", version_url))["descriptor"]["workflow_version_id"] == str(version_id)
        selected = first["items"][0]["current"]["workflow_version_id"]
        receipt_url = registration + "/receipts"
        registered = {
            "workflow_id": flow_id,
            "workflow_version_id": str(version_id),
            "sequence": 1,
            "status": "REGISTERED",
        }
        commit_directory({flow_id: selected}, first["next_cursor"], registered)
        assert (await client.post(receipt_url, json=registered)).status_code == 503
        catalog, checkpoint, pending_receipt = recover_directory()
        saved_binding = catalog[flow_id]
        assert checkpoint == first["next_cursor"] and pending_receipt == registered
        app.dependency_overrides[candidate.receipt_writer] = lambda: sync
        failed = {**pending_receipt, "status": "FAILED", "reason": "DIRECTORY_WRITE_FAILED"}
        assert (await data("POST", receipt_url, json=failed))["applied"]
        assert repo.status(sync.scope, flow_id)["status"] == "FAILED"
        assert (await data("POST", receipt_url, json=pending_receipt))["applied"] is True
        finish_receipt(pending_receipt)
        assert recover_directory() == (catalog, checkpoint, None)
        second = await data("POST", api + "/versions", params={"flow_id": flow_id}, json={"name": "v2", "data": graph})
        await data("PATCH", api + "/status", json={"flow_id": flow_id, "version_id": second["id"], "status": 2})
        replacement = await data("GET", changes_url, params={"cursor": checkpoint})
        event = replacement["items"][0]
        assert event["retired_version_id"] == catalog[flow_id]
        catalog[flow_id] = event["current"]["workflow_version_id"]
        commit_directory(catalog, replacement["next_cursor"])
        catalog, checkpoint, _ = recover_directory()
        assert catalog[flow_id] == str(second["id"]) and saved_binding == str(version_id)
        assert (await data("GET", version_url))["descriptor"] is None
        authorized[11].remove("unpublish")
        legacy_offline = f"{api}/update/{flow_id}"
        assert (await client.patch(legacy_offline, json={"status": 1})).status_code == 403
        authorized[11].add("unpublish")
        audit_count = flow_api.FlowService.update_flow_hook.await_count
        await data("PATCH", legacy_offline, json={"status": 1})
        assert flow_api.FlowService.update_flow_hook.await_count == audit_count + 1
        assert (await data("GET", f"{registration}/{flow_id}/versions/{second['id']}"))["descriptor"] is None
        offline = await data("GET", changes_url, params={"cursor": checkpoint})
        assert offline["items"][0]["change_type"] == "UNPUBLISHED"
        catalog.pop(offline["items"][0]["workflow_id"])
        commit_directory(catalog, offline["next_cursor"])
        assert recover_directory() == ({}, offline["next_cursor"], None)
        assert not catalog and not (await data("GET", registration + "/snapshot"))["items"]
        assert not (await data("POST", receipt_url, json=registered))["applied"]
        removed = {**registered, "workflow_version_id": str(second["id"]), "sequence": 3, "status": "REMOVED"}
        assert (await data("POST", receipt_url, json=removed))["applied"]
        assert repo.status(sync.scope, flow_id)["status"] == "REMOVED"
