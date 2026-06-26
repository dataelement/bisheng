import pytest
from pydantic import ValidationError
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFavoriteRemoveReq,
    ShougangPortalFavoriteStatusReq,
    ShougangPortalFavoriteFileItem,
)


def test_create_req_drops_target_space_id():
    req = ShougangPortalFavoriteCreateReq(source_space_id=1, source_file_id=2)
    assert req.source_space_id == 1 and req.source_file_id == 2
    assert not hasattr(req, "target_space_id")


def test_create_req_rejects_non_positive():
    with pytest.raises(ValidationError):
        ShougangPortalFavoriteCreateReq(source_space_id=0, source_file_id=2)


def test_status_req_parses_items():
    req = ShougangPortalFavoriteStatusReq(items=[{"space_id": 1, "file_id": 9}])
    assert req.items[0].file_id == 9


def test_file_item_status_literal():
    item = ShougangPortalFavoriteFileItem(
        favorite_file_id=5, source_space_id=1, source_file_id=2,
        title="t", file_name="t.pdf", status="invalid", updated_at="",
    )
    assert item.status == "invalid"
    with pytest.raises(ValidationError):
        ShougangPortalFavoriteFileItem(
            favorite_file_id=5, source_space_id=1, source_file_id=2,
            title="t", file_name="t.pdf", status="weird", updated_at="",
        )
