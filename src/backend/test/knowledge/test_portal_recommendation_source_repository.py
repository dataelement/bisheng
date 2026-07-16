from datetime import datetime, timedelta, timezone

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
