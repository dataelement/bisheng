"""覆盖 AC: AC-03, AC-08, AC-10, AC-13, AC-15, AC-20, AC-22, AC-23。

仅在显式指定的隔离 Mock 环境执行。依赖正常 API、F048、SQL、Redis 和 Worker。
本文件不将进程内 Provider 或直接节点调用计为端到端验证。
"""

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers, get_user_token

PREFIX = "e2e-f119-"
EXAMPLE = Path(__file__).parents[4] / "features/v3.0.0/119-kunlian-platform-agent/mock-workflow.example.json"


async def _cleanup_exact(client, headers, name, tenant_id, owner_id):
    """只清理本套件的精确名称、租户和所有者匹配的工作流。"""
    assert name.startswith(PREFIX) and len(name) >= 16
    cursor = None
    for _ in range(20):
        page = assert_resp_200(
            await client.get(
                f"{API_BASE}/workflow/list",
                headers=headers,
                params={"name": name, "managed": True, "page_size": 100, **({"cursor": cursor} if cursor else {})},
            )
        )
        for row in page["data"]:
            if row["name"] != name:
                continue
            facts = assert_resp_200(await client.get(f"{API_BASE}/workflow/get_one_flow/{row['id']}", headers=headers))
            assert (facts["name"], facts["tenant_id"], facts["user_id"]) == (name, tenant_id, owner_id)
            assert_resp_200(await client.delete(f"{API_BASE}/flows/{row['id']}", headers=headers))
        if not page["has_more"]:
            return
        next_cursor = page["next_cursor"]
        assert next_cursor and next_cursor != cursor
        cursor = next_cursor
    raise AssertionError("fixture cleanup pagination exceeded")


@pytest.fixture
async def mock_environment():
    if os.getenv("F119_MOCK_E2E") != "1":
        pytest.skip("NOT_RUN: API/Broker/Worker 与专用 Mock 用户待就绪。设置 F119_MOCK_E2E=1 后执行")
    required = [
        "F119_AUTHOR_USERNAME",
        "F119_AUTHOR_PASSWORD",
        "F119_RUNNER_USERNAME",
        "F119_RUNNER_PASSWORD",
        "F119_TENANT_ID",
        "F119_USE_MODEL_KEY",
        "F119_RUN_ID",
    ]
    missing = [key for key in required if not os.getenv(key)]
    assert not missing, f"Missing environment keys: {', '.join(missing)}"
    run_id = os.environ["F119_RUN_ID"]
    assert re.fullmatch(r"[a-zA-Z0-9-]{8,40}", run_id)
    tenant_id = int(os.environ["F119_TENANT_ID"])
    assert tenant_id > 1, "Use a dedicated test tenant"
    name = PREFIX + run_id
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        author = auth_headers(
            await get_user_token(client, os.environ["F119_AUTHOR_USERNAME"], os.environ["F119_AUTHOR_PASSWORD"])
        )
        runner = auth_headers(
            await get_user_token(client, os.environ["F119_RUNNER_USERNAME"], os.environ["F119_RUNNER_PASSWORD"])
        )
        owner = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=author))
        user = assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=runner))
        assert owner["tenant_id"] == user["tenant_id"] == tenant_id
        assert owner["user_id"] != user["user_id"] and user.get("role") != "admin"
        env = assert_resp_200(await client.get(f"{API_BASE}/env"))
        assert env["workflow"]["platform_agent_mode"] == "mock"
        await _cleanup_exact(client, author, name, tenant_id, owner["user_id"])
        try:
            yield client, author, runner, name, user["user_id"]
        finally:
            await _cleanup_exact(client, author, name, tenant_id, owner["user_id"])


