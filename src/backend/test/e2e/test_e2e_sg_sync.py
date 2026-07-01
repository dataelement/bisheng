"""E2E tests for SG sync endpoints against a deployed backend.

Exercises three remote callbacks in order:
1. ``POST /api/v1/departments/sg-sync`` — organization sync
2. ``POST /api/v1/users/sg-sync`` — user sync
3. ``POST /api/v1/users/sg-sso-sync`` — SSO account / guid sync

Prerequisites:
- Backend running with SG sync routes deployed.
- ``sso_sync.gateway_hmac_secret`` configured on the server (non-empty).
- Override target via ``E2E_API_BASE`` (default ``http://localhost:7860/api/v1``).
- Set ``E2E_SG_HEADER_SECRET`` (or ``E2E_HMAC_SECRET``) to the same secret value.
- Optional: ``E2E_ADMIN_PASSWORD`` for post-sync verification via admin APIs.

When the backend is unreachable, routes return 404, or the header secret is
unset, tests in this module are skipped so a plain ``pytest test/e2e`` run
stays green.

Data isolation: all synced entities use the ``e2e-sg-`` prefix generated per
module run; no bulk cleanup is performed (archive/disable only when explicitly
tested).
"""

from __future__ import annotations

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE
from test.e2e.helpers.sg_sync import (
    DEPTS_SG_PATH,
    HEADER_SECRET,
    SSO_SG_PATH,
    USERS_SG_PATH,
    assert_auth_rejected,
    assert_esb_partial_failure,
    assert_esb_success,
    assert_sso_success,
    build_department_payload,
    build_sso_account_payload,
    build_user_payload,
    new_run_prefix,
    post_sg,
)

HEALTH_URL = API_BASE.replace("/api/v1", "") + "/health"

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_SKIP", "0") == "1",
    reason="E2E tests skipped (E2E_SKIP=1)",
)


@pytest.fixture(scope="module")
def sg_client():
    """HTTP client with backend availability + SG route feature gate."""
    client = httpx.Client(base_url=API_BASE, timeout=60)
    try:
        health = client.get(HEALTH_URL)
        if health.status_code != 200:
            pytest.skip("Backend not running (health != 200)")
    except httpx.ConnectError:
        pytest.skip(f"Backend not reachable at {HEALTH_URL}")

    if not HEADER_SECRET:
        pytest.skip(
            "E2E_SG_HEADER_SECRET (or E2E_HMAC_SECRET) not set; must match server sso_sync.gateway_hmac_secret.",
        )

    probe = post_sg(
        client,
        DEPTS_SG_PATH,
        {
            "mdmId": 1,
            "BusinessSystem": 1,
            "uuid": "probe",
            "Field": [],
        },
    )
    if probe.status_code == 404:
        pytest.skip("SG department sync route not deployed (404)")
    probe_body = probe.json()
    if probe_body.get("status_code") == 19301:
        pytest.skip(
            "SG header secret mismatch (19301); check E2E_SG_HEADER_SECRET",
        )

    yield client
    client.close()


@pytest.fixture(scope="module")
def run_id() -> str:
    return new_run_prefix()


@pytest.fixture(scope="module")
def sg_context(run_id: str) -> dict:
    """Shared codes produced by the ordered sync flow."""
    return {
        "run_id": run_id,
        "parent_dept_code": f"{run_id}-root",
        "child_dept_code": f"{run_id}-child",
        "user_code": f"{run_id}-u1",
        "user_name": f"E2E SG User {run_id}",
        "guid": "",
    }


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


class TestSgSyncAuthGate:
    """Fixed-header dependency must reject missing / invalid secrets."""

    def test_missing_header_rejected(self, sg_client):
        resp = sg_client.post(
            DEPTS_SG_PATH,
            json={"mdmId": 1, "BusinessSystem": 1, "Field": []},
        )
        assert_auth_rejected(resp)

    def test_invalid_header_rejected(self, sg_client):
        resp = post_sg(
            sg_client,
            DEPTS_SG_PATH,
            {"mdmId": 1, "BusinessSystem": 1, "Field": []},
            secret="definitely-not-the-server-secret",
        )
        assert_auth_rejected(resp)


# ---------------------------------------------------------------------------
# Organization sync
# ---------------------------------------------------------------------------


