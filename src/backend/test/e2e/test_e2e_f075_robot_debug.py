"""Opt-in, read-only F075 acceptance against a prepared diagnostic deployment.

No accounts, bindings or files are created/cleaned by this suite. The operator
prepares an e2e-f075- assistant and dedicated admin/ordinary-user credentials.
"""

import json
import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.getenv("E2E_F075_ENABLED") != "true", reason="explicit debug acceptance opt-in required"),
]
PREFIX = "e2e-f075-"
DEBUG_BASE = API_BASE.rsplit("/api/v1", 1)[0] + "/robot-debug/api"


class TestE2ERobotDebug:
    @pytest.fixture
    async def prepared(self):
        required = ["E2E_ADMIN_TOKEN", "E2E_F075_USER_TOKEN", "E2E_F075_ASSISTANT_ID", "E2E_F075_TEST_USER_ID"]
        if any(not os.getenv(key) for key in required):
            pytest.fail("dedicated F075 acceptance identity/assistant inputs required")
        async with httpx.AsyncClient(timeout=200) as client:
            assistant_id = os.environ["E2E_F075_ASSISTANT_ID"]
            path = f"{DEBUG_BASE}/assistants/{assistant_id}"
            headers = auth_headers(os.environ["E2E_ADMIN_TOKEN"])
            response = await client.get(
                path + "/context", headers=headers, params={"test_user_id": int(os.environ["E2E_F075_TEST_USER_ID"])}
            )
            context = assert_resp_200(response)
            assert context["assistant_name"].startswith(PREFIX), "only a dedicated F075 test assistant is allowed"
            yield client, path, headers, context

    async def test_ac01_admin_and_ordinary_identity_are_paired(self, prepared):
        """AC-01/09: Real authenticated context is permitted only to admins."""
        client, path, _headers, context = prepared
        assert context["space_ids"] and context["test_user_id"] > 0
        rejected = await client.get(path + "/context", headers=auth_headers(os.environ["E2E_F075_USER_TOKEN"]))
        assert rejected.status_code == 403
        assert_resp_error(rejected, 403)
        anonymous = await client.get(DEBUG_BASE + "/status")
        assert anonymous.status_code == 401
        assert_resp_error(anonymous, 401)

    async def test_ac04_browser_scope_override_is_rejected(self, prepared):
        """AC-04: A real route rejects browser-supplied extra space scope."""
        client, path, headers, context = prepared
        response = await client.post(
            path + "/run",
            headers=headers,
            json={"query": "search", "test_user_id": context["test_user_id"], "space_ids": [999999]},
        )
        assert response.status_code == 422

    async def test_ac05_real_model_stream_exposes_ordered_tool_results(self, prepared):
        """AC-05/06/07: A real model run ends once and preserves tool output."""
        client, path, headers, context = prepared
        events = []
        async with client.stream(
            "POST",
            path + "/run",
            headers=headers,
            json={
                "query": os.getenv(
                    "E2E_F075_QUERY", "Summarize a document from the bound knowledge spaces and identify its source."
                ),
                "test_user_id": context["test_user_id"],
                "history": [],
            },
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert events[-1]["type"] == "completed"
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert len({e["run_id"] for e in events}) == 1
        assert sum(e["type"] in {"completed", "failed"} for e in events) == 1
        assert events[-1]["data"]["tool_call_count"] == sum(e["type"] == "tool_start" for e in events)
        for event in events:
            if event["type"] == "tool_end":
                assert isinstance(event["data"]["model_tool_output"], str)
                assert isinstance(event["data"].get("retrieval_metadata", []), list)
