from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.api import dependencies


@pytest.mark.asyncio
async def test_fulltext_search_dependency_reuses_process_readiness_guard(monkeypatch):
    client = MagicMock()
    client.options.return_value = client
    monkeypatch.setattr(
        dependencies,
        "get_es_connection",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(dependencies, "_knowledge_fulltext_readiness_guard", None)
    monkeypatch.setattr(dependencies, "_knowledge_fulltext_readiness_client_id", None)

    first = await dependencies.get_knowledge_fulltext_search_service()
    second = await dependencies.get_knowledge_fulltext_search_service()

    assert first is not second
    assert first.repository is not second.repository
    assert first.readiness_guard is second.readiness_guard


@pytest.mark.asyncio
async def test_fulltext_search_dependency_replaces_guard_when_client_changes(monkeypatch):
    first_client = MagicMock()
    first_client.options.return_value = first_client
    second_client = MagicMock()
    second_client.options.return_value = second_client
    get_connection = AsyncMock(side_effect=[first_client, second_client])
    monkeypatch.setattr(dependencies, "get_es_connection", get_connection)
    monkeypatch.setattr(dependencies, "_knowledge_fulltext_readiness_guard", None)
    monkeypatch.setattr(dependencies, "_knowledge_fulltext_readiness_client_id", None)

    first = await dependencies.get_knowledge_fulltext_search_service()
    second = await dependencies.get_knowledge_fulltext_search_service()

    assert first.readiness_guard is not second.readiness_guard
