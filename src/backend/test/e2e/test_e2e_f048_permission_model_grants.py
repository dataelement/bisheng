"""Live E2E coverage for F048 permission-model Grants.

Prerequisites:
- ``F048_E2E=1`` explicitly enables this destructive-in-test-environment suite.
- The backend and its MySQL/Redis/OpenFGA dependencies are running.
- ``E2E_API_BASE`` points at the dedicated test deployment.
- The configured admin is a platform super administrator.
- A normal same-tenant user and a normal cross-tenant user are pre-provisioned.

The suite creates only ``e2e-f048-permission-*`` workflows and performs
prefix-scoped cleanup before and after the module.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

PREFIX = "e2e-f048-permission-"
E2E_ENABLED = os.environ.get("F048_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not E2E_ENABLED,
    reason="set F048_E2E=1 only against a dedicated F048 test deployment",
)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required when F048_E2E=1")
    return value


async def _cleanup_workflows(
    client: httpx.AsyncClient,
    token: str,
) -> None:
    """Delete only workflows created by this suite."""

    cursor: str | None = None
    for _ in range(100):
        params: dict[str, str | int] = {
            "name": PREFIX,
            "flow_type": 10,
            "page_size": 100,
        }
        if cursor:
            params["cursor"] = cursor
        response = await client.get(
            f"{API_BASE}/workflow/list",
            params=params,
            headers=auth_headers(token),
        )
        page = assert_resp_200(response)
        for item in page.get("data", []):
            if str(item.get("name", "")).startswith(PREFIX):
                delete_response = await client.delete(
                    f"{API_BASE}/flows/{item['id']}",
                    headers=auth_headers(token),
                )
                assert_resp_200(delete_response)
        if not page.get("has_more"):
            return
        cursor = page.get("next_cursor")
        if not cursor:
            pytest.fail("workflow cleanup returned has_more without next_cursor")
    pytest.fail("workflow cleanup exceeded 100 cursor pages")


async def _permission_context(
    client: httpx.AsyncClient,
    token: str,
    workflow_id: str,
) -> dict:
    response = await client.get(
        f"{API_BASE}/permissions/resources/workflow/{workflow_id}/context",
        headers=auth_headers(token),
    )
    return assert_resp_200(response)


async def _permission_roster(
    client: httpx.AsyncClient,
    token: str,
    workflow_id: str,
) -> list[dict]:
    response = await client.get(
        f"{API_BASE}/permissions/resources/workflow/{workflow_id}/grants",
        params={"page_size": 100},
        headers=auth_headers(token),
    )
    return assert_resp_200(response)["data"]


async def _check_action(
    client: httpx.AsyncClient,
    token: str,
    workflow_id: str,
    action: str,
) -> bool:
    response = await client.post(
        f"{API_BASE}/permissions/check",
        json={
            "resource_type": "workflow",
            "resource_id": workflow_id,
            "action": action,
        },
        headers=auth_headers(token),
    )
    return bool(assert_resp_200(response)["allowed"])


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(timeout=30.0) as value:
        yield value


@pytest.fixture(scope="module")
async def admin_token(client: httpx.AsyncClient) -> str:
    return await get_admin_token(client)


@pytest.fixture(scope="module")
async def normal_user(
    client: httpx.AsyncClient,
) -> tuple[str, str]:
    user_id = _required_env("F048_E2E_USER_ID")
    token = await get_user_token(
        client,
        _required_env("F048_E2E_USER_NAME"),
        _required_env("F048_E2E_USER_PASSWORD"),
    )
    return user_id, token


@pytest.fixture(scope="module")
async def cross_tenant_token(client: httpx.AsyncClient) -> str:
    return await get_user_token(
        client,
        _required_env("F048_E2E_CROSS_TENANT_USER_NAME"),
        _required_env("F048_E2E_CROSS_TENANT_USER_PASSWORD"),
    )


@pytest.fixture(scope="module", autouse=True)
async def prefix_cleanup(
    client: httpx.AsyncClient,
    admin_token: str,
):
    """Run prefix-scoped cleanup both before and after the suite."""

    await _cleanup_workflows(client, admin_token)
    yield
    await _cleanup_workflows(client, admin_token)


@pytest.fixture(scope="module")
async def workflow(
    client: httpx.AsyncClient,
    admin_token: str,
) -> dict:
    name = f"{PREFIX}{uuid4().hex[:12]}"
    response = await client.post(
        f"{API_BASE}/workflow/create",
        json={
            "name": name,
            "flow_type": 10,
            "data": {"nodes": [], "edges": []},
        },
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status_code"] == 200, f"Business error {body['status_code']}: {body.get('status_message')}"
    created = body["data"]

    get_response = await client.get(
        f"{API_BASE}/workflow/get_one_flow/{created['id']}",
        headers=auth_headers(admin_token),
    )
    persisted = assert_resp_200(get_response)
    assert persisted["name"] == name
    return created


class TestE2EF048PermissionModelGrants:
    """F048 live API and business-call-chain checks."""

    async def test_ac07_ac08_ac09_catalog_shape_and_access(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        normal_user: tuple[str, str],
    ) -> None:
        """AC-07/08/09: standard models are fixed and Catalog is super-only."""

        response = await client.get(
            f"{API_BASE}/permissions/catalog",
            headers=auth_headers(admin_token),
        )
        catalog = assert_resp_200(response)
        standards = {model["key"]: model for model in catalog["models"] if model["kind"] == "STANDARD"}
        assert set(standards) == {"viewer", "editor", "manager", "owner"}
        assert {key: model["derived_level"] for key, model in standards.items()} == {
            "viewer": 1,
            "editor": 2,
            "manager": 3,
            "owner": 4,
        }
        assert all(model["active"] for model in standards.values())

        _, user_token = normal_user
        denied = await client.get(
            f"{API_BASE}/permissions/catalog",
            headers=auth_headers(user_token),
        )
        assert denied.status_code == 200
        assert_resp_error(denied, 19000)

    async def test_ac44_ac58_ac61_protected_owner_and_context(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        workflow: dict,
    ) -> None:
        """AC-44/58/61: context and protected creator owner are explainable."""

        context = await _permission_context(
            client,
            admin_token,
            workflow["id"],
        )
        assert context["mode"] == "CUSTOM"
        assert context["parent_type"] is None
        assert context["parent_id"] is None
        assert context["can_manage_permission"] is True
        assert context["projection_state"] == "READY"

        roster = await _permission_roster(
            client,
            admin_token,
            workflow["id"],
        )
        protected_owners = [item for item in roster if item["protected"] and item["model"]["key"] == "owner"]
        assert protected_owners
        assert all(not item["editable"] for item in protected_owners)
        owner = protected_owners[0]

        denied = await client.post(
            (f"{API_BASE}/permissions/resources/workflow/{workflow['id']}/grants:mutate"),
            json={
                "idempotency_key": f"f048-owner-{uuid4().hex}",
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
                "changes": [
                    {
                        "op": "REMOVE",
                        "assignee_id": owner["assignee_id"],
                        "expected_assignee_version": owner["assignee_version"],
                    }
                ],
            },
            headers=auth_headers(admin_token),
        )
        assert denied.status_code == 200
        assert_resp_error(denied, 25006)

    async def test_ac25_ac28_ac29_ac33_ac43_ac69_grant_cycle(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        normal_user: tuple[str, str],
        workflow: dict,
    ) -> None:
        """AC-25/28/29/33/43/69: add, observe, deny, and revoke atomically."""

        user_id, user_token = normal_user
        context = await _permission_context(
            client,
            admin_token,
            workflow["id"],
        )
        idempotency_key = f"f048-add-{uuid4().hex}"
        add_body = {
            "idempotency_key": idempotency_key,
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
            "changes": [
                {
                    "op": "ADD",
                    "model_key": "viewer",
                    "subject": {
                        "type": "user",
                        "id": user_id,
                    },
                }
            ],
        }
        mutate_url = f"{API_BASE}/permissions/resources/workflow/{workflow['id']}/grants:mutate"
        first = await client.post(
            mutate_url,
            json=add_body,
            headers=auth_headers(admin_token),
        )
        first_data = assert_resp_200(first)
        repeated = await client.post(
            mutate_url,
            json=add_body,
            headers=auth_headers(admin_token),
        )
        assert assert_resp_200(repeated) == first_data

        assert await _check_action(
            client,
            user_token,
            workflow["id"],
            "visible",
        )
        assert not await _check_action(
            client,
            user_token,
            workflow["id"],
            "delete",
        )

        denied_roster = await client.get(
            (f"{API_BASE}/permissions/resources/workflow/{workflow['id']}/grants"),
            headers=auth_headers(user_token),
        )
        assert denied_roster.status_code == 200
        assert_resp_error(denied_roster, 19000)

        roster = await _permission_roster(
            client,
            admin_token,
            workflow["id"],
        )
        assignments = [
            item
            for item in roster
            if (
                item["subject"]["type"] == "user"
                and item["subject"]["id"] == user_id
                and item["model"]["key"] == "viewer"
                and not item["protected"]
            )
        ]
        assert len(assignments) == 1
        assignment = assignments[0]

        current = await _permission_context(
            client,
            admin_token,
            workflow["id"],
        )
        remove = await client.post(
            mutate_url,
            json={
                "idempotency_key": f"f048-remove-{uuid4().hex}",
                "expected_resource_version": current["resource_version"],
                "expected_catalog_release_id": current["catalog_release_id"],
                "changes": [
                    {
                        "op": "REMOVE",
                        "assignee_id": assignment["assignee_id"],
                        "expected_assignee_version": assignment["assignee_version"],
                    }
                ],
            },
            headers=auth_headers(admin_token),
        )
        assert_resp_200(remove)
        assert not await _check_action(
            client,
            user_token,
            workflow["id"],
            "visible",
        )

    async def test_ac35_cross_tenant_resource_is_not_resolved(
        self,
        client: httpx.AsyncClient,
        cross_tenant_token: str,
        workflow: dict,
    ) -> None:
        """AC-35: a cross-tenant actor cannot resolve the business target."""

        response = await client.post(
            f"{API_BASE}/permissions/check",
            json={
                "resource_type": "workflow",
                "resource_id": workflow["id"],
                "action": "visible",
            },
            headers=auth_headers(cross_tenant_token),
        )
        assert response.status_code == 200
        assert_resp_error(response, 19003)

    async def test_ac48_top_level_workflow_cannot_inherit(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        workflow: dict,
    ) -> None:
        """AC-48: a resource without a canonical parent rejects INHERIT."""

        context = await _permission_context(
            client,
            admin_token,
            workflow["id"],
        )
        response = await client.post(
            (f"{API_BASE}/permissions/resources/workflow/{workflow['id']}/mode-drafts"),
            json={
                "target_mode": "INHERIT",
                "expected_resource_version": context["resource_version"],
                "expected_catalog_release_id": context["catalog_release_id"],
            },
            headers=auth_headers(admin_token),
        )
        assert response.status_code == 200
        assert_resp_error(response, 25007)

    async def test_ac02_invalid_action_is_fail_closed(
        self,
        client: httpx.AsyncClient,
        admin_token: str,
        workflow: dict,
    ) -> None:
        """AC-02: an unknown action is unavailable and fails closed."""

        response = await client.post(
            f"{API_BASE}/permissions/check",
            json={
                "resource_type": "workflow",
                "resource_id": workflow["id"],
                "action": "e2e_unknown_action",
            },
            headers=auth_headers(admin_token),
        )
        assert response.status_code == 200
        assert_resp_error(response, 25001)
