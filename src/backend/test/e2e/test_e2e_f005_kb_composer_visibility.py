"""F005 revision end-to-end: configured knowledge bases and "show in input box".

Runs against a deployed backend (114 by default via E2E_API_BASE). Needs:
  E2E_ADMIN_PASSWORD           super admin password
  E2E_F005_USER / _PASSWORD    a dedicated non-admin user of the root tenant

Only the root tenant's workbench ``orgKbs`` changes. The fixture snapshots the
daily config and writes it back, also on failure. The suite creates three
knowledge spaces named ``e2e-f005kb-*`` (private; the test user is granted viewer on two of them) and deletes
them afterwards; leftovers from an earlier run are deleted first.
"""

from __future__ import annotations

import copy
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

pytestmark = pytest.mark.e2e

TENANT = 1


PREFIX = "e2e-f005kb-"


async def _spaces(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    data = assert_resp_200(
        await client.get(f"{API_BASE}/knowledge/space/list", headers=headers, params={"page_size": 100})
    )
    return data.get("data") or []


async def _grant_viewer(env: Env, space_id: int, user_id: int) -> None:
    base = f"{API_BASE}/permissions/resources/knowledge_space/{space_id}"
    context = assert_resp_200(await env.client.get(f"{base}/context", headers=env.admin))
    body = {
        "idempotency_key": f"{PREFIX}{space_id}-{user_id}",
        "expected_resource_version": context["resource_version"],
        "expected_catalog_release_id": context["catalog_release_id"],
        "changes": [{"op": "ADD", "model_key": "viewer", "subject": {"type": "user", "id": str(user_id)}}],
    }
    assert_resp_200(await env.client.post(f"{base}/grants:mutate", headers=env.admin, json=body))


class Env:
    def __init__(self, client: httpx.AsyncClient, admin: dict, user: dict):
        self.client, self.admin, self.user = client, admin, user

    async def daily(self) -> dict:
        return assert_resp_200(await self.client.get(f"{API_BASE}/workstation/config/daily", headers=self.admin))[
            "data"
        ]

    async def save_daily(self, config: dict) -> None:
        assert_resp_200(await self.client.post(f"{API_BASE}/workstation/config/daily", headers=self.admin, json=config))

    async def user_config(self) -> dict:
        return assert_resp_200(await self.client.get(f"{API_BASE}/workstation/config", headers=self.user))


@pytest.fixture
async def env():
    user_name = os.environ.get("E2E_F005_USER")
    user_password = os.environ.get("E2E_F005_USER_PASSWORD")
    if not user_name or not user_password:
        pytest.skip("E2E_F005_USER / E2E_F005_USER_PASSWORD (a non-admin root-tenant user) are required")
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        admin = auth_headers(await get_admin_token(client))
        assert_resp_200(await client.post(f"{API_BASE}/admin/tenant-scope", headers=admin, json={"tenant_id": TENANT}))
        admin["X-Management-Tenant"] = str(TENANT)
        user = auth_headers(await get_user_token(client, user_name, user_password))
        state = Env(client, admin, user)
        before = copy.deepcopy(await state.daily())
        try:
            yield state
        finally:
            await state.save_daily(before)


@pytest.fixture
async def kbs(env):
    """Two spaces the user can see, and one only the admin can see."""

    async def clean():
        for space in await _spaces(env.client, env.admin):
            if space["name"].startswith(PREFIX):
                assert_resp_200(await env.client.delete(f"{API_BASE}/knowledge/space/{space['id']}", headers=env.admin))

    await clean()
    made = []
    for suffix in ("shown", "hidden", "private"):
        created = assert_resp_200(
            await env.client.post(
                f"{API_BASE}/knowledge/space",
                headers=env.admin,
                json={"name": f"{PREFIX}{suffix}", "auth_type": "private", "auto_tag_enabled": False},
            )
        )
        made.append((int(created["id"]), created["name"]))
    try:
        user_id = assert_resp_200(await env.client.get(f"{API_BASE}/user/info", headers=env.user))["user_id"]
        for space_id, _ in made[:2]:
            await _grant_viewer(env, space_id, user_id)
        seen = {int(space["id"]) for space in await _spaces(env.client, env.user)}
        assert {made[0][0], made[1][0]} <= seen
        assert made[2][0] not in seen
        yield tuple(made)
    finally:
        await clean()


def _item(kb: tuple[int, str], show: bool, order: int) -> dict:
    return {"id": kb[0], "name": kb[1], "type": 3, "show_in_composer": show, "sort_order": order}


async def test_ac25_ac26_ac28_show_in_composer_is_saved(env, kbs):
    """AC-25, AC-26, AC-28: each item keeps its setting; hidden items without default_checked are kept."""
    shown, hidden, _ = kbs
    config = await env.daily()
    config["orgKbs"] = [_item(shown, True, 0), _item(hidden, False, 1)]
    await env.save_daily(config)

    saved = (await env.daily())["orgKbs"]

    assert [(kb["id"], kb["show_in_composer"]) for kb in saved] == [(shown[0], True), (hidden[0], False)]
    assert all("default_checked" not in kb for kb in saved)


async def test_ac29_ac30_user_config_lists_every_configured_kb(env, kbs):
    """AC-29, AC-30: the user gets every configured knowledge base, hidden ones flagged, not dropped."""
    shown, hidden, _ = kbs
    config = await env.daily()
    config["orgKbs"] = [_item(shown, True, 0), _item(hidden, False, 1)]
    await env.save_daily(config)

    user_kbs = (await env.user_config()).get("orgKbs") or []

    assert [(kb["id"], kb["show_in_composer"]) for kb in user_kbs] == [(shown[0], True), (hidden[0], False)]


async def test_ac34_a_kb_the_user_cannot_see_is_left_out(env, kbs):
    """AC-34: a configured knowledge base without visible permission is not sent to the user; no error."""
    shown, _, admin_only = kbs
    if admin_only is None:
        pytest.skip("no knowledge base is hidden from this user")
    config = await env.daily()
    config["orgKbs"] = [_item(shown, True, 0), _item(admin_only, True, 1)]
    await env.save_daily(config)

    user_kbs = (await env.user_config()).get("orgKbs") or []

    assert [kb["id"] for kb in user_kbs] == [shown[0]]
