from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from bisheng.api.services import flow, workflow
from bisheng.api.v1 import workflow as browser
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import PermissionProjectionFailedError
from bisheng.permission.api import dependencies
from bisheng.permission.api.endpoints import grant as browser_grants
from bisheng.workflow.application import kunlian_workflow_management as management
from test.workflow.kunlian_workflow_authorization_fixtures import ADMIN, MEMBER, TENANT, WORKFLOW, PermissionFixture
from test.workflow.test_kunlian_workflow_authorization_reads import BASE


@pytest.mark.parametrize("independent_group", [False, True])
async def test_authorization_changes_reach_existing_workflow_endpoints(monkeypatch, independent_group):
    fixture = PermissionFixture()
    app, api = fixture.app()
    app.include_router(browser.router)
    app.include_router(browser_grants.router, prefix="/permissions")
    current = [ADMIN]
    app.dependency_overrides[api.authorization_subject] = lambda: fixture.subject(current[0])
    app.dependency_overrides[UserPayload.get_login_user] = lambda: UserPayload(
        user_id=current[0], tenant_id=TENANT, user_role=[]
    )
    app.dependency_overrides[browser.header_share_token_parser] = lambda: None
    app.dependency_overrides[dependencies.get_resource_permission_api] = lambda: fixture

    async def actor(user):
        return fixture.subject(user.user_id).actor

    async def decision(user, *, resource_type, resource_id, action):
        return await fixture.check(
            resource_type=resource_type, resource_id=resource_id, action=action, actor=await actor(user)
        )

    async def scan(**kwargs):
        assert kwargs["required_action"] == "visible"
        return ([{"id": WORKFLOW}] if WORKFLOW in kwargs["flow_ids"] else []), False, set()

    async def unauthorized(_request, error):
        return JSONResponse(error.to_dict(), status_code=403)

    app.add_exception_handler(UnAuthorizedError, unauthorized)
    monkeypatch.setattr(browser_grants, "permission_actor", actor)
    monkeypatch.setattr(browser, "check_business_action", decision)
    monkeypatch.setattr(flow, "check_business_action", decision)
    monkeypatch.setattr(workflow, "resolve_permission_actor", actor)
    monkeypatch.setattr(
        workflow.WorkFlowService,
        "_collect_visible_app_ids",
        AsyncMock(side_effect=lambda actor, _: [WORKFLOW] if "visible" in fixture.actions(actor) else []),
    )
    monkeypatch.setattr(workflow.WorkFlowService, "_scan_visible_flows_cursor", scan)
    monkeypatch.setattr(workflow.WorkFlowService, "add_extra_field", lambda user, data, managed, **kwargs: data)
    monkeypatch.setattr(
        browser.FlowDao,
        "aget_flow_by_id",
        AsyncMock(return_value=SimpleNamespace(id=WORKFLOW, flow_type=10, tenant_id=TENANT, logo=None)),
    )
    monkeypatch.setattr(flow.FlowService, "get_logo_share_link_async", AsyncMock(return_value=None))
    monkeypatch.setattr(management, "workflow_scope", lambda *args, **kwargs: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        grant_path = BASE + "/permissions/grants"
        roster = (await client.get(BASE + "/permissions")).json()["data"]
        body = {
            "expected_resource_version": roster["resource_version"],
            "expected_catalog_release_id": roster["catalog_release_id"],
            "subject_ref": "member-b",
            "model_key": "viewer",
        }
        granted = await client.post(grant_path, json=body, headers={"Idempotency-Key": "grant"})
        assert granted.status_code == 200 and granted.json()["data"]["status"] == "APPLIED"
        roster = (await client.get(BASE + "/permissions")).json()["data"]
        (row,) = roster["items"]
        current[0] = MEMBER
        listing = "/workflow/list?flow_type=10&action=visible"
        detail = f"/workflow/get_one_flow/{WORKFLOW}"
        assert (await client.get(listing)).json()["data"]["data"] == [{"id": WORKFLOW}]
        assert (await client.get(detail)).json()["data"]["id"] == WORKFLOW
        assert (await client.get(BASE + "/my-permissions")).json()["data"] == {"actions": ["visible"]}
        assert (await client.patch(f"/workflow/update/{WORKFLOW}", json={"name": "unauthorized"})).json()[
            "status_code"
        ] == UnAuthorizedError.Code
        assert (await client.post(grant_path, json=body, headers={"Idempotency-Key": "forbidden"})).status_code == 404

        current[0] = ADMIN
        fixture.membership = independent_group
        revoke_path = f"{grant_path}/{row['assignee_id']}/revoke"
        revoke = {
            "expected_resource_version": roster["resource_version"],
            "expected_catalog_release_id": roster["catalog_release_id"],
            "expected_assignee_version": row["assignee_version"],
        }
        revoked = await client.post(revoke_path, json=revoke, headers={"Idempotency-Key": "revoke"})
        assert revoked.status_code == 200
        assert (
            await client.post(revoke_path, json=revoke, headers={"Idempotency-Key": "revoke"})
        ).json() == revoked.json()
        assert (await client.get(BASE + "/permissions")).json()["data"]["items"] == []
        current[0] = MEMBER
        assert (await client.get(listing)).json()["data"]["data"] == ([{"id": WORKFLOW}] if independent_group else [])
        assert (await client.get(detail)).status_code == (200 if independent_group else 403)

        current[0] = ADMIN
        local = await client.post(
            f"/permissions/resources/workflow/{WORKFLOW}/grants:mutate",
            json={
                "idempotency_key": "browser",
                "expected_resource_version": fixture.revision,
                "expected_catalog_release_id": 12,
                "changes": [{"op": "ADD", "subject": {"type": "user", "id": str(MEMBER)}, "model_key": "viewer"}],
            },
        )
        assert local.json()["status_code"] == 200
        assert (await client.get(BASE + "/permissions")).json()["data"]["items"]
        assert (await client.post(grant_path, json=body, headers={"Idempotency-Key": "grant"})).json() == granted.json()
        assert fixture.mutations == 3


async def test_pending_and_revision_conflict_have_distinct_safe_http_results():
    fixture = PermissionFixture()
    app, api = fixture.app()
    app.dependency_overrides[api.authorization_subject] = lambda: fixture.subject()

    async def projection_unconfirmed(key):
        fixture.operations[key] = ("COMMITTED", fixture.revision)
        raise PermissionProjectionFailedError(msg="internal permission details")

    fixture.after_change = projection_unconfirmed
    body = {
        "expected_resource_version": 3,
        "expected_catalog_release_id": 12,
        "subject_ref": "member-b",
        "model_key": "viewer",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        path = BASE + "/permissions/grants"
        pending = await client.post(path, json=body, headers={"Idempotency-Key": "original"})
        assert pending.status_code == 202 and pending.headers["Cache-Control"] == "no-store"
        assert set(pending.json()["data"]) == {"operation_ref", "status"}
        assert pending.json()["data"]["status"] == "PENDING" and "internal permission details" not in pending.text
        conflict = await client.post(path, json=body, headers={"Idempotency-Key": "another"})
        assert conflict.status_code == 409 and conflict.json()["status_message"] == "REVISION_CONFLICT"
        assert fixture.mutations == 1
