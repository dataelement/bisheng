"""_scan_visible_child_items early-stop: permission-check only ~page_size items.

Root cause fixed here: the scan fetched a batch of up to
``_CHILD_PERMISSION_SCAN_BATCH_SIZE`` (100) rows and ran the ReBAC visibility
filter over the WHOLE batch before truncating to ``page_size``. Since each
ReBAC check is an OpenFGA round-trip, returning 10 visible items cost up to
~100 permission checks. The fix filters the batch in chunks and stops as soon
as ``page_size + 1`` visible items are found — same visible page, same order,
same ``has_more``, far fewer OpenFGA calls.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _make_svc(effective_ids_for):
    """Build a bare service with the permission plumbing stubbed.

    ``effective_ids_for(item) -> set[str]`` decides visibility per item and
    increments a call counter we assert on.
    """
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = Mock(user_id=1)
    svc._build_child_permission_context = AsyncMock(
        return_value={
            "can_view_all_statuses": True,  # skip status-hiding branch
            "tuple_cache": {},
            "tuple_department_paths": {},
            "models": {},
            "bindings": [],
            "binding_department_paths": {},
            "user_subject_strings": set(),
            "membership_permission_ids": set(),
            "public_space_permission_ids": set(),
        }
    )
    counter = {"checks": 0}

    async def _fake_effective(item, *, space_id, context):
        counter["checks"] += 1
        return effective_ids_for(item)

    svc._get_child_item_effective_permission_ids = _fake_effective
    return svc, counter


def _make_items(n):
    items = []
    for i in range(n):
        it = Mock()
        it.file_type = FileType.FILE.value
        it.id = i + 1
        it.status = 2  # SUCCESS
        items.append(it)
    return items


async def _scan(svc, items, page_size):
    with patch.object(SpaceFileDao, "async_list_children", new=AsyncMock(return_value=items)):
        return await svc._scan_visible_child_items(
            space_id=1,
            parent_id=None,
            file_ids=None,
            order_field="file_type",
            order_sort="asc",
            file_status=[2],
            file_type=None,
            page_size=page_size,
            cursor=None,
            exclude_file_ids=None,
        )


@pytest.mark.asyncio
async def test_scan_early_stops_permission_checks_when_items_visible():
    """All 50 items visible, page_size=10 → must NOT check all 50; ~page_size+1."""
    svc, counter = _make_svc(lambda item: {"view_file", "view_folder"})
    items = _make_items(50)

    page, has_more = await _scan(svc, items, page_size=10)

    assert has_more is True
    assert [it.id for it in page] == list(range(1, 11))
    # Early-stop: bounded to roughly page_size + 1, NOT the whole 50-item batch.
    assert counter["checks"] <= 12, f"checked {counter['checks']} items, expected <=12 (early-stop)"


@pytest.mark.asyncio
async def test_scan_returns_correct_page_with_partial_visibility():
    """Every 3rd item invisible → correct visible page, order and has_more."""
    invisible = {i for i in range(1, 51) if i % 3 == 0}  # 3,6,9,...
    svc, _counter = _make_svc(lambda item: set() if item.id in invisible else {"view_file"})
    items = _make_items(50)

    page, has_more = await _scan(svc, items, page_size=5)

    assert has_more is True
    # first 5 visible ids, skipping 3 and 6
    assert [it.id for it in page] == [1, 2, 4, 5, 7]
