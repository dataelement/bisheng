import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.workflow.kunlian_workflow_authorization_fixtures import (
    ADMIN,
    MEMBER,
    OTHER_WORKFLOW,
    TENANT,
    WORKFLOW,
    PermissionFixture,
    direct_row,
)

BASE = f"/__mock__/kunlian/workflows/{WORKFLOW}"


async def test_manager_roster_and_viewer_actions_have_distinct_permissions():
    fixture = PermissionFixture()
    fixture.rows = [direct_row(scope="INHERITED"), direct_row(subject_type="user_group"), direct_row()]
    app, api = fixture.app()
    actual = [fixture.subject()]
    app.dependency_overrides[api.authorization_subject] = lambda: actual[0]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        page = await client.get(BASE + "/permissions", params={"limit": 1})
        assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"
        payload = page.json()["data"]
        assert payload["items"] == [] and payload["has_more"]
        assert (payload["resource_version"], payload["catalog_release_id"]) == (3, 12)
        assert payload["grantable_models"] == [{"key": "viewer"}]
        page = await client.get(BASE + "/permissions", params={"cursor": payload["next_cursor"]})
        rows = page.json()["data"]["items"]
        assert [row["editable"] for row in rows] == [False, True]
        assert "内部姓名" not in page.text
        actual[0] = fixture.subject(MEMBER)
        assert (await client.get(BASE + "/permissions")).status_code == 404
        assert (await client.get(BASE + "/my-permissions")).json()["data"] == {"actions": ["visible"]}


@pytest.mark.parametrize(
    "reason",
    ["unverified", "wrong_connection", "inactive", "actor", "other_workflow", "unknown", "revision", "projection"],
)
async def test_roster_fails_closed_without_partial_content(reason):
    fixture = PermissionFixture()
    fixture.rows = [direct_row()]
    app, api = fixture.app()
    subject = fixture.subject()
    expected = 404
    if reason == "unverified":
        expected = 401
    elif reason == "wrong_connection":
        subject = fixture.subject(connection_id="wrong")
    elif reason == "inactive":
        fixture.active_users.remove(ADMIN)
    elif reason == "actor":
        subject = fixture.subject(actor=PermissionActor(user_id=ADMIN + 1, tenant_id=TENANT, super_admin=True))
    elif reason == "unknown":
        fixture.known, expected = False, 503
    elif reason == "revision":
        fixture.page_callback, expected = lambda: setattr(fixture, "revision", 4), 409
    elif reason == "projection":
        fixture.current, expected = False, 503
    if reason != "unverified":
        app.dependency_overrides[api.authorization_subject] = lambda: subject
    resource = OTHER_WORKFLOW if reason == "other_workflow" else WORKFLOW
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get(f"/__mock__/kunlian/workflows/{resource}/permissions")
        assert response.status_code == expected
        assert response.json()["data"] is None
        assert response.headers["Cache-Control"] == "no-store"
        assert fixture.rows == [direct_row()]
