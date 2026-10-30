"""Read-only /info checks against an explicitly selected upgraded test deployment.

Existing, published fixtures and ephemeral tokens are supplied by the operator.
No users, spaces, permissions, or files are created/deleted by this suite.
See F079's e2e-checklist.md for the case-map contract and execution limits.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("COFCO_INFO_E2E") != "1", reason="requires an upgraded dedicated COFCO deployment"
    ),
]
CASES = (
    ("member", True, "subscribed", "ordinary", 200),
    ("department_grant", True, "subscribed", "ordinary", 200),
    ("pending_visible", True, "subscribed", "ordinary", 200),
    ("rejected_visible", True, "subscribed", "ordinary", 200),
    ("preview_not_joined", False, "not_subscribed", "ordinary", 200),
    ("preview_pending", False, "pending", "ordinary", 200),
    ("preview_rejected", False, "rejected", "ordinary", 200),
    ("creator", True, "subscribed", "ordinary", 200),
    ("super_admin_not_joined", True, "not_subscribed", "super_admin", 200),
    ("private_denied", False, None, "ordinary", 18040),
    ("cross_tenant_denied", False, None, "ordinary", 18000),
)


@pytest.mark.parametrize("case_name,visible,subscription_status,identity_type,expected_code", CASES)
async def test_ac01_to_ac05_live_info_contract(case_name, visible, subscription_status, identity_type, expected_code):
    """AC-01..05: real identity, access hint, subscription, and button summary."""
    assert os.environ.get("E2E_API_BASE"), "explicit E2E_API_BASE is required"
    cases = json.loads(os.environ["COFCO_INFO_E2E_CASES"])
    case = cases[case_name]
    assert case["data_prefix"].startswith("e2e-cofco-info-")
    token = os.environ[case["token_env"]]
    headers = auth_headers(token)

    async with httpx.AsyncClient(timeout=30.0) as client:
        identity = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
        if identity_type == "ordinary":
            assert identity["role"] != "admin"
            assert identity["is_global_super"] is False
            assert identity["is_child_admin"] is False
        elif identity_type == "super_admin":
            assert identity["is_global_super"] is True or identity["role"] == "admin"
        else:
            raise AssertionError("identity must be ordinary or super_admin")

        space_id = int(case["space_id"])
        response = await client.get(f"{API_BASE}/knowledge/space/{space_id}/info", headers=headers)
        if expected_code != 200:
            assert_resp_error(response, expected_code)
            return

        info = assert_resp_200(response)
        assert info["name"].startswith(case["data_prefix"])
        assert info["state"] == 1, "only pre-provisioned published spaces may be used"
        assert info["actions"] == (["visible"] if visible else [])
        assert info["subscription_status"] == subscription_status
        assert info["is_followed"] is (subscription_status == "subscribed")
        assert info["is_pending"] is (subscription_status == "pending")
        assert isinstance(info["download_action_enabled"], bool)
        if visible:
            summary = assert_resp_200(
                await client.get(
                    f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/my-permissions",
                    headers=headers,
                )
            )
            assert set(case["expected_button_actions"]) <= set(summary["actions"])