class TestPlatformAgentMockE2E:
    @pytest.mark.asyncio
    async def test_a_publishes_v1_b_runs_and_private_agent_is_denied(self, mock_environment):
        """AC-03、AC-08、AC-10、AC-13、AC-15、AC-20、AC-22、AC-23: 正常入口及一条拒绝。"""
        client, author, runner, name, runner_id = mock_environment
        graph = json.loads(EXAMPLE.read_text())
        response = await client.post(
            f"{API_BASE}/workflow/create",
            headers=author,
            json={"name": name, "description": "F119 isolated Mock test", "data": graph},
        )
        assert response.status_code in {200, 201}
        envelope = response.json()
        assert envelope["status_code"] == 200 and "status_message" in envelope
        flow = envelope["data"]
        flow_id, version_id = flow["id"], flow["version_id"]
        directory = assert_resp_200(
            await client.get(f"{API_BASE}/workflow/platform-agents", headers=author, params={"workflow_id": flow_id})
        )
        assert directory["provider_mode"] == "mock"
        version = assert_resp_200(
            await client.get(
                f"{API_BASE}/workflow/platform-agents/mock:echo/versions/v1",
                headers=author,
                params={"workflow_id": flow_id},
            )
        )
        assert version["ref"]["version_id"] == "v1"
        assert_resp_200(
            await client.put(
                f"{API_BASE}/workflow/versions/{version_id}", headers=author, json={"name": "v1", "data": graph}
            )
        )
        saved = assert_resp_200(await client.get(f"{API_BASE}/workflow/versions/{version_id}", headers=author))
        assert saved["data"] == graph
        context = assert_resp_200(
            await client.get(f"{API_BASE}/permissions/resources/workflow/{flow_id}/context", headers=author)
        )
        assert_resp_200(
            await client.post(
                f"{API_BASE}/permissions/resources/workflow/{flow_id}/grants:mutate",
                headers=author,
                json={
                    "idempotency_key": uuid4().hex,
                    "expected_resource_version": context["resource_version"],
                    "expected_catalog_release_id": context["catalog_release_id"],
                    "changes": [
                        {
                            "op": "ADD",
                            "model_key": os.environ["F119_USE_MODEL_KEY"],
                            "subject": {"type": "user", "id": str(runner_id)},
                        }
                    ],
                },
            )
        )
        assert_resp_200(
            await client.patch(
                f"{API_BASE}/workflow/status",
                headers=author,
                json={"flow_id": flow_id, "version_id": version_id, "status": 2},
            )
        )
        second = deepcopy(graph)
        second["nodes"][1]["data"]["group_params"][0]["params"][0]["value"]["version_id"] = "v2"
        assert_resp_200(
            await client.post(
                f"{API_BASE}/workflow/versions",
                params={"flow_id": flow_id},
                headers=author,
                json={"name": "v2", "data": second},
            )
        )
        published = assert_resp_200(await client.get(f"{API_BASE}/workflow/get_one_flow/{flow_id}", headers=author))
        assert (
            published["data"]["_platform_agent_publication"]["nodes"]["platform_agent_example"]["ref"]["version_id"]
            == "v1"
        )
        invocation_url = API_BASE.removesuffix("/api/v1") + "/api/v2/workflow/invoke"
        output = assert_resp_200(
            await client.post(invocation_url, headers=runner, json={"workflow_id": flow_id, "stream": False})
        )
        assert "F119 Mock / B" in json.dumps(output, ensure_ascii=False)
        assert_resp_200(
            await client.patch(
                f"{API_BASE}/workflow/status",
                headers=author,
                json={"flow_id": flow_id, "version_id": version_id, "status": 1},
            )
        )
        graph["nodes"][1]["data"]["group_params"][0]["params"][0]["value"]["agent_id"] = "mock:private"
        assert_resp_200(
            await client.put(
                f"{API_BASE}/workflow/versions/{version_id}", headers=author, json={"name": "v1", "data": graph}
            )
        )
        assert_resp_200(
            await client.patch(
                f"{API_BASE}/workflow/status",
                headers=author,
                json={"flow_id": flow_id, "version_id": version_id, "status": 2},
            )
        )
        rejected = assert_resp_200(
            await client.post(invocation_url, headers=runner, json={"workflow_id": flow_id, "stream": False})
        )
        assert "F119 Mock / B" not in json.dumps(rejected, ensure_ascii=False)
        assert "10555" in json.dumps(rejected)
        # 普通 B 只有 use。目录接口仍必须拒绝编辑资格。
        assert_resp_error(
            await client.get(f"{API_BASE}/workflow/platform-agents", headers=runner, params={"workflow_id": flow_id}),
            403,
        )
