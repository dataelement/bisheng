"""Round-trip tests for tenant review_tag_similarity_threshold persistence."""

import importlib
import json
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

base_service_stub = types.ModuleType("bisheng.common.services.base")


class _BaseService:
    pass


base_service_stub.BaseService = _BaseService
sys.modules["bisheng.common.services.base"] = base_service_stub
workstation_service = importlib.reload(
    importlib.import_module("bisheng.workstation.domain.services.workstation_service")
)

from bisheng.api.v1.schemas import KnowledgeSpaceConfig
from bisheng.common.models.config import ConfigKeyEnum

WorkStationService = workstation_service.WorkStationService


@pytest.mark.asyncio
async def test_update_knowledge_space_config_persists_similarity_threshold():
    stored: dict[str, str] = {}

    async def fake_aresolve(key):
        assert key == ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE
        return stored.get("value"), False, 1, bool(stored.get("value"))

    async def fake_aupsert(key, payload):
        assert key == ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE
        stored["value"] = payload

    with (
        patch.object(WorkStationService, "_aresolve_tenant_config", new=AsyncMock(side_effect=fake_aresolve)),
        patch.object(WorkStationService, "_aupsert_tenant_config", new=AsyncMock(side_effect=fake_aupsert)),
        patch.object(WorkStationService, "_multi_tenant_enabled", return_value=True),
        patch.object(WorkStationService, "_current_tenant_id", return_value=1),
    ):
        saved = await WorkStationService.update_knowledge_space_config(
            KnowledgeSpaceConfig(
                system_prompt="sys",
                user_prompt="user",
                max_chunk_size=15000,
                auto_tag_visible=True,
                review_tag_visible=True,
                review_tag_similarity_threshold=0.72,
            )
        )

    payload = json.loads(stored["value"])
    assert payload["review_tag_similarity_threshold"] == 0.72
    assert saved.review_tag_similarity_threshold == 0.72


@pytest.mark.asyncio
async def test_update_knowledge_space_config_merges_with_existing_payload():
    existing = KnowledgeSpaceConfig(
        system_prompt="old-sys",
        user_prompt="old-user",
        max_chunk_size=12000,
        auto_tag_visible=False,
        review_tag_visible=True,
        review_tag_similarity_threshold=0.7,
    ).model_dump(mode="json")
    stored = {"value": json.dumps(existing, ensure_ascii=True)}

    async def fake_aresolve(key):
        return stored.get("value"), False, 1, True

    async def fake_aupsert(key, payload):
        stored["value"] = payload

    with (
        patch.object(WorkStationService, "_aresolve_tenant_config", new=AsyncMock(side_effect=fake_aresolve)),
        patch.object(WorkStationService, "_aupsert_tenant_config", new=AsyncMock(side_effect=fake_aupsert)),
        patch.object(WorkStationService, "_multi_tenant_enabled", return_value=True),
        patch.object(WorkStationService, "_current_tenant_id", return_value=1),
    ):
        saved = await WorkStationService.update_knowledge_space_config(
            KnowledgeSpaceConfig(
                system_prompt="old-sys",
                user_prompt="old-user",
                max_chunk_size=12000,
                auto_tag_visible=False,
                review_tag_visible=True,
                review_tag_similarity_threshold=0.91,
            )
        )

    payload = json.loads(stored["value"])
    assert payload["review_tag_similarity_threshold"] == 0.91
    assert saved.review_tag_similarity_threshold == 0.91
