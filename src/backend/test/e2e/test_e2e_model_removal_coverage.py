"""Opt-in existing-environment precheck acceptance; never submits a deletion.

Set E2E_MODEL_COVERAGE=1, E2E_MODEL_SERVER_IDS and E2E_API_BASE. Uses the
shared authentication helpers and compares the full visible model inventory.
Only expiring confirmation plans are created; no test business resources exist.
"""

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("E2E_MODEL_COVERAGE") != "1", reason="requires explicit environment opt-in"),
]


class TestE2EModelRemovalCoverage:
    async def test_ac89_model_removal_prechecks_complete_without_changing_models(self):
        """AC-89: complete reference prechecks return plans and preserve configured models."""
        ids = [int(value) for value in os.environ["E2E_MODEL_SERVER_IDS"].split(",")]
        assert ids
        tenant = os.environ.get("E2E_MODEL_TENANT", "1")
        async with httpx.AsyncClient(timeout=60) as client:
            headers = {**auth_headers(await get_admin_token(client)), "X-Management-Tenant": tenant}
            before = assert_resp_200(await client.get(f"{API_BASE}/llm", headers=headers))
            assert set(ids) <= {server["id"] for server in before}
            for server_id in ids:
                result = assert_resp_200(
                    await client.post(
                        f"{API_BASE}/llm/server-removal-plan", headers=headers, json={"server_id": server_id}
                    )
                )
                inspection = result["inspection"]
                assert inspection["check_complete"] is True
                assert inspection["coverage_epoch"] > 0
                assert result["confirmation"]
            after = assert_resp_200(await client.get(f"{API_BASE}/llm", headers=headers))
            assert before == after
