"""Opt-in F055 live handoff. Requires an approved e2e-f055-* app and synthetic probe.

F055_E2E=1, E2E_API_BASE, F055_E2E_APP_ID, F055_E2E_TENANT_ID,
F055_E2E_OWNER_TOKEN, F055_E2E_NONOWNER_TOKEN, F055_E2E_FOREIGN_TOKEN.
App manifest must declare F055_TEST_COLOR. Use the same suite against Docker and K8s.
Only the suite variable is removed; application and persistent data are retained.
"""

import asyncio
import os
import time
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = pytest.mark.skipif(
    os.getenv("F055_E2E") != "1", reason="requires deployed F055 dedicated test application"
)
NAME = "F055_TEST_COLOR"


@pytest.fixture
async def journey():
    app_id = os.environ["F055_E2E_APP_ID"]
    tenant_id = int(os.environ["F055_E2E_TENANT_ID"])
    headers = auth_headers(os.environ["F055_E2E_OWNER_TOKEN"])
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        app = assert_resp_200(await client.get(f"{API_BASE}/apps/{app_id}", headers=headers))
        assert app["slug"].startswith("e2e-f055-") and app["tenant_id"] == tenant_id
        assert app["state"] == "online"
        url = f"{API_BASE}/apps/{app_id}/secrets"
        initial = assert_resp_200(await client.get(url, headers=headers))
        declaration = next(item for item in initial["items"] if item["name"] == NAME)
        assert declaration["approved_reference"]
        if declaration["present"]:
            assert_resp_200(
                await client.request(
                    "DELETE",
                    f"{url}/{NAME}",
                    headers=headers,
                    json={"expected_revision": initial["revision"], "confirm_online_impact": True},
                )
            )
        try:
            yield client, app, url, headers
        finally:
            latest = assert_resp_200(await client.get(url, headers=headers))
            if any(item["name"] == NAME and item["present"] for item in latest["items"]):
                assert_resp_200(
                    await client.request(
                        "DELETE",
                        f"{url}/{NAME}",
                        headers=headers,
                        json={"expected_revision": latest["revision"], "confirm_online_impact": True},
                    )
                )


async def test_save_confirm_and_rebuild(journey):
    """AC-67, AC-70, AC-73, AC-74, AC-76, AC-90, AC-91, AC-92: save and explicit same-version apply."""
    client, app, url, headers = journey
    for desired, marker in [("e2e-before", "before"), ("e2e-after", "after")]:
        previous = assert_resp_200(await client.get(url, headers=headers))
        response = await client.put(
            f"{url}/{NAME}", headers=headers, json={"value": desired, "expected_revision": previous["revision"]}
        )
        changed = assert_resp_200(response)
        assert "operation_id" not in changed and desired not in response.text
        saved = assert_resp_200(await client.get(url, headers=headers))
        assert saved["runtime"]["running_operation_id"] == previous["runtime"]["running_operation_id"]
        assert saved["runtime"]["comparison"] == "different"
        request = {
            "request_id": uuid4().hex,
            "expected_version_id": saved["runtime"]["running_version_id"],
            "expected_config_revision": saved["revision"],
            "expected_route_epoch": saved["runtime"]["route_epoch"],
            "confirm_restart": True,
        }
        accepted = assert_resp_200(await client.post(f"{url}/rebuild", headers=headers, json=request))
        replay = assert_resp_200(await client.post(f"{url}/rebuild", headers=headers, json=request))
        assert replay["operation_id"] == accepted["operation_id"]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            current = assert_resp_200(await client.get(url, headers=headers))
            operation = current["runtime"]["rebuild_operation"]
            assert not operation or operation["status"] not in {"failed", "cancelled", "timed_out"}
            if (
                current["runtime"]["running_operation_id"] == accepted["operation_id"]
                and current["runtime"]["comparison"] == "same"
                and operation["status"] == "completed"
            ):
                break
            await asyncio.sleep(2)
        else:
            pytest.fail("confirmed rebuild did not complete")
        probe = await client.get(app["entry_url"].rstrip("/") + "/__f055_probe", headers=headers)
        assert probe.status_code == 200 and probe.json()[marker] is True
        final = assert_resp_200(await client.get(f"{API_BASE}/apps/{app['app_id']}", headers=headers))
        assert final["current_version_id"] == app["current_version_id"]
        assert final["pending_version_id"] == app["pending_version_id"]


async def test_nonowner_and_foreign_tenant_cannot_manage(journey):
    """AC-66, AC-85, AC-89: pair the owner journey with nonowner/cross-tenant refusal."""
    client, _app, url, _headers = journey
    for name in ["F055_E2E_NONOWNER_TOKEN", "F055_E2E_FOREIGN_TOKEN"]:
        response = await client.put(
            f"{url}/{NAME}", headers=auth_headers(os.environ[name]), json={"value": "e2e-after", "expected_revision": 0}
        )
        assert_resp_error(response, 16254)
