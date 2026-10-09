"""Opt-in, read-only F074 checks against provisioned test spaces and models.

No resources are created or deleted. The model call uses the test credential's
normal quota and audit path. Never provide production credentials here.
"""

import os

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error
from test.e2e.helpers.auth import auth_headers

API_KEY = os.environ.get("E2E_KNOWLEDGE_ANSWER_API_KEY", "")
SPACE_ID = os.environ.get("E2E_KNOWLEDGE_ANSWER_SPACE_ID", "")
MODEL_ID = os.environ.get("E2E_KNOWLEDGE_ANSWER_MODEL_ID", "")
QUERY = os.environ.get("E2E_KNOWLEDGE_ANSWER_QUERY", "")
EMPTY_SPACE_ID = os.environ.get("E2E_KNOWLEDGE_ANSWER_EMPTY_SPACE_ID", "")
ANSWER_URL = f"{API_BASE.rsplit('/api/', 1)[0]}/api/v2/filelib/answer"

pytestmark = pytest.mark.skipif(
    not all((API_KEY, SPACE_ID, MODEL_ID, QUERY)),
    reason="F074 provisioned test API key, space, model and known-answer query are required",
)


class TestE2EKnowledgeAnswer:
    @pytest.fixture()
    async def client(self):
        async with httpx.AsyncClient(timeout=135) as client:
            yield client

    @pytest.fixture()
    def body(self):
        return {"query": QUERY, "knowledge_base_ids": [int(SPACE_ID)], "model_id": int(MODEL_ID)}

    async def test_ac01_answer_with_actual_reference_files(self, client, body):
        """AC-01/05: A provisioned known-answer question returns real file references."""
        response = await client.post(ANSWER_URL, headers=auth_headers(API_KEY), json=body)
        data = assert_resp_200(response)
        assert data["has_context"] is True
        assert data["model_id"] == int(MODEL_ID)
        assert isinstance(data["answer"], str) and data["answer"].strip()
        assert data["references"]
        assert all(item["knowledge_id"] == int(SPACE_ID) and item["document_id"] > 0 for item in data["references"])
        keys = [(item["knowledge_id"], item["document_id"]) for item in data["references"]]
        assert len(keys) == len(set(keys))

    async def test_ac08_missing_credential_is_rejected(self, client, body):
        """AC-08: The production router authenticates before knowledge execution."""
        response = await client.post(ANSWER_URL, json=body)
        assert response.status_code == 401
        assert_resp_error(response, expected_code=26001)

    async def test_ac13_identity_override_is_rejected(self, client, body):
        """AC-09/13: Business arguments cannot replace the authenticated actor."""
        response = await client.post(ANSWER_URL, headers=auth_headers(API_KEY), json={**body, "user_id": 1})
        assert response.status_code == 400
        payload = response.json()
        assert {"status_code", "status_message"} <= payload.keys()
        assert payload["status_code"] == 26019

    @pytest.mark.skipif(not EMPTY_SPACE_ID, reason="A provisioned empty test space is required")
    async def test_ac03_empty_space_does_not_expand_scope(self, client, body):
        """AC-03: An authorized empty space returns no context or references."""
        response = await client.post(
            ANSWER_URL,
            headers=auth_headers(API_KEY),
            json={**body, "knowledge_base_ids": [int(EMPTY_SPACE_ID)]},
        )
        data = assert_resp_200(response)
        assert data == {"answer": "未找到相关内容", "has_context": False, "model_id": int(MODEL_ID), "references": []}
