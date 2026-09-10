from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from elasticsearch import NotFoundError

from bisheng.common.errcode.knowledge import (
    KnowledgeFulltextIndexIncompatibleError,
    KnowledgeFulltextSearchUnavailableError,
    KnowledgeInvalidCursorError,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_cursor_repository_impl import (
    KnowledgeFulltextCursorRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexConfigurationError,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_search_schema import (
    KnowledgeFulltextAdvancedSearchQuery,
    KnowledgeFulltextSearchBatch,
    KnowledgeFulltextSearchHit,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_search_service import (
    KnowledgeFulltextReadinessGuard,
    KnowledgeFulltextSearchService,
)


def build_service(*, clock=lambda: 1.0):
    index_repository = AsyncMock()
    repository = AsyncMock()
    guard = KnowledgeFulltextReadinessGuard(
        index_repository,
        ttl_seconds=60,
        clock=clock,
    )
    return KnowledgeFulltextSearchService(repository=repository, readiness_guard=guard), repository, index_repository


async def test_readiness_is_cached_and_cursor_round_trips():
    service, repository, index_repository = build_service()
    repository.open_pit.return_value = "pit-1"
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[2, 1], all_keywords="制度")

    first = await service.begin(query, cursor=None)
    cursor = service.encode_next_cursor(
        first,
        sort_values=[2.0, "2026-01-01", 10, 99],
    )
    resumed = await service.begin(query, cursor=cursor)

    assert resumed.pit_id == "pit-1"
    assert resumed.search_after == [2.0, "2026-01-01", 10, 99]
    index_repository.validate_read_index.assert_awaited_once()
    repository.open_pit.assert_awaited_once()


async def test_cursor_rejects_changed_query_context():
    service, repository, _ = build_service()
    repository.open_pit.return_value = "pit-1"
    original = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1], all_keywords="制度")
    changed = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1], all_keywords="流程")
    session = await service.begin(original, cursor=None)
    cursor = service.encode_next_cursor(
        session,
        sort_values=[2.0, "2026-01-01", 10, 99],
    )

    with pytest.raises(KnowledgeInvalidCursorError):
        await service.begin(changed, cursor=cursor)


async def test_condition_cursor_rejects_changed_order_relation_or_mode():
    service, repository, _ = build_service()
    repository.open_pit.return_value = "pit-conditions"
    original = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        conditions=[
            {"relation": None, "field": "content", "match_mode": "exact", "value": "制度"},
            {"relation": "and", "field": "tags", "match_mode": "exact", "value": "设备"},
        ],
    )
    changed = KnowledgeFulltextAdvancedSearchQuery(
        space_ids=[1],
        conditions=[
            {"relation": None, "field": "content", "match_mode": "fuzzy", "value": "制度"},
            {"relation": "or", "field": "tags", "match_mode": "exact", "value": "设备"},
        ],
    )
    session = await service.begin(original, cursor=None)
    cursor = service.encode_next_cursor(
        session,
        sort_values=[2.0, "2026-01-01", 10, 99],
    )

    with pytest.raises(KnowledgeInvalidCursorError):
        await service.begin(changed, cursor=cursor)


async def test_mapping_incompatibility_fails_closed_before_opening_pit():
    service, repository, index_repository = build_service()
    index_repository.validate_read_index.side_effect = KnowledgeFulltextIndexConfigurationError("bad")
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1])

    with pytest.raises(KnowledgeFulltextIndexIncompatibleError):
        await service.begin(query, cursor=None)

    repository.open_pit.assert_not_awaited()


async def test_expired_pit_is_invalid_cursor_and_sort_contract_is_checked():
    service, repository, _ = build_service()
    repository.open_pit.return_value = "pit-1"
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1])
    session = await service.begin(query, cursor=None)
    repository.search.side_effect = NotFoundError("expired", meta=None, body=None)

    with pytest.raises(KnowledgeInvalidCursorError):
        await service.fetch(query, session, size=20)

    repository.search.side_effect = None
    repository.search.return_value = KnowledgeFulltextSearchBatch(
        pit_id="pit-2",
        hits=[KnowledgeFulltextSearchHit(file_id=1, sort_values=[1, 2])],
        exhausted=True,
    )
    with pytest.raises(KnowledgeFulltextIndexIncompatibleError):
        await service.fetch(query, session, size=20)


async def test_document_cursor_snapshots_are_replayable_and_reject_changed_scope_or_expiry(monkeypatch):
    values = {}

    async def save(key, value, *, ex):
        assert ex == 120
        values[key] = value
        return True

    redis = SimpleNamespace(
        async_connection=SimpleNamespace(
            set=save,
            get=AsyncMock(side_effect=lambda key: values.get(key)),
        )
    )
    service, repository, _ = build_service()
    service.cursor_repository = KnowledgeFulltextCursorRepositoryImpl(redis)
    repository.open_pit.return_value = "pit-documents"
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1], document_type="NEW")
    first = await service.begin(query, cursor=None, deduplicate_documents=True)
    token = await service.encode_document_cursor(
        first,
        sort_values=["2026-01-01", 42, 1],
        emitted_document_ids={2505},
    )
    resumed = await service.begin(query, cursor=token, deduplicate_documents=True)
    assert resumed.emitted_document_ids == {2505}
    assert resumed.search_after == ["2026-01-01", 42, 1]
    next_token = await service.encode_document_cursor(
        resumed,
        sort_values=["2026-01-02", 43, 2],
        emitted_document_ids={2505, 2506},
    )
    assert token != next_token
    replayed = await service.begin(query, cursor=token, deduplicate_documents=True)
    assert replayed == resumed
    assert first.emitted_document_ids == set()
    changed = query.model_copy(update={"space_ids": [2]})
    with pytest.raises(KnowledgeInvalidCursorError):
        await service.begin(changed, cursor=token, deduplicate_documents=True)
    with monkeypatch.context() as context:
        context.setattr(
            "bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_cursor_repository_impl.get_current_tenant_id",
            lambda: 999,
        )
        with pytest.raises(KnowledgeInvalidCursorError):
            await service.begin(query, cursor=token, deduplicate_documents=True)
    values.clear()
    with pytest.raises(KnowledgeInvalidCursorError):
        await service.begin(query, cursor=token, deduplicate_documents=True)


@pytest.mark.parametrize("operation", ["load", "save"])
async def test_document_cursor_storage_failure_does_not_reset_pagination(monkeypatch, operation):
    # 全局 fixture 将 redis.exceptions 预先 mock。这里恢复真实异常类的行为。
    class RedisConnectionError(Exception):
        pass

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_fulltext_search_service.RedisError",
        RedisConnectionError,
    )
    service, repository, _ = build_service()
    repository.open_pit.return_value = "pit-1"
    service.cursor_repository = AsyncMock()
    getattr(service.cursor_repository, operation).side_effect = RedisConnectionError("unavailable")
    query = KnowledgeFulltextAdvancedSearchQuery(space_ids=[1], document_type="NEW")
    with pytest.raises(KnowledgeFulltextSearchUnavailableError):
        if operation == "load":
            await service.begin(query, cursor="missing", deduplicate_documents=True)
        else:
            session = await service.begin(query, cursor=None, deduplicate_documents=True)
            await service.encode_document_cursor(
                session,
                sort_values=["2026-01-01", 42, 1],
                emitted_document_ids={2505},
            )
