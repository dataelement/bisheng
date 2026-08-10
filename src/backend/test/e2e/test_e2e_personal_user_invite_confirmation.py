"""API E2E coverage for F045 personal-user invite confirmation.

Prerequisites:
- A running BiSheng backend with real MySQL, Redis and OpenFGA.
- A running worker consuming the default approval outbox queue.
- ``E2E_API_BASE`` and ``E2E_ADMIN_PASSWORD`` configured for that environment.
- Optional ``E2E_F045_ALLOW_SCENE_TOGGLE=1`` enables the destructive-looking,
  but automatically restored, approval-scene gate check.

All mutable test data uses a per-run ``f045-e2e-<uuid>-`` prefix. Cleanup is
prefix-scoped and runs before and after the class. Historical approval records
are intentionally retained as audit data; their resource and user snapshots
remain uniquely identifiable by the run prefix.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import (
    auth_headers,
    create_test_user,
    get_admin_token,
    get_user_token,
)

RUN_ID = uuid.uuid4().hex[:8]
PREFIX = f"f045-e2e-{RUN_ID}-"
TEST_PASSWORD = "F045_e2e_user_123"
SCENARIO_CODE = "resource_user_invite_confirmation"
SCENE_DISABLED_MESSAGE = "个人用户邀请确认场景未启用，无法新增个人用户权限"  # noqa: RUF001


def _rows(data: object) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("data") or data.get("items") or []
        return rows if isinstance(rows, list) else []
    return []


async def _cleanup_prefixed_data(client: httpx.AsyncClient, token: str) -> None:
    """Delete only resources/users created by this exact E2E run."""
    if len(PREFIX) < 5:
        raise AssertionError("unsafe E2E cleanup prefix")
    headers = auth_headers(token)

    spaces = _rows(
        assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/mine",
                headers=headers,
            )
        )
    )
    for space in spaces:
        if str(space.get("name", "")).startswith(PREFIX):
            assert_resp_200(
                await client.delete(
                    f"{API_BASE}/knowledge/space/{space['id']}",
                    headers=headers,
                )
            )

    channels = _rows(
        assert_resp_200(
            await client.get(
                f"{API_BASE}/channel/manager/my_channels",
                params={"query_type": "created", "sort_by": "latest_update"},
                headers=headers,
            )
        )
    )
    for channel in channels:
        if str(channel.get("name", "")).startswith(PREFIX):
            assert_resp_200(
                await client.delete(
                    f"{API_BASE}/channel/manager/{channel['id']}",
                    headers=headers,
                )
            )

    users = _rows(
        assert_resp_200(
            await client.get(
                f"{API_BASE}/user/list",
                params={"page_num": 1, "page_size": 100, "name": PREFIX},
                headers=headers,
            )
        )
    )
    for user in users:
        if str(user.get("user_name", "")).startswith(PREFIX) and not user.get("delete"):
            assert_resp_200(
                await client.post(
                    f"{API_BASE}/user/update",
                    json={"user_id": user["user_id"], "delete": 1},
                    headers=headers,
                )
            )


async def _create_user_and_token(
    client: httpx.AsyncClient,
    admin_token: str,
    *,
    suffix: str,
    role_id: int,
) -> tuple[dict, str]:
    user = await create_test_user(
        client,
        admin_token,
        username=f"{PREFIX}{suffix}",
        role_id=role_id,
        password=TEST_PASSWORD,
    )
    token = await get_user_token(client, user["user_name"], TEST_PASSWORD)
    return user, token


async def _permissions(
    client: httpx.AsyncClient,
    token: str,
    *,
    resource_type: str,
    resource_id: str,
) -> list[dict]:
    if resource_type == "channel":
        url = f"{API_BASE}/channel/manager/{resource_id}/permissions"
    else:
        url = f"{API_BASE}/permissions/resources/{resource_type}/{resource_id}/permissions"
    return _rows(assert_resp_200(await client.get(url, headers=auth_headers(token))))


async def _wait_for_permission_state(
    client: httpx.AsyncClient,
    token: str,
    *,
    resource_type: str,
    resource_id: str,
    target_user_id: int,
    expected_status: str | None,
    timeout_seconds: float = 60.0,
) -> list[dict]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        rows = await _permissions(
            client,
            token,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        target = next(
            (
                row
                for row in rows
                if row.get("subject_type") == "user"
                and int(row.get("subject_id", -1)) == target_user_id
            ),
            None,
        )
        if (target or {}).get("authorization_status") == expected_status:
            return rows
        if expected_status is None and target is None:
            return rows
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"permission state did not become {expected_status!r}: {rows}"
            )
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
class TestE2EPersonalUserInviteConfirmation:
    """F045 API E2E: gate, dedupe, self-decision and final permission state."""

    @pytest.fixture(autouse=True, scope="class")
    async def setup_and_teardown(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                admin_token = await get_admin_token(client)
            except (httpx.HTTPError, AssertionError) as error:
                pytest.skip(f"F045 real E2E environment unavailable: {error}")
            await _cleanup_prefixed_data(client, admin_token)
            try:
                yield
            finally:
                admin_token = await get_admin_token(client)
                await _cleanup_prefixed_data(client, admin_token)

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    async def test_ac24_ac25_ac26_default_scene_is_enabled_and_self_confirming(
        self,
        client,
        admin_token,
    ):
        """AC-24/25/26: the shared seeded scene is enabled with one active route and flow."""
        scenarios = _rows(
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/approval/admin/scenarios",
                    headers=auth_headers(admin_token),
                )
            )
        )
        scenario = next(item for item in scenarios if item["scenario_code"] == SCENARIO_CODE)
        assert scenario["enabled"] is True

        routes = _rows(
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/approval/admin/scenarios/{scenario['id']}/routes",
                    headers=auth_headers(admin_token),
                )
            )
        )
        assert any(route.get("enabled") for route in routes)

        flows = _rows(
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/approval/admin/scenarios/{scenario['id']}/flows",
                    headers=auth_headers(admin_token),
                )
            )
        )
        assert any(flow.get("is_active") for flow in flows)

    async def test_ac01_ac05_ac09_ac12_ac15_ac16_ac19_invite_dedupe_and_approve(
        self,
        client,
        admin_token,
    ):
        """AC-01/05/09/12/15/16/19: one pending invite, self approve, one active grant."""
        target, target_token = await _create_user_and_token(
            client,
            admin_token,
            suffix="approve-target",
            role_id=2,
        )
        second_inviter, second_inviter_token = await _create_user_and_token(
            client,
            admin_token,
            suffix="second-inviter",
            role_id=1,
        )
        target_id = int(target["user_id"])
        second_inviter_id = int(second_inviter["user_id"])

        space = assert_resp_200(
            await client.post(
                f"{API_BASE}/knowledge/space",
                json={"name": f"{PREFIX}approve-space", "auth_type": "approval"},
                headers=auth_headers(admin_token),
            )
        )
        space_id = str(space["id"])
        first_grant = {
            "subject_type": "user",
            "subject_id": target_id,
            "relation": "viewer",
            "include_children": False,
        }
        first = assert_resp_200(
            await client.post(
                f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/authorize",
                json={"grants": [first_grant], "revokes": []},
                headers=auth_headers(admin_token),
            )
        )
        assert first["invite_created_count"] == 1
        assert first["results"][0]["outcome"] == "invite_created"
        instance_id = int(first["results"][0]["approval_instance_id"])

        pending_rows = await _permissions(
            client,
            admin_token,
            resource_type="knowledge_space",
            resource_id=space_id,
        )
        pending = next(row for row in pending_rows if int(row.get("subject_id", -1)) == target_id)
        assert pending["authorization_status"] == "pending"
        assert int(pending["approval_instance_id"]) == instance_id
        assert pending["relation"] == "viewer"
        assert_resp_error(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/info",
                headers=auth_headers(target_token),
            ),
            18040,
        )

        # A tenant administrator is intentionally not allowed to confirm for
        # the invitee, even though they can read the task through admin access.
        my_tasks = _rows(
            assert_resp_200(
                await client.get(
                    f"{API_BASE}/approval/my-tasks",
                    headers=auth_headers(target_token),
                )
            )
        )
        task = next(item for item in my_tasks if int(item["instance_id"]) == instance_id)
        assert int(task["approver_user_id"]) == target_id
        assert_resp_error(
            await client.post(
                f"{API_BASE}/approval/tasks/{task['task_id']}/decision",
                json={"action": "approve"},
                headers=auth_headers(admin_token),
            ),
            18101,
        )

        # The second inviter asks for a different role. The first invitation
        # and role snapshot win, so no second instance/task is created.
        duplicate = assert_resp_200(
            await client.post(
                f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/authorize",
                json={
                    "grants": [{**first_grant, "relation": "editor"}],
                    "revokes": [],
                },
                headers=auth_headers(second_inviter_token),
            )
        )
        assert duplicate["invite_existing_count"] == 1
        assert duplicate["results"][0]["outcome"] == "invite_existing"
        assert int(duplicate["results"][0]["approval_instance_id"]) == instance_id
        assert duplicate["results"][0]["relation"] == "viewer"
        assert second_inviter_id != target_id

        decided = assert_resp_200(
            await client.post(
                f"{API_BASE}/approval/tasks/{task['task_id']}/decision",
                json={"action": "approve", "comment": "F045 E2E self confirmation"},
                headers=auth_headers(target_token),
            )
        )
        assert decided["instance_status"] in {"approved", "executing", "executed"}

        active_rows = await _wait_for_permission_state(
            client,
            admin_token,
            resource_type="knowledge_space",
            resource_id=space_id,
            target_user_id=target_id,
            expected_status="active",
        )
        active = next(row for row in active_rows if int(row.get("subject_id", -1)) == target_id)
        assert active["relation"] == "viewer"
        assert active.get("approval_instance_id") is None
        assert_resp_200(
            await client.get(
                f"{API_BASE}/knowledge/space/{space_id}/info",
                headers=auth_headers(target_token),
            )
        )
        assert_resp_error(
            await client.post(
                f"{API_BASE}/approval/tasks/{task['task_id']}/decision",
                json={"action": "approve"},
                headers=auth_headers(target_token),
            ),
            18102,
        )

    async def test_ac06_ac20_ac21_ac22_reject_then_reinvite_and_withdraw(
        self,
        client,
        admin_token,
    ):
        """AC-06/20/21/22: reject removes pending, reinvite works, withdraw is terminal."""
        target, target_token = await _create_user_and_token(
            client,
            admin_token,
            suffix="reject-target",
            role_id=2,
        )
        target_id = int(target["user_id"])
        channel = assert_resp_200(
            await client.post(
                f"{API_BASE}/channel/manager/create",
                json={
                    "name": f"{PREFIX}reject-channel",
                    "visibility": "review",
                    "source_list": [],
                },
                headers=auth_headers(admin_token),
            )
        )
        channel_id = str(channel["id"])
        grant = {
            "subject_type": "user",
            "subject_id": target_id,
            "relation": "viewer",
            "include_children": False,
        }

        async def invite() -> tuple[int, int]:
            result = assert_resp_200(
                await client.post(
                    f"{API_BASE}/channel/manager/{channel_id}/authorize",
                    json={"grants": [grant], "revokes": []},
                    headers=auth_headers(admin_token),
                )
            )
            instance_id = int(result["results"][0]["approval_instance_id"])
            tasks = _rows(
                assert_resp_200(
                    await client.get(
                        f"{API_BASE}/approval/my-tasks",
                        headers=auth_headers(target_token),
                    )
                )
            )
            task = next(item for item in tasks if int(item["instance_id"]) == instance_id)
            return instance_id, int(task["task_id"])

        first_instance_id, first_task_id = await invite()
        assert_resp_200(
            await client.post(
                f"{API_BASE}/approval/tasks/{first_task_id}/decision",
                json={"action": "reject", "comment": "F045 E2E reject"},
                headers=auth_headers(target_token),
            )
        )
        await _wait_for_permission_state(
            client,
            admin_token,
            resource_type="channel",
            resource_id=channel_id,
            target_user_id=target_id,
            expected_status=None,
        )

        second_instance_id, second_task_id = await invite()
        assert second_instance_id != first_instance_id
        assert_resp_200(
            await client.post(
                f"{API_BASE}/approval/instances/{second_instance_id}/withdraw",
                json={"reason": "F045 E2E withdraw"},
                headers=auth_headers(admin_token),
            )
        )
        await _wait_for_permission_state(
            client,
            admin_token,
            resource_type="channel",
            resource_id=channel_id,
            target_user_id=target_id,
            expected_status=None,
        )
        assert_resp_error(
            await client.post(
                f"{API_BASE}/approval/tasks/{second_task_id}/decision",
                json={"action": "approve"},
                headers=auth_headers(target_token),
            ),
            18102,
        )

    async def test_ac27_ac28_disabled_scene_rejects_create_without_side_effect(
        self,
        client,
        admin_token,
    ):
        """AC-27/28: disabled scene returns exact 18106 and creates no resource/invite."""
        if os.environ.get("E2E_F045_ALLOW_SCENE_TOGGLE") != "1":
            pytest.skip("set E2E_F045_ALLOW_SCENE_TOGGLE=1 on an isolated E2E tenant")

        target, _ = await _create_user_and_token(
            client,
            admin_token,
            suffix="gate-target",
            role_id=2,
        )
        target_id = int(target["user_id"])
        headers = auth_headers(admin_token)
        scenarios = _rows(
            assert_resp_200(
                await client.get(f"{API_BASE}/approval/admin/scenarios", headers=headers)
            )
        )
        scenario = next(item for item in scenarios if item["scenario_code"] == SCENARIO_CODE)
        assert scenario["enabled"] is True
        name = f"{PREFIX}disabled-scene-space"
        try:
            assert_resp_200(
                await client.put(
                    f"{API_BASE}/approval/admin/scenarios/{scenario['id']}",
                    json={"enabled": False},
                    headers=headers,
                )
            )
            response = await client.post(
                f"{API_BASE}/knowledge/space",
                json={
                    "name": name,
                    "auth_type": "approval",
                    "initial_permissions": {
                        "grants": [
                            {
                                "subject_type": "user",
                                "subject_id": target_id,
                                "relation": "viewer",
                                "include_children": False,
                            }
                        ]
                    },
                },
                headers=headers,
            )
            body = assert_resp_error(response, 18106)
            assert body["status_message"] == SCENE_DISABLED_MESSAGE

            spaces = _rows(
                assert_resp_200(
                    await client.get(
                        f"{API_BASE}/knowledge/space/mine",
                        headers=headers,
                    )
                )
            )
            assert not any(space.get("name") == name for space in spaces)
            requests = _rows(
                assert_resp_200(
                    await client.get(
                        f"{API_BASE}/approval/my-requests",
                        headers=headers,
                    )
                )
            )
            assert not any(request.get("business_name") == name for request in requests)
        finally:
            assert_resp_200(
                await client.put(
                    f"{API_BASE}/approval/admin/scenarios/{scenario['id']}",
                    json={"enabled": True},
                    headers=headers,
                )
            )
