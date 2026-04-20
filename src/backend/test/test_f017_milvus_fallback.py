"""F017 unit tests — Milvus-layer Child→Root fallback (T20).

The Milvus fallback is not a collection-name rewrite (like MinIO paths);
it is a knowledge-id expansion: a Child retrieval is extended to include
every Root-shared ``knowledge.id`` the Child is authorized to read via
F017 FGA tuples. These tests exercise
``KnowledgeRag.aexpand_with_root_shared`` without hitting MySQL / Milvus.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag


def _fake_settings(multi_tenant_enabled: bool):
    s = MagicMock()
    s.multi_tenant = MagicMock()
    s.multi_tenant.enabled = multi_tenant_enabled
    return s


@pytest.mark.asyncio
async def test_expand_adds_root_shared_ids_for_child_leaf():
    """Child leaf → union with Root-shared, preserves caller order, dedups."""
    with patch(
        'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
        AsyncMock(return_value=[7, 8]),
    ), patch(
        'bisheng.common.services.config_service.settings', _fake_settings(True),
    ):
        result = await KnowledgeRag.aexpand_with_root_shared(
            [1, 2, 3], leaf_tenant_id=5,
        )
    assert result == [1, 2, 3, 7, 8]


@pytest.mark.asyncio
async def test_expand_dedups_when_caller_already_included_root_id():
    with patch(
        'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
        AsyncMock(return_value=[3, 7]),
    ), patch(
        'bisheng.common.services.config_service.settings', _fake_settings(True),
    ):
        result = await KnowledgeRag.aexpand_with_root_shared(
            [1, 3], leaf_tenant_id=5,
        )
    assert result == [1, 3, 7]  # 3 kept at original position, 7 appended


@pytest.mark.asyncio
async def test_expand_noop_for_root_leaf():
    """Root users already see every Root knowledge, no expansion needed."""
    with patch(
        'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
    ) as fetch_mock:
        result = await KnowledgeRag.aexpand_with_root_shared(
            [1, 2, 3], leaf_tenant_id=1,  # Root
        )
    assert result == [1, 2, 3]
    fetch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_expand_noop_when_multi_tenant_disabled():
    with patch(
        'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
    ) as fetch_mock, patch(
        'bisheng.common.services.config_service.settings', _fake_settings(False),
    ):
        result = await KnowledgeRag.aexpand_with_root_shared(
            [1, 2], leaf_tenant_id=5,
        )
    assert result == [1, 2]
    fetch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_expand_noop_when_no_root_shared_rows():
    with patch(
        'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
        AsyncMock(return_value=[]),
    ), patch(
        'bisheng.common.services.config_service.settings', _fake_settings(True),
    ):
        result = await KnowledgeRag.aexpand_with_root_shared(
            [1, 2], leaf_tenant_id=5,
        )
    assert result == [1, 2]


@pytest.mark.asyncio
async def test_expand_reads_context_var_when_leaf_not_supplied():
    """Default leaf_tenant_id=None reads from ContextVar."""
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.knowledge.domain.knowledge_rag.KnowledgeRag._afetch_root_shared_knowledge_ids',
            AsyncMock(return_value=[9]),
        ), patch(
            'bisheng.common.services.config_service.settings', _fake_settings(True),
        ):
            result = await KnowledgeRag.aexpand_with_root_shared([1])
    finally:
        current_tenant_id.reset(token)
    assert result == [1, 9]
