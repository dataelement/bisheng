from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.tag import Tag, TagResourceTypeEnum
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def test_resolve_new_tag_id_matches_resource_type():
    new_tags = [
        Tag(id=20, name="制度", resource_type=TagResourceTypeEnum.MANUAL_TAG.value),
        Tag(id=21, name="安全", resource_type=TagResourceTypeEnum.SYSTEM_TAG.value),
    ]
    assert (
        TagLibraryTagService._resolve_new_tag_id(
            "制度",
            TagResourceTypeEnum.MANUAL_TAG.value,
            new_tags,
        )
        == 20
    )


def test_resolve_new_tag_id_falls_back_across_system_and_manual():
    new_tags = [
        Tag(id=30, name="制度", resource_type=TagResourceTypeEnum.SYSTEM_TAG.value),
    ]
    assert (
        TagLibraryTagService._resolve_new_tag_id(
            "制度",
            TagResourceTypeEnum.MANUAL_TAG.value,
            new_tags,
        )
        == 30
    )


@pytest.mark.asyncio
async def test_remap_tag_links_after_library_replace_updates_stale_tag_ids():
    session = AsyncMock()
    session.exec = AsyncMock()
    old_id_by_key = {
        ("制度", TagResourceTypeEnum.MANUAL_TAG.value): 10,
        ("安全", TagResourceTypeEnum.SYSTEM_TAG.value): 11,
    }
    new_tags = [
        Tag(id=20, name="制度", resource_type=TagResourceTypeEnum.MANUAL_TAG.value),
        Tag(id=21, name="安全", resource_type=TagResourceTypeEnum.SYSTEM_TAG.value),
        Tag(id=22, name="新审核", resource_type=TagResourceTypeEnum.MANUAL_TAG.value),
    ]
    now = datetime.now()

    await TagLibraryTagService._remap_tag_links_after_library_replace(
        session,
        old_id_by_key=old_id_by_key,
        new_tags=new_tags,
        now=now,
    )

    assert session.exec.await_count == 2
