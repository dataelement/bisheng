"""覆盖 AC: AC-07, AC-08, AC-09, AC-11, AC-12, AC-18。仅在专用环境显式运行。"""

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200
from test.e2e.helpers.auth import auth_headers, get_user_token

EXAMPLE = Path(__file__).parents[4] / "features/v3.0.0/120-kunlian-knowledge-retrieval/mock-workflow.example.json"


@pytest.fixture
async def environment():
    if os.environ.get("F120_MOCK_E2E") != "1":
        pytest.skip("NOT_RUN: 需要专用 API、Broker、Worker 和测试账号")
    required = (
        "F120_AUTHOR_USERNAME",
        "F120_AUTHOR_PASSWORD",
        "F120_RUNNER_USERNAME",
        "F120_RUNNER_PASSWORD",
        "F120_TENANT_ID",
        "F120_USE_MODEL_KEY",
    )
    assert all(os.environ.get(key) for key in required), "缺少 F120 专用环境参数"
    tenant_id = int(os.environ["F120_TENANT_ID"])
    assert tenant_id > 1
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        author, runner = [
            auth_headers(
                await get_user_token(client, os.environ[f"F120_{role}_USERNAME"], os.environ[f"F120_{role}_PASSWORD"])
            )
            for role in ("AUTHOR", "RUNNER")
        ]
        owner, actor = [
            assert_resp_200(await client.get(f"{API_BASE}/user/info", headers=headers)) for headers in (author, runner)
        ]
        assert owner["tenant_id"] == actor["tenant_id"] == tenant_id
        assert owner["user_id"] != actor["user_id"] and actor.get("role") != "admin"
        env = assert_resp_200(await client.get(f"{API_BASE}/env"))
        assert env["workflow"]["platform_knowledge_mode"] == "mock"
        yield client, author, runner, owner, actor


async def test_published_mock_runs_through_broker_and_worker(environment):
    client, author, runner, owner, actor = environment
    name = f"e2e-f120-{uuid4().hex}"
    graph = json.loads(EXAMPLE.read_text())
    created = await client.post(
        f"{API_BASE}/workflow/create",
        headers=author,
        json={"name": name, "description": "F120 Mock fixture", "data": graph},
    )
    assert created.status_code in (200, 201)
    envelope = created.json()
    assert envelope["status_code"] == 200
    flow_id, version_id = envelope["data"]["id"], envelope["data"]["version_id"]
    try:
        directory = assert_resp_200(
            await client.get(
                f"{API_BASE}/workflow/platform-knowledge",
                headers=author,
                params={"workflow_id": flow_id},
            )
        )
        assert any(item["resource_id"] == "mock:maintenance" for item in directory["items"])
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
                            "model_key": os.environ["F120_USE_MODEL_KEY"],
                            "subject": {"type": "user", "id": str(actor["user_id"])},
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
        invoke = API_BASE.removesuffix("/api/v1") + "/api/v2/workflow/invoke"
        started = assert_resp_200(
            await client.post(invoke, headers=runner, json={"workflow_id": flow_id, "stream": False})
        )
        waiting = next(event for event in started["events"] if event["node_id"] == "input_example")
        result = assert_resp_200(
            await client.post(
                invoke,
                headers=runner,
                json={
                    "workflow_id": flow_id,
                    "stream": False,
                    "session_id": started["session_id"],
                    "message_id": waiting["message_id"],
                    "input": {"input_example": {"question": "轴承温度异常如何处理?"}},
                },
            )
        )
        assert any("润滑" in str(event.get("output_schema")) for event in result["events"])
    finally:
        current = assert_resp_200(await client.get(f"{API_BASE}/workflow/get_one_flow/{flow_id}", headers=author))
        assert (current["name"], current["tenant_id"], current["user_id"]) == (
            name,
            owner["tenant_id"],
            owner["user_id"],
        )
        assert_resp_200(await client.delete(f"{API_BASE}/flows/{flow_id}", headers=author))
