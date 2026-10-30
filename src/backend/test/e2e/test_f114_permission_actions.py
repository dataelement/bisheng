"""Opt-in F114 smoke against an isolated, already published e2e-f114 app.

F114_E2E=1, E2E_API_BASE, F114_APP_ID, F114_TENANT_ID, and four in-memory
tokens F114_EDITOR_TOKEN, F114_PUBLISHER_TOKEN, F114_USE_TOKEN,
F114_FOREIGN_TOKEN. These are dedicated non-admin users, pre-granted exact
F048 actions. The editor has edit only, the publisher publish only, the user
use only, and the foreign actor belongs to another tenant. Credentials never
enter fixtures, reports or Git. Only E2E_F114_TEMP is changed and cleaned.
New application/user provisioning is outside this smoke and must be separately
authorized; it reuses the same seeded-environment approach as F056 closeout.
"""

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(
    os.environ.get("F114_E2E") != "1", reason="requires deployed F114 and isolated e2e-f114 fixture"
)
KEY = "E2E_F114_TEMP"


@pytest.fixture
async def target():
    app_id = os.environ["F114_APP_ID"]
    tenant = int(os.environ["F114_TENANT_ID"])
    headers = {
        kind: auth_headers(os.environ[f"F114_{kind.upper()}_TOKEN"])
        for kind in ["editor", "publisher", "use", "foreign"]
    }
    async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=headers["editor"]))
        assert app["tenant_id"] == tenant and app["slug"].startswith("e2e-f114-")
        for value in headers.values():
            value["X-Management-Tenant"] = str(tenant)

        async def cleanup():
            config = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}/secrets", headers=headers["editor"]))
            if any(row["name"] == KEY and row["present"] for row in config["items"]):
                assert_resp_200(
                    await client.request(
                        "DELETE",
                        f"{API_BASE}/apps/{app_id}/secrets/{KEY}",
                        headers=headers["editor"],
                        json={"expected_revision": config["revision"], "confirm_online_impact": True},
                    )
                )

        await cleanup()
        try:
            yield client, headers, app_id, tenant
        finally:
            await cleanup()


async def test_management_summary_and_private_content_pair(target):
    """AC-06、AC-07、AC-21、AC-24、AC-61: publish-only sees metadata, never private settings."""
    client, h, app_id, _ = target
    data = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=h["publisher"]))
    assert "publish" in data["allowed_actions"] and "edit" not in data["allowed_actions"]
    assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}/secrets", headers=h["editor"]))
    assert_resp_error(await client.get(f"{API_BASE}/apps/{app_id}/secrets", headers=h["publisher"]), 19000)
    assert_resp_error(await client.get(f"{API_BASE}/apps/{app_id}", headers=h["use"]), 19000)
    assert_resp_error(await client.get(f"{API_BASE}/apps/{app_id}", headers=h["foreign"]), 16101)


async def test_edit_save_does_not_restart_and_cannot_rebuild_without_publish(target):
    """AC-24、AC-25、AC-26、AC-65: one masked setting; same serving operation and combined-action refusal."""
    client, h, app_id, _tenant = target
    before = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}/secrets", headers=h["editor"]))
    assert_resp_200(
        await client.put(
            f"{API_BASE}/apps/{app_id}/secrets/{KEY}",
            headers=h["editor"],
            json={"expected_revision": before["revision"], "value": "e2e-not-a-real-secret"},
        )
    )
    after = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}/secrets", headers=h["editor"]))
    assert (
        after["revision"] > before["revision"]
        and after["runtime"]["running_version_id"] == before["runtime"]["running_version_id"]
    )
    assert after["runtime"]["route_epoch"] == before["runtime"]["route_epoch"]
    assert "e2e-not-a-real-secret" not in str(after)
    runtime = after["runtime"]
    assert_resp_error(
        await client.post(
            f"{API_BASE}/apps/{app_id}/secrets/rebuild",
            headers=h["editor"],
            json={
                "request_id": "e2e-f114-no-publish",
                "expected_version_id": runtime["running_version_id"],
                "expected_config_revision": after["revision"],
                "expected_route_epoch": runtime["route_epoch"],
                "confirm_restart": True,
            },
        ),
        19000,
    )


async def test_old_scope_form_is_rejected_before_mutation(target):
    """AC-16、AC-17: a stale management form cannot change another tenant's resource."""
    client, h, app_id, tenant = target
    before = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=h["editor"]))
    response = await client.patch(
        f"{API_BASE}/apps/{app_id}",
        headers={**h["editor"], "X-Management-Tenant": str(tenant + 1000000)},
        json={"description": "must not be written"},
    )
    assert_resp_error(response, 19704)
    after = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=h["editor"]))
    assert after["description"] == before["description"]
