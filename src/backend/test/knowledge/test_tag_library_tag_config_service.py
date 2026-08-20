"""Tests for review-tag similarity threshold resolution."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.v1.schemas import KnowledgeSpaceConfig
from bisheng.core.config.settings import KnowledgeConf
from bisheng.knowledge.domain.services.tag_library_tag_config_service import (
    async_get_system_review_tag_similarity_threshold,
    get_system_review_tag_similarity_threshold,
    resolve_review_tag_similarity_threshold_async,
    resolve_review_tag_similarity_threshold_sync,
)


def test_system_threshold_default():
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.get_knowledge",
        return_value=KnowledgeConf(),
    ):
        assert get_system_review_tag_similarity_threshold() == 0.85


def test_system_threshold_from_knowledge_conf():
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.get_knowledge",
        return_value=KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.9}),
    ):
        assert get_system_review_tag_similarity_threshold() == 0.9


@pytest.mark.asyncio
async def test_async_system_threshold_from_knowledge_conf():
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.async_get_knowledge",
        new=AsyncMock(return_value=KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.92})),
    ):
        assert await async_get_system_review_tag_similarity_threshold() == 0.92


def test_tenant_override_wins_over_system():
    payload = json.dumps(
        KnowledgeSpaceConfig(review_tag_similarity_threshold=0.75).model_dump(mode="json"),
        ensure_ascii=True,
    )
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.get_knowledge",
        return_value=KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.9}),
    ), patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service._resolve_tenant_config_payload_sync",
        return_value=payload,
    ):
        assert resolve_review_tag_similarity_threshold_sync(2) == 0.75


def test_null_tenant_threshold_falls_back_to_system():
    payload = json.dumps(
        KnowledgeSpaceConfig(review_tag_visible=True).model_dump(mode="json"),
        ensure_ascii=True,
    )
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.get_knowledge",
        return_value=KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.88}),
    ), patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service._resolve_tenant_config_payload_sync",
        return_value=payload,
    ):
        assert resolve_review_tag_similarity_threshold_sync(2) == 0.88


@pytest.mark.asyncio
async def test_async_tenant_override():
    payload = json.dumps(
        KnowledgeSpaceConfig(review_tag_similarity_threshold=0.8).model_dump(mode="json"),
        ensure_ascii=True,
    )
    with patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service.bisheng_settings.async_get_knowledge",
        new=AsyncMock(return_value=KnowledgeConf(tag_library={"review_tag_similarity_threshold": 0.9})),
    ), patch(
        "bisheng.knowledge.domain.services.tag_library_tag_config_service._resolve_tenant_config_payload_async",
        new=AsyncMock(return_value=payload),
    ):
        assert await resolve_review_tag_similarity_threshold_async(2) == 0.8
