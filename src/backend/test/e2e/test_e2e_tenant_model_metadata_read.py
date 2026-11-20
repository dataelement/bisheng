"""Opt-in, read-only deployment checks using dedicated, pre-provisioned fixtures.

This suite never creates users/data, changes model status, or recovers tasks.
Operators provide selected-management-view headers and ephemeral auth through env.
See F023 e2e-checklist.md for case-map requirements and write/UI acceptance.
"""

import json
import os
from urllib.parse import quote

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("TENANT_METADATA_E2E") != "1", reason="requires an upgraded dedicated deployment"
    ),
]


@pytest.mark.parametrize("case_name", ["roles_super", "roles_admin", "assistant_user", "tools_super", "tools_user"])
async def test_deployed_read_contract(case_name):
    """AC-01/02/03/04: selected-view roles, configured models, and permitted tools."""
    assert os.environ.get("E2E_API_BASE"), "an explicit test deployment is required"
    case = json.loads(os.environ["TENANT_METADATA_E2E_CASES"])[case_name]
    assert case["data_prefix"].startswith("e2e-tenant-metadata-")
    token = os.environ[case["token_env"]]
    headers = auth_headers(token)
    if case.get("headers_env"):
        # Includes only the test account's already-selected view cookie/target header.
        extra = json.loads(os.environ[case["headers_env"]])
        assert "Authorization" not in extra
        if "Cookie" in extra:
            headers["Cookie"] += "; " + extra.pop("Cookie")
        headers.update(extra)
    async with httpx.AsyncClient(timeout=30) as client:
        if case_name.startswith("roles_"):
            data = assert_resp_200(
                await client.get(
                    f"{API_BASE}/departments/{quote(case['department_id'], safe='')}/members",
                    params={"page": 1, "limit": 100},
                    headers=headers,
                )
            )
            member = next(row for row in data["data"] if row["user_id"] == case["user_id"])
            assert member["user_name"].startswith(case["data_prefix"])
            assert {row["id"] for row in member["roles"]} == set(case["role_ids"])
            if case_name == "roles_super":
                assert {row["reason"] for row in member["role_binding_issues"]} == set(case["issue_reasons"])
            else:
                assert "role_binding_issues" not in member
        elif case_name == "assistant_user":
            data = assert_resp_200(await client.get(f"{API_BASE}/llm/assistant/llm_list", headers=headers))
            models = [model for provider in data for model in provider["models"] if model["online"]]
            assert [row["id"] for row in models] == case["online_model_ids"]
            assert all(row["model_name"].startswith(case["data_prefix"]) for row in models)
        else:
            data = assert_resp_200(await client.get(f"{API_BASE}/tool", headers=headers))
            assert {row["id"] for row in data} == set(case["visible_tool_type_ids"])
