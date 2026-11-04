"""T079:真实网关、目录 Worker、Cookie 身份与 F048 授权生命周期。

默认跳过。操作侧通过私有 checkpoint 完成真实 OP 登录和状态变更;
测试侧不猜测上游管理接口、不签发 JWT、不直调 Worker/领域服务。
"""

import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from test.e2e.helpers.kunlian import PREFIX, live_journey

pytestmark = pytest.mark.e2e


@pytest.fixture
async def kunlian_journey():
    if os.environ.get("F118_E2E") != "1":
        pytest.skip("待执行:设置 F118_E2E=1,并提供专属配对环境和真实操作侧")
    async with live_journey(os.environ) as journey:
        yield journey


class TestKunlianIdentityJourney:
    async def test_directory_authorization_disable_restore_and_logout(self, kunlian_journey, record_property):
        """AC-01, AC-04, AC-05, AC-06, AC-07, AC-09, AC-10, AC-12, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24:真实身份与权限闭环。"""
        journey = kunlian_journey
        manifest = journey.manifest
        await journey.preflight()
        await journey.bridge.checkpoint(
            "prepare-missing-directory",
            connection_id=manifest["connection_id"],
            instruction="核验 A/B/C 及独立新建 missing 探针;本地已发布目录尚未覆盖 missing,暂停自动目录调度直到本次回调完成;不删除历史绑定;A/B 无菜单",
        )
        before = await journey.status()
        await journey.login("missing", expected_status=409, reason="DIRECTORY_NOT_READY")
        after = await journey.status()
        assert after["sync_requested_version"] > before["sync_requested_version"], "缺目录没有登记补同步"

        await journey.bridge.checkpoint(
            "directory-ready-no-menu",
            instruction="确认真实全目录包括 A/B、missing 和其他租户事实,恢复自动调度,仍不授任何菜单",
        )
        binding_path = "/identity-integrations/kunlian/tenant-bindings/" + manifest["external_tenant_id"]
        mapping = await journey.admin_call("GET", binding_path)
        if mapping["local_tenant_id"] is not None:
            assert mapping["local_tenant_id"] == manifest["local_tenant_id"], "不能重绑定其他测试/业务租户"
        await journey.admin_call(
            "PUT",
            binding_path,
            json={
                "local_tenant_id": manifest["local_tenant_id"],
                "expected_revision": mapping["revision"],
                "enabled": True,
            },
        )
        persisted = await journey.admin_call("GET", binding_path)
        assert persisted["local_tenant_id"] == manifest["local_tenant_id"] and persisted["enabled"]
        await journey.sync()
        await journey.login("a", expected_status=403, reason="ENTRY_UNAUTHORIZED")
        await journey.bridge.checkpoint(
            "grant-menu-only", instruction="管理员仅为 A/B 授予所测入口菜单,不赋予对象 Grant;C 保持外部跨租户身份"
        )
        a, b = await journey.login("a"), await journey.login("b")
        await journey.user(a, "a")
        await journey.user(b, "b")
        # 固定租户之外的 ID Token 在网关严格验证阶段已拒绝。
        await journey.login("c", expected_status=400, reason="LOGIN_INVALID")

        name = PREFIX + uuid4().hex
        record_property("workflow_test_name", name)
        created = await journey.browser_call(
            a,
            "POST",
            "/workflow/create",
            status=201,
            json={
                "name": name,
                "flow_type": 10,
                "data": {"nodes": [], "edges": []},
            },
        )
        workflow_id = created["id"]
        # 创建响应后立即登记清理目标,后续断言失败也能清理本次资产。
        expected = {
            "name": name,
            "user_id": manifest["actors"]["a"]["user_id"],
            "tenant_id": manifest["local_tenant_id"],
        }
        journey.workflows[workflow_id] = expected
        original = await journey.admin_call("GET", "/workflow/get_one_flow/" + workflow_id)
        assert all(original[key] == value for key, value in expected.items())
        assert not await journey.check_action(b, workflow_id, "visible")
        assert not await journey.check_action(b, workflow_id, "use")

        await journey.mutate_grants(
            workflow_id,
            [
                {
                    "op": "ADD",
                    "model_key": "viewer",
                    "subject": {
                        "type": "user",
                        "id": str(manifest["actors"]["b"]["user_id"]),
                    },
                }
            ],
        )
        assert await journey.check_action(b, workflow_id, "visible")
        assert await journey.check_action(b, workflow_id, "use")
        assert await journey.check_action(a, workflow_id, "edit")
        assert not await journey.check_action(b, workflow_id, "edit")
        assert not await journey.check_action(b, workflow_id, "publish")
        await journey.browser_call(b, "GET", "/workflow/get_one_flow/" + workflow_id)
        await journey.browser_call(
            b, "GET", "/workflow/write/auth", code=10599, params={"flow_id": workflow_id, "flow_type": 10}
        )
        roster = await journey.roster(workflow_id)
        assignments = [
            row
            for row in roster
            if row["subject"]["type"] == "user"
            and row["subject"]["id"] == str(manifest["actors"]["b"]["user_id"])
            and row["model"]["key"] == "viewer"
        ]
        assert len(assignments) == 1

        await journey.bridge.checkpoint("disable-b", instruction="真实昆联上游停用 B;不删除本地用户、人工 Grant 或资产")
        await journey.sync()
        response = await b.get("/api/v1/user/info")
        assert response.status_code in {401, 403}, "已确认停用的旧 Cookie 仍可访问"
        old_cookie = b.cookies.get("access_token_cookie")
        assert await journey.roster(workflow_id) == roster
        kept = await journey.admin_call("GET", "/workflow/get_one_flow/" + workflow_id)
        for key in ("name", "user_id", "tenant_id", "data"):
            assert kept[key] == original[key], "成员停用不应改变工作流资料/归属"
        await journey.mutate_grants(
            workflow_id,
            [
                {
                    "op": "REMOVE",
                    "assignee_id": assignments[0]["assignee_id"],
                    "expected_assignee_version": assignments[0]["assignee_version"],
                }
            ],
        )
        revoked_roster = await journey.roster(workflow_id)
        assert not any(row["assignee_id"] == assignments[0]["assignee_id"] for row in revoked_roster)

        await journey.bridge.checkpoint("restore-b", instruction="真实上游恢复 B,不增加或补回人工授权")
        await journey.sync()
        response = await b.get("/api/v1/user/info")
        assert response.status_code in {401, 403}, "恢复错误地复活旧会话"
        fresh = await journey.login("b")
        if fresh.cookies.get("access_token_cookie") == old_cookie:
            raise AssertionError("恢复后没有建立新的本地会话")
        await journey.user(fresh, "b")
        assert await journey.roster(workflow_id) == revoked_roster
        assert not await journey.check_action(fresh, workflow_id, "visible")
        assert not await journey.check_action(fresh, workflow_id, "edit")

        access = fresh.cookies.get("access_token_cookie")
        binding_cookie = fresh.cookies.get("kunlian_browser_binding")
        result = await journey.browser_call(fresh, "POST", "/user/logout")
        assert result["local_logged_out"] is True
        action = result["next_action"]
        assert action["url"] == "/api/kunlian/logout" and action["method"] == "POST"
        replay = await fresh.get(
            "/api/v1/user/info",
            headers={"Cookie": f"access_token_cookie={access}; kunlian_browser_binding={binding_cookie}"},
        )
        assert replay.status_code in {401, 403}, "退出后旧会话仍可重放"
        remote = await fresh.post(
            "/api/kunlian/logout", data={"ticket": action["ticket"]}, headers={"Origin": journey.origin}
        )
        assert remote.status_code == 303, "网关没有在本地撤销证明后交接退出"
        answer = await journey.bridge.checkpoint(
            "op-logout",
            logout_url=remote.headers["location"],
            instruction="真实 OP 确认退出,访问网关前截获 logout_callback_url",
        )
        callback = answer.get("logout_callback_url", "")
        parsed = urlsplit(callback)
        assert parsed.scheme + "://" + parsed.netloc == journey.origin
        assert parsed.path == "/api/kunlian/logout/callback" and not parsed.fragment
        confirmed = await fresh.get(callback)
        if confirmed.status_code != 200 or "LOGOUT_CALLBACK_RECEIVED" not in confirmed.text:
            raise AssertionError("未收到受绑定的 OP 退出回调确认")
