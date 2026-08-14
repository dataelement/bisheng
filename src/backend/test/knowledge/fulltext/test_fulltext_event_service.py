from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.knowledge_fulltext_event_service import (
    KnowledgeFulltextEventService,
)


async def test_event_service_passes_only_ids_action_and_diagnostics_to_repository():
    repository = AsyncMock()
    service = KnowledgeFulltextEventService(repository, multi_tenant_enabled=False)

    await service.request_file_sync(
        file_id=7,
        knowledge_id=9,
        trigger_type="metadata_updated",
        tenant_id=1,
    )

    payload = repository.request_sync.await_args.kwargs
    assert payload["aggregate_id"] == 7
    assert payload["knowledge_id"] == 9
    assert payload["desired_action"].value == "sync_current"
    assert not {"content", "document", "user_metadata"}.intersection(payload)


async def test_event_service_rejects_multi_tenant():
    repository = AsyncMock()
    with pytest.raises(ValueError, match="multi-tenant"):
        KnowledgeFulltextEventService(repository, multi_tenant_enabled=True)
