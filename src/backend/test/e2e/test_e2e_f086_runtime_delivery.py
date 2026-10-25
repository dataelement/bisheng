"""Opt-in live F086 management boundary checks; creates no platform objects.

F086_E2E=1 requires a dedicated Docker v2 deployment, an approved application
whose name starts with e2e-f086-, and three separately authenticated identities.
Publication, human approval, image/offline and failure-injection journeys remain
in the feature's manual-e2e checklist; this module does not claim to cover them.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_user_token

pytestmark = pytest.mark.skipif(
    os.environ.get("F086_E2E") != "1",
    reason="requires dedicated F086 live deployment and owner/nonowner/foreign accounts",
)


def required(name):
    value = os.environ.get("F086_E2E_" + name, "").strip()
    if not value:
        pytest.fail("F086_E2E_" + name + " is required")
    return value


@pytest.fixture
async def runtime_target():
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        tokens = {}
        for role in ["OWNER", "NONOWNER", "FOREIGN"]:
            tokens[role] = await get_user_token(client, required(role + "_USERNAME"), required(role + "_PASSWORD"))
        app = required("APP_ID")
        detail = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}", headers=auth_headers(tokens["OWNER"])))
        assert detail["name"].startswith("e2e-f086-"), "suite only addresses its dedicated application"
        assert int(detail["tenant_id"]) == int(required("TENANT_ID"))
        yield client, app, tokens


async def test_owner_can_read_snapshots_and_persisted_profile_defaults(runtime_target):
    """AC-14, AC-15, AC-41: owner can read catalog and only its own snapshot metadata."""
    client, app, tokens = runtime_target
    headers = auth_headers(tokens["OWNER"])
    profiles = assert_resp_200(await client.get(f"{API_BASE}/runtime/profiles", headers=headers))
    defaults = assert_resp_200(await client.get(f"{API_BASE}/runtime/profiles/defaults", headers=headers))
    assert profiles and defaults
    ids = {profile["id"] for profile in profiles}
    assert all(item["profile_id"] in ids and item["generation"] >= 1 for item in defaults)
    state = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}/runtime/state", headers=headers))
    assert state["generation"] >= 1 and state["operation_id"]
    snapshots = assert_resp_200(await client.get(f"{API_BASE}/apps/{app}/runtime/snapshots", headers=headers))
    assert isinstance(snapshots, list)
    assert all(item["confirmed_at"] for item in snapshots)


@pytest.mark.parametrize("role", ["NONOWNER", "FOREIGN"])
async def test_other_identities_cannot_read_owner_snapshots(runtime_target, role):
    """AC-30, AC-45, AC-53: same-tenant and foreign identities receive the owner refusal."""
    client, app, tokens = runtime_target
    assert_resp_error(
        await client.get(f"{API_BASE}/apps/{app}/runtime/snapshots", headers=auth_headers(tokens[role])), 16105
    )


@pytest.mark.parametrize("role", ["NONOWNER", "FOREIGN"])
async def test_other_identities_cannot_restore_even_with_well_formed_input(runtime_target, role):
    """AC-45, AC-53: restore checks ownership before any snapshot lookup or operation intent."""
    client, app, tokens = runtime_target
    assert_resp_error(
        await client.post(
            f"{API_BASE}/apps/{app}/runtime/restore",
            headers=auth_headers(tokens[role]),
            json={
                "snapshot_id": uuid4().hex,
                "expected_current_generation": 1,
                "acknowledge_data_loss": True,
                "idempotency_key": "e2e-f086-denied-" + uuid4().hex,
            },
        ),
        16105,
    )


async def test_owner_cannot_change_global_runtime_defaults(runtime_target):
    """AC-14, AC-30: an ordinary owner does not acquire global catalog privileges."""
    client, _app, tokens = runtime_target
    assert_resp_error(
        await client.put(
            f"{API_BASE}/runtime/profiles/default",
            headers=auth_headers(tokens["OWNER"]),
            json={
                "language": "python3.11",
                "profile_id": "e2e-f086-no-such-profile",
                "expected_generation": 0,
            },
        ),
        16106,
    )
