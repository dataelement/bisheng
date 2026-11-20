"""F005 end-to-end: auto-enabled workbench tools and skills.

Runs against a deployed backend (114 by default via E2E_API_BASE). Needs:
  E2E_ADMIN_PASSWORD           super admin password
  E2E_F005_USER / _PASSWORD    a dedicated non-admin user of the root tenant
  E2E_F005_LLM=1               optional: also send real messages (slow, uses the model)

Only two settings change: the code interpreter's usage in the root tenant's
workbench config, and the ``bisheng-pptx`` skill row of the root tenant. The
fixture snapshots both and writes them back, also on failure.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_admin_token, get_user_token

pytestmark = pytest.mark.e2e

TENANT = 1
CODE_KEY = "bisheng_code_interpreter"
SKILL = "bisheng-pptx"


def _code_group(config: dict) -> dict:
    for group in config.get("tools") or []:
        if any(child.get("tool_key") == CODE_KEY for child in group.get("children") or []):
            return group
    pytest.skip("the code interpreter is not among the selected workbench tools")


def _skill_row(rows) -> dict:
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    return next(row for row in rows if row["name"] == SKILL)


class Env:
    def __init__(self, client: httpx.AsyncClient, admin: dict, user: dict):
        self.client, self.admin, self.user = client, admin, user

    async def daily(self) -> dict:
        return assert_resp_200(await self.client.get(f"{API_BASE}/workstation/config/daily", headers=self.admin))[
            "data"
        ]

    async def save_daily(self, config: dict) -> None:
        assert_resp_200(await self.client.post(f"{API_BASE}/workstation/config/daily", headers=self.admin, json=config))

    async def set_tool(self, *, auto: bool, default: bool) -> None:
        config = await self.daily()
        group = _code_group(config)
        group["auto_enabled"], group["default_checked"] = auto, default
        await self.save_daily(config)

    async def skill(self) -> dict:
        rows = assert_resp_200(
            await self.client.get(f"{API_BASE}/linsight/skill", headers=self.admin, params={"page": 1, "limit": 500})
        )
        return _skill_row(rows)

    async def set_skill(self, auto: bool) -> None:
        resp = await self.client.patch(
            f"{API_BASE}/linsight/skill/{SKILL}/auto-enabled", headers=self.admin, json={"auto_enabled": auto}
        )
        assert_resp_200(resp)

    async def set_skill_enabled(self, enabled: bool) -> None:
        resp = await self.client.patch(
            f"{API_BASE}/linsight/skill/{SKILL}/status", headers=self.admin, json={"enabled": enabled}
        )
        assert_resp_200(resp)

    async def user_get(self, path: str, **params):
        return assert_resp_200(await self.client.get(f"{API_BASE}{path}", headers=self.user, params=params or None))


@pytest.fixture
async def env():
    user_name = os.environ.get("E2E_F005_USER")
    user_password = os.environ.get("E2E_F005_USER_PASSWORD")
    if not user_name or not user_password:
        pytest.skip("E2E_F005_USER / E2E_F005_USER_PASSWORD (a non-admin root-tenant user) are required")
    async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
        admin = auth_headers(await get_admin_token(client))
        assert_resp_200(await client.post(f"{API_BASE}/admin/tenant-scope", headers=admin, json={"tenant_id": TENANT}))
        admin["X-Management-Tenant"] = str(TENANT)
        user = auth_headers(await get_user_token(client, user_name, user_password))
        state = Env(client, admin, user)
        config_before = copy.deepcopy(await state.daily())
        skill_before = await state.skill()
        try:
            yield state
        finally:
            await state.save_daily(config_before)
            await state.set_skill(bool(skill_before.get("auto_enabled")))
            await state.set_skill_enabled(bool(skill_before.get("enabled")))


# -- admin settings -----------------------------------------------------------


async def test_ac01_ac02_tool_usage_is_saved_and_exclusive(env):
    """AC-01, AC-02: auto-enabled is stored, read back, and clears default_checked."""
    await env.set_tool(auto=True, default=True)

    group = _code_group(await env.daily())

    assert (group["auto_enabled"], group["default_checked"]) == (True, False)


async def test_ac06_skill_auto_enabled_is_listed(env):
    """AC-06: the management list shows the skill as auto-enabled."""
    await env.set_skill(True)

    assert (await env.skill())["auto_enabled"] is True


async def test_ac06_non_admin_cannot_switch_a_skill(env):
    """AC-06 (deny pair): the switch is a tenant-admin action; the stored value is unchanged."""
    before = (await env.skill())["auto_enabled"]
    resp = await env.client.patch(
        f"{API_BASE}/linsight/skill/{SKILL}/auto-enabled", headers=env.user, json={"auto_enabled": not before}
    )

    # get_tenant_admin_user answers every non-admin with 19801 (one code for both denials).
    assert_resp_error(resp, 19801)
    assert (await env.skill())["auto_enabled"] == before


# -- user-side lists ----------------------------------------------------------


async def _user_lists(env) -> dict:
    tools = (await env.user_get("/workstation/config")).get("tools") or []
    caps = (await env.user_get("/dsh/capabilities")).get("items") or []
    return {
        "tool_menu": any(c.get("tool_key") == CODE_KEY for g in tools for c in g.get("children") or []),
        "center_tool": any(i.get("tool_key") == CODE_KEY for i in caps),
        "center_skill": any((i.get("invocation_name") or "").endswith(f"-{SKILL}") for i in caps),
        "selectable": SKILL in json.dumps(await env.user_get("/linsight/skill/selectable")),
        "skill_center": SKILL in json.dumps(await env.user_get("/linsight/skill/center")),
        "runtime": SKILL in json.dumps(await env.user_get("/linsight/skill/runtime/catalog")),
    }


async def test_ac10_ac11_ac13_hidden_while_auto_enabled_and_back_after(env):
    """AC-10, AC-11: hidden from every user-facing picker; AC-13: back after switching off.

    The runtime catalog is not a picker and keeps the skill (design 决策 6).
    """
    await env.set_tool(auto=False, default=True)
    await env.set_skill(False)
    shown = await _user_lists(env)
    assert shown == dict.fromkeys(shown, True)

    await env.set_tool(auto=True, default=False)
    await env.set_skill(True)
    hidden = await _user_lists(env)
    assert hidden == {**dict.fromkeys(hidden, False), "runtime": True}

    await env.set_tool(auto=False, default=True)
    await env.set_skill(False)
    assert await _user_lists(env) == shown


async def test_ac07_a_disabled_skill_does_not_reach_the_user(env):
    """AC-07: disabled wins over auto-enabled."""
    await env.set_skill(True)
    await env.set_skill_enabled(False)

    assert SKILL not in json.dumps(await env.user_get("/linsight/skill/runtime/catalog"))


# -- real runs (optional) -----------------------------------------------------

LLM = pytest.mark.skipif(os.environ.get("E2E_F005_LLM") != "1", reason="set E2E_F005_LLM=1 to send real messages")


async def _run(env, text: str) -> list[dict]:
    model = str(((await env.user_get("/workstation/config")).get("models") or [{}])[0].get("id"))
    body = {
        "model": model,
        "clientTimestamp": datetime.now(UTC).isoformat(),
        "text": text,
        "tools": [],
        "skills": [],
    }
    sent = assert_resp_200(
        await env.client.post(
            f"{API_BASE}/workstation/chat/completions",
            headers={**env.user, "X-BS-Run-Protocol": "2"},
            json=body,
        )
    )
    events = []
    async with env.client.stream(
        "GET", f"{API_BASE}/workstation/conversations/{sent['conversation_id']}/events", headers=env.user
    ) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


@LLM
async def test_ac14_auto_enabled_tool_runs_without_being_picked(env):
    """AC-14, AC-20: nothing picked, the code interpreter is called and shown."""
    await env.set_tool(auto=True, default=False)

    events = await _run(env, "运行一段 python 代码，打印 sys.version，把输出原样告诉我")  # noqa: RUF001

    names = [e["data"].get("name") for e in events if e.get("type") == "tool_call"]
    assert CODE_KEY in names


@LLM
async def test_ac24_custom_skill_is_mounted_without_being_picked(env):
    """AC-24: a user-picked custom skill is still readable in a direct answer with nothing picked."""
    events = await _run(env, "湖南某县积雪 30 厘米、国省道中断、已发布橙色预警，按湖南省预案初步核验应启动几级响应？")  # noqa: RUF001

    outputs = " ".join(
        str(e["data"].get("output") or "")
        for e in events
        if e.get("type") == "tool_call" and e["data"].get("name") == "read_file"
    )
    assert "name: snow-ice-emergency-level-verify" in outputs
