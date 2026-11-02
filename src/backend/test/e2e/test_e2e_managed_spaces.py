"""Opt-in read-only F116 contracts against an upgraded dedicated deployment.

Fixtures and temporary identity tokens must already exist. This suite neither
deploys code nor creates users, grants, spaces, or files.
"""

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("MANAGED_SPACES_E2E") != "1", reason="requires an upgraded dedicated release-line deployment"
    ),
]


@pytest.mark.parametrize("identity", ["ordinary", "super_admin", "restricted_super_admin"])
async def test_ac01_ac04_ac05_live_managed_contract(identity):
    """AC-01/04/05: real identities, expected fixture inclusion, fields and pins."""
    assert os.environ.get("E2E_API_BASE"), "explicit E2E_API_BASE is required"
    case = json.loads(os.environ["MANAGED_SPACES_E2E_CASES"])[identity]
    assert case["data_prefix"].startswith("e2e-managed-spaces-")
    assert case["fixtures"], "fixture assertions must not be empty"
    expected_tenant = int(case["tenant_id"])
    assert expected_tenant > 0
    headers = auth_headers(os.environ[case["token_env"]])
    async with httpx.AsyncClient(timeout=60.0) as client:
        user = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers))
        if identity == "ordinary":
            assert user["role"] != "admin"
            assert user["is_global_super"] is False and user["is_child_admin"] is False
        else:
            assert user["is_global_super"] is True or user["role"] == "admin"
        rows = assert_resp_200(
            await client.get(f"{API_BASE}/knowledge/space/managed", params={"order_by": "name"}, headers=headers)
        )
        assert isinstance(rows, list)
        assert len({row["id"] for row in rows}) == len(rows)
        # Legacy /user/info can report a null tenant_id; fixtures explicitly
        # declare the expected current tenant instead of trusting that field.
        if user.get("tenant_id") is not None:
            assert user["tenant_id"] == expected_tenant
        assert all(row["tenant_id"] == expected_tenant for row in rows)
        assert [row["is_pinned"] for row in rows] == sorted((row["is_pinned"] for row in rows), reverse=True)
        by_id = {row["id"]: row for row in rows}
        for fixture in case["fixtures"]:
            space_id = int(fixture["space_id"])
            assert (space_id in by_id) is fixture["included"], fixture["case_name"]
            if not fixture["included"]:
                continue
            row = by_id[space_id]
            assert row["name"].startswith(case["data_prefix"])
            assert row["user_role"] == fixture["user_role"]
            assert row["is_pinned"] is fixture["is_pinned"]
            assert isinstance(row["file_num"], int)
            summary = assert_resp_200(
                await client.get(
                    f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/my-permissions", headers=headers
                )
            )
            assert "edit" in summary["actions"]
