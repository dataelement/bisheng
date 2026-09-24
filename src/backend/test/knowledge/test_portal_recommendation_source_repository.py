from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_source_repository_impl import (
    PortalRecommendationSourceRepositoryImpl,
)


def test_changed_after_normalizes_aware_watermark_to_naive_utc_database_parameter():
    local_offset = timezone(timedelta(hours=8))

    assert PortalRecommendationSourceRepositoryImpl._naive_utc(
        datetime(2026, 7, 15, 16, 30, tzinfo=local_offset)
    ) == datetime(2026, 7, 15, 8, 30)
    assert PortalRecommendationSourceRepositoryImpl._naive_utc(
        datetime(2026, 7, 15, 8, 30)
    ) == datetime(2026, 7, 15, 8, 30)


def test_source_mapping_carries_current_space_level():
    file = SimpleNamespace(
        id=41,
        knowledge_id=7,
        file_type=1,
        status=2,
        split_rule=None,
        file_encoding=None,
        file_level_path=None,
        update_time=datetime(2026, 7, 15, 8, 30),
        create_time=datetime(2026, 7, 14, 8, 30),
    )

    source = PortalRecommendationSourceRepositoryImpl._to_source(
        (file, True, KnowledgeSpaceLevelEnum.PERSONAL)
    )

    assert source.space_level == KnowledgeSpaceLevelEnum.PERSONAL.value


async def test_department_invalidation_queries_batches_and_deduplicates_users(async_db_session, monkeypatch):
    from sqlalchemy import text
    from unittest.mock import AsyncMock

    await async_db_session.execute(text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (21,1,1),(21,501,1),(22,999,1),(23,999,0)"))
    await async_db_session.commit()
    execute = AsyncMock(wraps=async_db_session.execute)
    monkeypatch.setattr(async_db_session, 'execute', execute)
    repo = PortalRecommendationSourceRepositoryImpl(async_db_session)
    result = await repo.primary_department_user_ids(list(range(1, 1002)) + [1, 501])
    assert result == [21, 22]
    assert execute.await_count == 3
