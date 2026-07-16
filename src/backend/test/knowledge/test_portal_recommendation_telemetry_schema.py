import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalTelemetryEventReq


def test_portal_search_query_is_server_normalized_and_requires_search_entry_point():
    event = ShougangPortalTelemetryEventReq(
        event_type="portal_search",
        source_app="shougang_portal",
        scene="knowledge_search",
        entry_point="search_page",
        query="  Safety   安全  ",
        normalized_query="client cannot override this",
    )

    assert event.query == "Safety 安全"
    assert event.normalized_query == "safety 安全"

    with pytest.raises(ValidationError):
        ShougangPortalTelemetryEventReq(
            event_type="portal_search",
            source_app="shougang_portal",
            scene="knowledge_search",
            entry_point="pagination",
            query="steel",
        )


def test_document_read_accepts_exact_source_and_recommendation_scene():
    event = ShougangPortalTelemetryEventReq(
        event_type="portal_document_read",
        source_app="shougang_portal",
        scene="document_preview",
        entry_point="home_recommendation",
        recommendation_scene="personalized_v1",
        space_id=10,
        file_id=100,
    )
    assert event.recommendation_scene == "personalized_v1"

    with pytest.raises(ValidationError):
        ShougangPortalTelemetryEventReq(
            event_type="portal_document_read",
            source_app="shougang_portal",
            scene="document_preview",
            entry_point="unknown-client-value",
            space_id=10,
            file_id=100,
        )
