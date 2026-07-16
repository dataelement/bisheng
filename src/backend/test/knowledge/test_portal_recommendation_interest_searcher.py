from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.repositories.interfaces.portal_recommendation_telemetry_repository import (
    PortalSearchQuerySignal,
)
from bisheng.knowledge.domain.services.portal_recommendation_interest_searcher import (
    PortalRecommendationContentSearcher,
)


@pytest.mark.asyncio
async def test_production_interest_search_uses_weight_fields_and_projection_allowlist():
    captured = {}

    async def search_es(index_names, body):
        captured.update(index_names=index_names, body=body)
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {"metadata": {"document_id": 101}},
                        "matched_queries": ["q0:title", "q0:tag", "q1:summary"],
                    },
                    {
                        "_source": {"metadata": {"document_id": 999}},
                        "matched_queries": ["q0:title"],
                    },
                ]
            }
        }

    searcher = PortalRecommendationContentSearcher(
        projection_loader=lambda: [
            SimpleNamespace(file_id=101, space_id=10, recommendable=True),
            SimpleNamespace(file_id=102, space_id=10, recommendable=False),
        ],
        space_loader=lambda _ids: [SimpleNamespace(id=10, index_name="space-10")],
        es_searcher=search_es,
    )
    signals = [
        PortalSearchQuerySignal("steel", datetime.now(timezone.utc), 1),
        PortalSearchQuerySignal("safety", datetime.now(timezone.utc), 1),
    ]
    token = current_tenant_id.set(5)
    try:
        hits = await searcher.search(5, signals, 50)
    finally:
        current_tenant_id.reset(token)

    assert captured["index_names"] == ["space-10"]
    assert captured["body"]["query"]["bool"]["filter"] == [
        {"terms": {"metadata.document_id": [101]}}
    ]
    names = {
        next(iter(item["match"].values()))["_name"]
        for item in captured["body"]["query"]["bool"]["should"]
    }
    assert {"q0:title", "q0:tag", "q0:summary"}.issubset(names)
    assert [(hit.space_id, hit.file_id) for hit in hits] == [(10, 101)]
    assert hits[0].query_field_scores["steel"] == (1.0, 1.0, 0.0)
    assert hits[0].query_field_scores["safety"] == (0.0, 0.0, 1.0)
