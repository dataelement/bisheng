from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.knowledge_migration import KnowledgeMigrationCandidateInvalidError
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.schemas.knowledge_migration_schema import MigrationBatchCreateRequest
from bisheng.knowledge.domain.services.knowledge_migration_service import KnowledgeMigrationService


def _space(space_id, owner_id, level):
    return SimpleNamespace(space=SimpleNamespace(id=space_id, name=f"space-{space_id}"), owner_id=owner_id, level=level)


@pytest.mark.parametrize("preserve_link", [False, True])
def test_invalid_owner_blocks_only_target_candidates(preserve_link):
    row = _space(10, 0, "team")
    source = KnowledgeMigrationService._space_response(row, purpose="source", preserve_link=preserve_link)
    target = KnowledgeMigrationService._space_response(row, purpose="target", preserve_link=preserve_link)
    assert source.selectable is True
    assert source.owner_valid is False
    assert source.unavailable_reason is None
    assert target.selectable is False
    assert target.unavailable_reason


@pytest.mark.parametrize("preserve_link", [False, True])
async def test_create_accepts_invalid_source_owner_but_rejects_invalid_target(preserve_link):
    source, target = _space(10, 0, "team"), _space(20, 7, "department")
    repository = SimpleNamespace(
        find_spaces_by_ids=AsyncMock(return_value=[source, target]),
        find_nodes=AsyncMock(return_value=[SimpleNamespace(
            id=100, file_type=FileType.FILE.value, file_name="document.pdf", file_level_path="",
        )]),
    )
    service = KnowledgeMigrationService(repository=None, source_repository=repository, dispatcher=None)
    request = MigrationBatchCreateRequest(
        request_id="ownerless-source",
        source_selections=[{"space_id": 10, "nodes": [{"node_type": "file", "node_id": 100}]}],
        target_space_id=20,
        preserve_link=preserve_link,
    )
    normalized = await service._normalize_create(request)
    assert normalized.source_spaces[0].owner_id == 0
    assert normalized.target_space.owner_id == 7
    target.owner_id = 0
    with pytest.raises(KnowledgeMigrationCandidateInvalidError):
        await service._normalize_create(request)
