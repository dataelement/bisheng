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
