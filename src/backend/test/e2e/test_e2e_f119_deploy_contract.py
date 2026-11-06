"""Opt-in F119 deployed diagnostic checks; all resources are preseeded and read-only.

F119_E2E=1 requires dedicated e2e-f119 ordinary users, an application with a
retained failed operation, and the upgraded platform services. This suite does
not replace the CLI/approval/database/stop-start journeys in e2e-checklist.md.
"""

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_user_token

pytestmark = pytest.mark.skipif(
    os.environ.get("F119_E2E") != "1", reason="requires deployed F119 and dedicated fixtures"
)


@pytest.fixture
async def target():
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        headers = {}
        for role in ("OWNER", "PUBLISH_ONLY", "FOREIGN"):
            username = os.environ[f"F119_E2E_{role}_USERNAME"]
            assert username.startswith("e2e-f119-")
            token = await get_user_token(client, username, os.environ[f"F119_E2E_{role}_PASSWORD"])
            headers[role] = auth_headers(token)
            identity = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers[role]))
            assert identity["user_name"] == username
            assert identity.get("role") != "admin" and not identity.get("is_child_admin")
        app = os.environ["F119_E2E_APP_ID"]
        detail = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}", headers=headers["OWNER"]))
        assert detail["name"].startswith("e2e-f119-")
        assert int(detail["tenant_id"]) == int(os.environ["F119_E2E_TENANT_ID"])
        yield client, app, os.environ["F119_E2E_OPERATION_ID"], headers


async def test_editor_receives_only_bounded_public_failure_details(target):
    """AC-21, AC-22, AC-24, AC-25: real edit actor reads safe retained diagnostics."""
    client, app, operation, headers = target
    data = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}/publish-status", headers=headers["OWNER"]))
    assert "edit" in data["allowed_actions"]
    failure = data["deployment"]["failure"]
    assert set(failure) == {"stage", "code", "message", "details", "hints"}
    assert failure["code"] in {16124, 16227, 16228}
    details = failure["details"]
    assert details["operation_id"] == operation
    assert set(details) <= {
        "operation_id",
        "reason",
        "runtime_stage",
        "maintenance",
        "data_may_have_changed",
        "tail",
        "diagnostics_available",
        "image_role",
        "image_ref",
    }
    assert len(details["tail"]) <= 40
    assert len("\n".join(details["tail"]).encode()) <= 16384
    assert details["diagnostics_available"] is bool(details["tail"])


async def test_publish_only_reads_progress_without_failure_or_output(target):
    """AC-24, AC-26: publish-only ordinary user gets management progress, no logs."""
    client, app, operation, headers = target
    data = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}/publish-status", headers=headers["PUBLISH_ONLY"]))
    assert "publish" in data["allowed_actions"] and "edit" not in data["allowed_actions"]
    assert data["deployment"]["failure"] is None
    op = assert_resp_200(
        await client.get(f"{API_BASE}/apps/{app}/runtime/operations/{operation}", headers=headers["PUBLISH_ONLY"])
    )
    assert op["failure"] is None


async def test_foreign_user_cannot_read_operation_even_with_a_real_id(target):
    """AC-24, AC-26: foreign ordinary actor is denied before operation lookup."""
    client, app, operation, headers = target
    assert_resp_error(
        await client.get(f"{API_BASE}/apps/{app}/runtime/operations/{operation}", headers=headers["FOREIGN"]), 16101
    )
