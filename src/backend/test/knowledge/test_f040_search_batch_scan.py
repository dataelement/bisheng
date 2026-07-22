"""F040 (C) T6c: keyword space search batch-scans the candidate set with early
stop instead of fetching every match, ReBAC-filtering all of it, then Python-
slicing one page.

Equivalence red line: for any page, ``_scan_visible_search_items`` must return the
SAME visible items, in the SAME (id-tie-broken) order, as "fetch all candidates →
filter visibility → slice the page"; ``has_more`` must be exact; and the scan must
STOP EARLY (not exhaust the candidate set) once the page is filled — that early
stop is the whole point of the optimization.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_KS = "bisheng.knowledge.domain.services.knowledge_space_service"


class _User:
    user_id = 5
    tenant_id = 1

    def is_admin(self):
        return False


def _candidates(n: int):
    """Ordered candidate rows (already in the DAO's sort + id-tiebreak order)."""
    return [SimpleNamespace(id=i, file_name=f"f{i}.txt", file_type=0) for i in range(n)]


def _install(all_candidates, visible_ids, *, batch_size=4):
    """Patch the DAO (OFFSET batches over `all_candidates`), the visibility filter
    (keep ids in `visible_ids`, order preserved), the permission context, and the
    scan batch size. Returns the DAO call counter dict."""
    counter = {"dao_calls": 0, "max_offset_end": 0}

    async def _fake_dao(
        space_id,
        *,
        file_name,
        file_ids,
        extra_file_ids,
        status,
        file_level_path,
        order_by,
        order_field,
        order_sort,
        exclude_file_ids,
        page,
        page_size,
        id_tiebreaker,
    ):
        assert id_tiebreaker is True, "batch-scan must request a deterministic id-tie-broken order"
        counter["dao_calls"] += 1
        start = (page - 1) * page_size
        end = start + page_size
        counter["max_offset_end"] = max(counter["max_offset_end"], end)
        return all_candidates[start:end]

    async def _fake_filter(self, items, *, space_id, context=None):
        return [it for it in items if it.id in visible_ids]

    patchers = [
        patch(f"{_KS}.KnowledgeFileDao.aget_file_by_filters", new=_fake_dao),
        patch.object(KnowledgeSpaceService, "_filter_visible_child_items", _fake_filter),
        patch.object(KnowledgeSpaceService, "_build_child_permission_context", new=AsyncMock(return_value={})),
        patch(f"{_KS}._SEARCH_SCAN_BATCH_SIZE", batch_size),
    ]
    return counter, patchers


async def _scan(svc, *, page, page_size):
    return await svc._scan_visible_search_items(
        space_id=1,
        file_name="kw",
        filter_files=None,
        extra_file_ids=None,
        file_status=None,
        file_level_path=None,
        order_field="file_type",
        order_sort="asc",
        exclude_file_ids=None,
        page=page,
        page_size=page_size,
    )


def _oracle(all_candidates, visible_ids, page, page_size):
    visible = [c for c in all_candidates if c.id in visible_ids]
    expected = visible[(page - 1) * page_size : page * page_size]
    has_more = len(visible) > page * page_size
    return expected, has_more


async def test_scan_page_equals_fetch_all_filter_slice():
    svc = KnowledgeSpaceService(request=None, login_user=_User())
    cands = _candidates(40)
    visible_ids = {c.id for c in cands if c.id % 2 == 0}  # half visible

    counter, patchers = _install(cands, visible_ids, batch_size=4)
    import contextlib

    with contextlib.ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        page_slice, has_more = await _scan(svc, page=1, page_size=3)

    exp, exp_more = _oracle(cands, visible_ids, 1, 3)
    assert [c.id for c in page_slice] == [c.id for c in exp]
    assert has_more is exp_more


async def test_scan_walks_all_pages_no_dup_no_gap():
    svc = KnowledgeSpaceService(request=None, login_user=_User())
    cands = _candidates(50)
    visible_ids = {c.id for c in cands if c.id % 3 != 0}

    walked = []
    page = 1
    import contextlib

    while True:
        counter, patchers = _install(cands, visible_ids, batch_size=7)
        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            page_slice, has_more = await _scan(svc, page=page, page_size=4)
        walked.extend(c.id for c in page_slice)
        if not has_more:
            break
        page += 1
        assert page < 100

    all_visible = [c.id for c in cands if c.id in visible_ids]
    assert walked == all_visible
    assert len(walked) == len(set(walked))


async def test_scan_stops_early_does_not_exhaust_candidates():
    """Page 1 of a list where every candidate is visible must NOT scan the whole
    candidate set — it stops once page_size+1 visible are collected."""
    svc = KnowledgeSpaceService(request=None, login_user=_User())
    cands = _candidates(1000)
    visible_ids = {c.id for c in cands}  # everything visible

    counter, patchers = _install(cands, visible_ids, batch_size=10)
    import contextlib

    with contextlib.ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        page_slice, has_more = await _scan(svc, page=1, page_size=5)

    assert [c.id for c in page_slice] == [0, 1, 2, 3, 4]
    assert has_more is True
    # page_size=5 + probe -> need 6 visible; batch=10 -> a single batch suffices.
    assert counter["dao_calls"] == 1
    assert counter["max_offset_end"] <= 10, "must not fetch beyond the first batch"


async def test_scan_last_page_has_more_false():
    svc = KnowledgeSpaceService(request=None, login_user=_User())
    cands = _candidates(10)
    visible_ids = {c.id for c in cands}  # 10 visible

    counter, patchers = _install(cands, visible_ids, batch_size=4)
    import contextlib

    with contextlib.ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        # page 2 of size 5 -> items 5..9, exactly the tail, no next page.
        page_slice, has_more = await _scan(svc, page=2, page_size=5)

    assert [c.id for c in page_slice] == [5, 6, 7, 8, 9]
    assert has_more is False


async def test_scan_sparse_visibility_refills_across_batches():
    """Only the last few candidates are visible -> the scan must traverse many
    filtered-empty batches and still return them correctly."""
    svc = KnowledgeSpaceService(request=None, login_user=_User())
    cands = _candidates(30)
    visible_ids = {c.id for c in cands[-4:]}  # ids 26,27,28,29

    counter, patchers = _install(cands, visible_ids, batch_size=5)
    import contextlib

    with contextlib.ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        page_slice, has_more = await _scan(svc, page=1, page_size=3)

    assert [c.id for c in page_slice] == [26, 27, 28]
    assert has_more is True
