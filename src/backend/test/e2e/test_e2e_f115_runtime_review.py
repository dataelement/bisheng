"""Opt-in F115 journeys against a deployed platform, never mocks.

Use only dedicated e2e-f115 people/app/tenant fixtures. Credentials are supplied
in environment variables and remain in memory. The selected management scope
must already match F115_E2E_TENANT; this suite never changes a global scope.
Creation writes are disabled unless F115_E2E_ALLOW_CREATE=1 is also explicit.
"""

import os
from dataclasses import dataclass, field

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers
from test.e2e.helpers.cleanup import cleanup_exact_test_library

pytestmark = pytest.mark.skipif(
    os.environ.get("F115_E2E") != "1", reason="requires deployed F115 and dedicated fixtures"
)


@dataclass
class Target:
    client: httpx.AsyncClient = field(repr=False)
    reader: dict = field(repr=False)
    foreign: dict = field(repr=False)
    tenant_admin: dict = field(repr=False)
    ordinary: dict = field(repr=False)
    tenant_id: int
    app_id: str
    task_id: int
    instance_id: int


@pytest.fixture
async def target():
    async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False) as client:
        result = Target(
            client=client,
            reader=auth_headers(os.environ["F115_E2E_APPROVER_TOKEN"]),
            foreign=auth_headers(os.environ["F115_E2E_FOREIGN_TOKEN"]),
            tenant_admin=auth_headers(os.environ["F115_E2E_TENANT_ADMIN_TOKEN"]),
            ordinary=auth_headers(os.environ["F115_E2E_NO_CREATE_TOKEN"]),
            tenant_id=int(os.environ["F115_E2E_TENANT"]),
            app_id=os.environ["F115_E2E_APP_ID"],
            task_id=int(os.environ["F115_E2E_TASK_ID"]),
            instance_id=int(os.environ["F115_E2E_INSTANCE_ID"]),
        )
        for headers in (result.reader, result.foreign, result.tenant_admin, result.ordinary):
            identity = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
            assert identity["user_name"].startswith("e2e-f115-")
            if headers == result.ordinary:
                assert identity.get("role") != "admin" and not identity.get("is_child_admin")
                assert "create_knowledge" not in identity.get("web_menu", [])
            if headers == result.tenant_admin:
                assert identity.get("is_child_admin") and identity.get("leaf_tenant_id") == result.tenant_id
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{result.app_id}", headers=result.tenant_admin))
        assert app["tenant_id"] == result.tenant_id and app["name"].startswith("e2e-f115-")
        yield result


async def test_instance_is_current_and_nullable(target):
    """AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-52."""
    data = assert_resp_200(
        await target.client.get(f"{API_BASE}/apps/{target.app_id}/instance", headers=target.tenant_admin)
    )
    assert data["observation_state"] in {"current", "no_execution", "execution_missing"}
    count = data["restart_count"]
    assert count is None or (type(count) is int and count >= 0)
    if data["observation_state"] != "current":
        assert data["started_at"] is None and count is None


async def test_approval_current_scope_and_foreign_denial(target):
    """AC-22, AC-23, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38, AC-52."""
    paths = (f"/approval/my-tasks/{target.task_id}", f"/approval/instances/{target.instance_id}")
    for path in paths:
        data = assert_resp_200(await target.client.get(API_BASE + path, headers=target.reader))
        assert data["current_visibility"]["state"] == "available"
        assert "detail_snapshot" in data and "payload_snapshot" in data
        assert_resp_error(await target.client.get(API_BASE + path, headers=target.foreign), 18101)


async def test_model_candidates_preserve_real_people(target):
    """AC-11, AC-13, AC-14, AC-15, AC-16, AC-52: a prepared real-person call is selectable."""
    data = assert_resp_200(
        await target.client.get(
            f"{API_BASE}/app-runtime-audit/candidates/visitor",
            headers=target.tenant_admin,
            params={"kind": "model", "app_id": target.app_id, "time_range": "all", "tenant_id": target.tenant_id},
        )
    )
    assert all(str(item["id"]).isdigit() and item["label"] for item in data["items"])
    assert any(str(item["id"]) == os.environ["F115_E2E_VISITOR_ID"] for item in data["items"])


@pytest.mark.parametrize("kind", [0, 1])
async def test_tenant_admin_creation_and_old_form_denial(target, kind):
    """AC-39, AC-40, AC-42, AC-43, AC-45, AC-52.

    Remaining role-change/copy pairings are explicit in the UI/operator checklist.
    """
    if os.environ.get("F115_E2E_ALLOW_CREATE") != "1":
        pytest.skip("knowledge creation requires explicit write authorization")
    name = f"e2e-f115-kb-{target.tenant_id}-{kind}"
    owner_id = int(os.environ["F115_E2E_TENANT_ADMIN_ID"])
    await cleanup_exact_test_library(
        target.client, target.tenant_admin, name=name, kind=kind, tenant_id=target.tenant_id, owner_id=owner_id
    )
    payload = {
        "name": name,
        "type": kind,
        "model": os.environ["F115_E2E_EMBEDDING_ID"],
        "expected_tenant_id": target.tenant_id,
    }
    # Both rejection checks precede the only write; no historical resource is touched.
    wrong = {**payload, "expected_tenant_id": int(os.environ["F115_E2E_FOREIGN_TENANT"])}
    assert_resp_error(
        await target.client.post(f"{API_BASE}/knowledge/create", headers=target.tenant_admin, json=wrong), 10993
    )
    assert_resp_error(
        await target.client.post(f"{API_BASE}/knowledge/create", headers=target.ordinary, json=payload), 403
    )
    data = assert_resp_200(
        await target.client.post(f"{API_BASE}/knowledge/create", headers=target.tenant_admin, json=payload)
    )
    try:
        assert data["tenant_id"] == target.tenant_id and data["name"] == name and data["user_id"] == owner_id
        rows = assert_resp_200(
            await target.client.get(
                f"{API_BASE}/knowledge/info", headers=target.tenant_admin, params={"knowledge_id": data["id"]}
            )
        )
        assert any(row["id"] == data["id"] and row["name"] == name for row in rows)
    finally:
        await cleanup_exact_test_library(
            target.client, target.tenant_admin, name=name, kind=kind, tenant_id=target.tenant_id, owner_id=owner_id
        )
