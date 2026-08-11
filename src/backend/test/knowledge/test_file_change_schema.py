from __future__ import annotations

import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    FileChangeResourceType,
    KnowledgeSpaceFileChangeDetailResp,
)


def _detail(resource_type: str) -> KnowledgeSpaceFileChangeDetailResp:
    return KnowledgeSpaceFileChangeDetailResp(
        request_id=1,
        space_id=2,
        action="rename",
        resource_type=resource_type,
        resource_id=3,
        resource_name="quarterly.pdf",
        applicant_user_id=4,
        status="pending",
    )


def test_detail_explicitly_maps_internal_knowledge_file_to_public_file():
    assert _detail("knowledge_file").resource_type == FileChangeResourceType.FILE


def test_detail_rejects_version_footprint_as_root_resource():
    with pytest.raises(ValidationError):
        _detail("knowledge_file_version")
