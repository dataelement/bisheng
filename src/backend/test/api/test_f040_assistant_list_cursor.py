"""Assistant F048 action filtering over the F040 keyset cursor scan.

Equivalence is the safety red line: the cursor scan must surface the SAME visible
assistants, in the SAME order, as the legacy offset path — across page boundaries,
with no duplicates and no gaps even when concrete-action filtering thins a batch.
These tests pin that by simulating the keyset DAO in-memory and the F048
``batch_check_business_actions`` facade, then walking every page via ``next_cursor``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.api.services.assistant import AssistantService

_AS = "bisheng.api.services.assistant"


class _User:
    user_id = 42

    def __init__(self, admin: bool = False):
        self._admin = admin

    def is_admin(self):
        return self._admin


def _make_rows(n: int):
    """Rows pre-sorted by (update_time DESC, id DESC) — the DAO's contract order."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    rows = []
    for i in range(n):
        rows.append(
            SimpleNamespace(
                id=f"a{i:03d}",
                update_time=base - timedelta(minutes=i),
                user_id=999,  # not the requester → write flag is driven by the concrete edit action
            )
        )
    # already descending by update_time (and id ties broken desc); keep as-is.
    return rows


def _fake_dao_factory(all_rows):
    """In-memory keyset simulation honouring cursor + limit+1 has_more probe."""

    async def _fake(name, status, assistant_ids, cursor, limit):
        rows = all_rows
        if assistant_ids is not None:
            allow = set(assistant_ids)
            rows = [r for r in rows if r.id in allow]
        start = 0
        if cursor:
            cu, ci = cursor
            start = len(rows)
            for idx, r in enumerate(rows):
                if (r.update_time, r.id) < (cu, ci):
                    start = idx
                    break
        window = rows[start : start + limit + 1]
        has_more = len(window) > limit
        return window[:limit], has_more

    return _fake


async def _collect_all_pages(user, *, allowed_ids, all_rows, page_size, action="use"):
    """Walk the scan helper page-by-page via the (update_time, id) cursor."""

    async def _fake_action_map(
        login_user,
        *,
        resource_type,
        resource_ids,
        actions,
    ):
        assert login_user is user
        assert resource_type == "assistant"
        requested_actions = set(actions)
        return {
            resource_id: frozenset(requested_actions & {"use", "edit"} if resource_id in allowed_ids else ())
            for resource_id in map(str, resource_ids)
        }

    collected = []
    cursor = None
    pages = 0
    with (
        patch(f"{_AS}.AssistantDao.aget_all_assistants_cursor", new=_fake_dao_factory(all_rows)),
        patch(
            f"{_AS}.batch_check_business_actions",
            new=AsyncMock(side_effect=_fake_action_map),
        ),
    ):
        while True:
            pages += 1
            assert pages < 1000, "pagination did not terminate"
            visible, has_more, _editable = await AssistantService._scan_visible_assistants_cursor(
                user=user,
                name=None,
                status=None,
                assistant_ids=None,
                cursor=cursor,
                page_size=page_size,
                action=action,
            )
            collected.extend(visible)
            if not has_more or not visible:
                break
            last = visible[-1]
            cursor = [last.update_time, last.id]
    return collected


async def test_scan_visible_equals_offset_filter_slice():
    """Cursor scan over all pages == legacy (fetch-all → filter → ordered) set."""
    all_rows = _make_rows(20)
    allowed = {r.id for i, r in enumerate(all_rows) if i % 3 != 0}  # sparse: ~2/3 visible

    legacy = [r for r in all_rows if r.id in allowed]  # order preserved by construction
    collected = await _collect_all_pages(
        _User(admin=False),
        allowed_ids=allowed,
        all_rows=all_rows,
        page_size=4,
    )

    assert [r.id for r in collected] == [r.id for r in legacy]
    # no duplicates across page boundaries
    assert len(collected) == len({r.id for r in collected})


async def test_scan_refills_across_thinned_batches():
    """A batch fully filtered out must not end pagination early — the scan keeps
    pulling keyset windows until page_size+1 visible or DB exhausted."""
    all_rows = _make_rows(30)
    # Only the LAST 5 rows are visible; everything before is filtered out. With a
    # small page_size the scan must traverse many empty-after-filter windows.
    allowed = {r.id for r in all_rows[-5:]}
    collected = await _collect_all_pages(
        _User(admin=False),
        allowed_ids=allowed,
        all_rows=all_rows,
        page_size=3,
    )
    assert {r.id for r in collected} == allowed


async def test_admin_still_uses_concrete_action_facade():
    """System identity policy stays behind the sole F048 authorization facade."""
    all_rows = _make_rows(6)

    async def _allow_all(
        login_user,
        *,
        resource_type,
        resource_ids,
        actions,
    ):
        assert login_user.is_admin()
        assert resource_type == "assistant"
        assert tuple(actions) == ("use", "edit")
        return {resource_id: frozenset({"use", "edit"}) for resource_id in map(str, resource_ids)}

    action_map = AsyncMock(side_effect=_allow_all)
    with (
        patch(f"{_AS}.AssistantDao.aget_all_assistants_cursor", new=_fake_dao_factory(all_rows)),
        patch(f"{_AS}.batch_check_business_actions", new=action_map),
    ):
        visible, has_more, editable = await AssistantService._scan_visible_assistants_cursor(
            user=_User(admin=True),
            name=None,
            status=None,
            assistant_ids=None,
            cursor=None,
            page_size=10,
            action="use",
        )
    assert [r.id for r in visible] == [r.id for r in all_rows]
    assert has_more is False
    assert editable == {r.id for r in all_rows}
    action_map.assert_awaited_once()


async def test_has_more_probe_is_exact_at_page_boundary():
    """Exactly page_size visible rows ⇒ has_more False (no phantom extra page)."""
    all_rows = _make_rows(8)

    async def _fake_action_map(
        login_user,
        *,
        resource_type,
        resource_ids,
        actions,
    ):
        assert resource_type == "assistant"
        assert tuple(actions) == ("use", "edit")
        return {resource_id: frozenset({"use"}) for resource_id in map(str, resource_ids)}

    with (
        patch(f"{_AS}.AssistantDao.aget_all_assistants_cursor", new=_fake_dao_factory(all_rows)),
        patch(
            f"{_AS}.batch_check_business_actions",
            new=AsyncMock(side_effect=_fake_action_map),
        ),
    ):
        visible, has_more, _ = await AssistantService._scan_visible_assistants_cursor(
            user=_User(admin=False),
            name=None,
            status=None,
            assistant_ids=None,
            cursor=None,
            page_size=8,
            action="use",
        )
    assert len(visible) == 8
    assert has_more is False


async def test_envelope_rejects_bad_cursor_with_app_invalid_cursor_error():
    from bisheng.common.errcode.flow import AppInvalidCursorError

    raised = False
    try:
        await AssistantService.aget_assistant_envelope(
            _User(admin=False),
            cursor="!!!not-a-valid-cursor!!!",
            page_size=10,
        )
    except AppInvalidCursorError:
        raised = True
    assert raised, "malformed cursor must surface AppInvalidCursorError, not a 500"


async def test_envelope_empty_tag_match_short_circuits():
    from bisheng.common.schemas.api import PageInfiniteCursorData

    with patch(f"{_AS}.TagDao.get_resources_by_tags", return_value=[]):
        result = await AssistantService.aget_assistant_envelope(
            _User(admin=False),
            tag_id=7,
            page_size=10,
        )
    assert isinstance(result, PageInfiniteCursorData)
    assert result.data == []
    assert result.has_more is False
    assert result.next_cursor is None
