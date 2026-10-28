"""Work retrieval preserves authenticated service scope and bounded inputs."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bisheng.knowledge.api.dependencies import (
    get_knowledge_document_version_repository,
    get_knowledge_space_chat_service,
)
from bisheng.knowledge.api.endpoints.knowledge_space import router


class WorkRetrievalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.service = SimpleNamespace(
            login_user=SimpleNamespace(user_id=27, tenant_id=1),
            aretrieve_chunks=AsyncMock(return_value=[]),
        )
        self.catalog = AsyncMock(return_value={91: SimpleNamespace(tool_key="bisheng_knowledge_search")})
        catalog_patch = patch(
            "bisheng.dsh.domain.services.work_capabilities.WorkCapabilitiesService._tools", self.catalog
        )
        catalog_patch.start()
        self.addCleanup(catalog_patch.stop)
        self.version_repo = object()
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_knowledge_space_chat_service] = lambda: self.service
        self.app.dependency_overrides[get_knowledge_document_version_repository] = lambda: self.version_repo
        self.client = TestClient(self.app)

    def test_exact_scope_and_sources(self):
        self.service.aretrieve_chunks.return_value = [
            (
                7,
                SimpleNamespace(
                    page_content="Policy passage",
                    metadata={"document_id": 12, "document_name": "Policy.pdf", "chunk_index": 3},
                ),
            ),
            (
                9,
                SimpleNamespace(
                    page_content="Budget marker K2",
                    metadata={"document_id": 13, "document_name": "Budget.pdf", "chunk_index": 1},
                ),
            ),
        ]
        response = self.client.post(
            "/knowledge/space/retrieve", json={"query": " leave policy ", "space_ids": [7, 7, 9]}
        )
        self.assertEqual(response.status_code, 200)
        self.service.aretrieve_chunks.assert_awaited_once_with(
            query="leave policy", knowledge_base_ids=[7, 9], top_k=10, max_content=12000
        )
        self.assertIs(self.service.version_repo, self.version_repo)
        self.assertEqual(
            response.json()["data"]["chunks"],
            [
                {
                    "content": "Policy passage",
                    "space_id": 7,
                    "document_id": 12,
                    "document_name": "Policy.pdf",
                    "chunk_index": 3,
                },
                {
                    "content": "Budget marker K2",
                    "space_id": 9,
                    "document_id": 13,
                    "document_name": "Budget.pdf",
                    "chunk_index": 1,
                },
            ],
        )

    def test_missing_catalog_blocks_retrieval_before_accessing_documents(self):
        self.catalog.return_value = {}
        response = self.client.post("/knowledge/space/retrieve", json={"query": "q", "space_ids": [7, 9]})
        self.assertEqual(response.status_code, 403)
        self.assertIn("Enable this tool", response.json()["detail"])
        self.service.aretrieve_chunks.assert_not_awaited()

    def test_permission_failure_propagates(self):
        self.service.aretrieve_chunks.side_effect = HTTPException(status_code=403, detail="Forbidden")
        response = self.client.post("/knowledge/space/retrieve", json={"query": "q", "space_ids": [7]})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("chunks", response.text)

    def test_login_dependency_is_required(self):
        async def require_login():
            raise HTTPException(status_code=401, detail="Login required")

        self.app.dependency_overrides[get_knowledge_space_chat_service] = require_login
        response = self.client.post("/knowledge/space/retrieve", json={"query": "q", "space_ids": [7]})
        self.assertEqual(response.status_code, 401)
        self.service.aretrieve_chunks.assert_not_awaited()

    def test_rejects_unbounded_or_ambiguous_input(self):
        for body in [
            {"query": " ", "space_ids": [7]},
            {"query": "q" * 4001, "space_ids": [7]},
            {"query": "q", "space_ids": []},
            {"query": "q", "space_ids": [7] * 51},
            {"query": "q", "space_ids": ["7"]},
            {"query": "q", "space_ids": [True]},
            {"query": "q", "space_ids": [-1]},
            {"query": "q", "space_ids": [7], "tenant_id": 2},
        ]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/knowledge/space/retrieve", json=body).status_code, 422)
        self.service.aretrieve_chunks.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
