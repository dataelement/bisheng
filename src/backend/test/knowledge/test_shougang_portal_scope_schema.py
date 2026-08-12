import pytest

from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalAdvancedFileSearchReq,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileSearchReq,
)


@pytest.mark.parametrize(
    "schema_type",
    [
        ShougangPortalFileBrowseReq,
        ShougangPortalFileSearchReq,
        ShougangPortalAdvancedFileSearchReq,
    ],
)
def test_portal_file_request_accepts_268_space_ids(schema_type):
    space_ids = list(range(1, 269))

    request = schema_type(space_ids=space_ids)

    assert request.space_ids == space_ids


@pytest.mark.parametrize(
    "schema_type",
    [
        ShougangPortalFileBrowseReq,
        ShougangPortalFileSearchReq,
        ShougangPortalAdvancedFileSearchReq,
    ],
)
def test_portal_file_request_accepts_more_than_1000_space_ids(schema_type):
    space_ids = list(range(1, 1328))

    request = schema_type(space_ids=space_ids)

    assert request.space_ids == space_ids
