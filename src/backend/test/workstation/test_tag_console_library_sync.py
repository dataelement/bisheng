"""A library's own name list has to follow the tag rows the console writes.

Regression for "删除标签后标签数据再次出现". A tag library keeps a second copy of
its tag names in its own columns, left from before the names lived in ``tag``.
The console deleted tag rows without touching that copy, so a library could end
up with zero rows but a non-empty name list — which is exactly what
``_ensure_tags_materialized`` treats as "the migration missed this library",
rebuilding every name the moment someone opened the library detail. Deleted tags
came back.

Ordering matters as much as the call itself: the resync reads the tag rows back
through its own session, so running it before the commit would re-persist the
state that was just supposed to change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagScope
from bisheng.workstation.domain.services.tag_console_service import TagConsoleService

TENANT_ID = 1
LIB_A, LIB_B, LIB_TARGET = 2, 3, 9


def _tag(tag_id: int, library_id: int, name: str = "结垢") -> Tag:
    return Tag(
        id=tag_id,
        name=name,
        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
        business_id=str(library_id),
        user_id=1,
        tenant_id=TENANT_ID,
        resource_type=TagResourceTypeEnum.SYSTEM_TAG.value,
    )


def _build_service(found: list[Tag], calls: list[str]):
    repository = AsyncMock()
    repository.get_library_tags_by_ids.return_value = found
    repository.library_exists.return_value = True
    repository.find_library_tag_by_name.return_value = None
    repository.session.commit = AsyncMock(side_effect=lambda: calls.append("commit"))

    tags_service = AsyncMock()
    tags_service.resolve_review_tag_scope.return_value = ReviewTagScope(full_tenant=True)
    return TagConsoleService(
        login_user=SimpleNamespace(
            user_id=1,
            tenant_id=TENANT_ID,
            is_global_super=False,
            is_admin=lambda: True,
            has_tenant_admin=AsyncMock(return_value=False),
        ),
        repository=repository,
        tags_service=tags_service,
    )


def _patch_sync(calls: list[str]):
    async def _record(library_id: int) -> None:
        calls.append(f"sync:{library_id}")

    return patch(
        "bisheng.workstation.domain.services.tag_console_service.TagLibraryTagService.sync_library_name_lists",
        new=AsyncMock(side_effect=_record),
    )


def _patch_cache():
    return patch(
        "bisheng.workstation.domain.services.tag_console_service."
        "TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async",
        new=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_delete_resyncs_every_library_it_touched():
    calls: list[str] = []
    service = _build_service([_tag(1, LIB_A), _tag(2, LIB_B, "边裂")], calls)

    with _patch_sync(calls), _patch_cache():
        result = await service.batch_delete([1, 2], TENANT_ID)

    assert result.succeeded == 2
    assert calls == ["commit", f"sync:{LIB_A}", f"sync:{LIB_B}"], (
        "both libraries must be resynced, and only after the delete is committed"
    )


@pytest.mark.asyncio
async def test_move_resyncs_both_ends():
    calls: list[str] = []
    service = _build_service([_tag(1, LIB_A)], calls)

    with _patch_sync(calls), _patch_cache():
        result = await service.batch_move([1], LIB_TARGET, TENANT_ID)

    assert result.succeeded == 1
    assert calls == ["commit", f"sync:{LIB_A}", f"sync:{LIB_TARGET}"], "the tag leaves one name list and joins another"


@pytest.mark.asyncio
async def test_nothing_moved_means_nothing_to_resync():
    """A tag already sitting in the target is skipped, so no list changed."""
    calls: list[str] = []
    service = _build_service([_tag(1, LIB_TARGET)], calls)

    with _patch_sync(calls), _patch_cache():
        result = await service.batch_move([1], LIB_TARGET, TENANT_ID)

    assert result.skipped == 1
    assert calls == []


@pytest.mark.asyncio
async def test_library_ids_ignores_unparseable_business_ids():
    """Legacy rows may hold something that is not a bare library id."""
    tags = [_tag(1, LIB_A), Tag(id=2, name="x", business_id=None, business_type="tag_library")]

    assert TagConsoleService._library_ids_of(tags) == {LIB_A}