class TestSgDepartmentSyncRemote:
    """Remote organization sync — parent then child department."""

    def test_sync_root_department(self, sg_client, run_id, sg_context):
        payload = build_department_payload(
            run_id=run_id,
            dept_suffix="root",
            name=f"E2E SG Root {run_id}",
        )
        resp = post_sg(sg_client, DEPTS_SG_PATH, payload)
        assert resp.status_code == 200, resp.text[:500]
        rows = assert_esb_success(resp.json())
        assert rows[0]["code"] == sg_context["parent_dept_code"]

    def test_sync_child_department(self, sg_client, run_id, sg_context):
        payload = build_department_payload(
            run_id=run_id,
            dept_suffix="child",
            parent_code=sg_context["parent_dept_code"],
            name=f"E2E SG Child {run_id}",
        )
        resp = post_sg(sg_client, DEPTS_SG_PATH, payload)
        assert resp.status_code == 200
        rows = assert_esb_success(resp.json())
        assert rows[0]["code"] == sg_context["child_dept_code"]

    def test_invalid_row_returns_partial_failure(self, sg_client, run_id):
        payload = {
            "mdmId": 9002,
            "BusinessSystem": 1,
            "uuid": f"{run_id}-bad-batch",
            "Field": [
                {
                    "uuid": f"{run_id}-bad",
                    "code": "",
                    "pid": "",
                    "remark": "invalid",
                    "state": "01",
                },
            ],
        }
        resp = post_sg(sg_client, DEPTS_SG_PATH, payload)
        assert resp.status_code == 200
        rows = assert_esb_partial_failure(resp.json())
        assert "code is required" in rows[0].get("errorText", "")


# ---------------------------------------------------------------------------
# User sync
# ---------------------------------------------------------------------------


class TestSgUserSyncRemote:
    """Remote user sync — depends on departments created above."""

    def test_sync_on_job_user(self, sg_client, run_id, sg_context):
        payload = build_user_payload(
            run_id=run_id,
            dept_code=sg_context["child_dept_code"],
            user_suffix="u1",
            display_name=sg_context["user_name"],
            job_status="01",
        )
        resp = post_sg(sg_client, USERS_SG_PATH, payload)
        assert resp.status_code == 200, resp.text[:500]
        rows = assert_esb_success(resp.json())
        assert rows[0]["code"] == sg_context["user_code"]

    # def test_sync_off_job_user(self, sg_client, run_id, sg_context):
    #     payload = build_user_payload(
    #         run_id=run_id,
    #         dept_code=sg_context['child_dept_code'],
    #         user_suffix='u1',
    #         display_name=sg_context['user_name'],
    #         job_status='02',
    #     )
    #     resp = post_sg(sg_client, USERS_SG_PATH, payload)
    #     assert resp.status_code == 200
    #     assert_esb_success(resp.json())

    def test_missing_department_returns_partial_failure(self, sg_client, run_id):
        payload = build_user_payload(
            run_id=run_id,
            dept_code=f"{run_id}-missing-dept",
            user_suffix="ghost",
        )
        resp = post_sg(sg_client, USERS_SG_PATH, payload)
        assert resp.status_code == 200
        rows = assert_esb_partial_failure(resp.json())
        assert "department external_id=" in rows[0].get("errorText", "")


# ---------------------------------------------------------------------------
# SSO account sync
# ---------------------------------------------------------------------------


class TestSgSsoAccountSyncRemote:
    """Remote SSO account sync — bind guid to synced user."""

    def test_sync_account_without_guid_generates_guid(
        self,
        sg_client,
        sg_context,
    ):
        payload = build_sso_account_payload(
            person_no=sg_context["user_code"],
            user_name=sg_context["user_name"],
            guid="",
        )
        resp = post_sg(sg_client, SSO_SG_PATH, payload)
        assert resp.status_code == 200, resp.text[:500]
        rows = assert_sso_success(resp.json())
        assert rows[0]["Guid"]
        sg_context["guid"] = rows[0]["Guid"]

    def test_sync_account_with_existing_guid(
        self,
        sg_client,
        sg_context,
    ):
        assert sg_context["guid"], "previous test must provide guid"
        updated_name = f"{sg_context['user_name']} Updated"
        payload = build_sso_account_payload(
            person_no=sg_context["user_code"],
            user_name=updated_name,
            guid=sg_context["guid"],
        )
        resp = post_sg(sg_client, SSO_SG_PATH, payload)
        assert resp.status_code == 200
        rows = assert_sso_success(resp.json())
        assert rows[0]["Guid"] == sg_context["guid"]
        assert rows[0]["UserName"] == updated_name
        sg_context["user_name"] = updated_name

    def test_unknown_person_returns_failure_row(self, sg_client, run_id):
        payload = build_sso_account_payload(
            person_no=f"{run_id}-nobody",
            user_name="Nobody",
            guid="",
        )
        resp = post_sg(sg_client, SSO_SG_PATH, payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["TIEM"][0]["Result"] == "1"
        assert "user not found" in body["TIEM"][0]["Description"]
