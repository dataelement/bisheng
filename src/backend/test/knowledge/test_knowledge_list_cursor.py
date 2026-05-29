"""T008 — Knowledge list cursor protocol (AC-01, AC-04..06, AC-08, AC-11).

Covers:
- AC-01 response shape: `{data, page_size, has_more, next_cursor}`, no `total`
- AC-04 first page (no cursor)
- AC-05 keyset continuation (sort_by ∈ {update_time, create_time})
- AC-06 last page: has_more=False, next_cursor=None
- AC-08 invalid cursor → KnowledgeInvalidCursorError (10991)
- AC-11 acount_user_knowledge no longer called
- AD-15 sort_by=name fallback: pseudo-cursor (page_num offset), same response shape
- type=0 (document KB) and type=1 (QA KB) both follow cursor protocol
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum


def _load_service():
    from bisheng.knowledge.domain.services import knowledge_service as mod

    return mod


def _make_login_user(user_id=7, accessible=("1", "2", "3")):
    return SimpleNamespace(
        user_id=user_id,
        is_admin=lambda: False,
        rebac_list_accessible=AsyncMock(return_value=list(accessible)),
    )


def _make_knowledge_row(id_: int, name: str = "kb", update_time=None, create_time=None):
    """Minimal SQLModel-like row for cursor tests; only needs the attrs the
    service touches when building next_cursor."""
    return SimpleNamespace(
        id=id_,
        name=name,
        update_time=update_time or f"2026-05-29T12:34:5{id_:02d}",
        create_time=create_time or f"2026-05-28T08:00:0{id_:02d}",
        user_id=999,
        type=KnowledgeTypeEnum.NORMAL.value,
    )


# ---------------------------------------------------------------------------
# AC-01 / AC-04: first page returns the cursor envelope, no `total`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_page_returns_cursor_envelope_no_total():
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()

    # 21 rows ≥ page_size+1 → has_more=True
    rows = [_make_knowledge_row(i) for i in range(1, 22)]

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={1: {"view_kb"}, 2: {"view_kb"}, 3: {"view_kb"}}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        result = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=None,
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )

    assert result.page_size == 20
    assert result.has_more is True
    assert result.next_cursor is not None
    assert len(result.data) == 20  # 21 fetched, truncated to 20
    assert not hasattr(result, "total")


@pytest.mark.asyncio
async def test_last_page_returns_has_more_false_and_null_cursor():
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()

    # Only 5 rows < page_size+1 → has_more=False, next_cursor=None
    rows = [_make_knowledge_row(i) for i in range(1, 6)]

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={i: {"view_kb"} for i in [1, 2, 3]}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        result = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=None,
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )

    assert result.has_more is False
    assert result.next_cursor is None
    assert len(result.data) == 5


# ---------------------------------------------------------------------------
# AC-05: cursor continuation decodes correctly and the next_cursor matches the
# last visible item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_cursor_encodes_last_visible_sort_key_and_id():
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()

    rows = [_make_knowledge_row(i) for i in range(10, 32)]  # 22 rows

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={i: {"view_kb"} for i in [1, 2, 3]}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        result = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=None,
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )

    # next_cursor should decode to (last_visible.update_time, last_visible.id)
    decoded = decode_cursor(
        result.next_cursor,
        expected_key_len=2,
        expected_context="knowledge|sort_by=update_time",
    )
    last_visible = result.data[-1]
    assert decoded == [last_visible.update_time, last_visible.id]


# ---------------------------------------------------------------------------
# AC-08: invalid cursor raises KnowledgeInvalidCursorError (10991)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_garbage_cursor_raises_invalid_cursor_error():
    mod = _load_service()
    from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError

    login_user = _make_login_user()

    # No DB mocks needed: service should fail on cursor decode before hitting DAO.
    with pytest.raises(KnowledgeInvalidCursorError):
        await mod.KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor="not!valid!base64!@#$",
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )


@pytest.mark.asyncio
async def test_cursor_context_mismatch_raises_invalid_cursor_error():
    """Defend against frontend reusing a cursor across a sort_by change (AD-02)."""
    mod = _load_service()
    from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError

    cursor_for_update_time = encode_cursor(
        ("2026-05-29T12:34:56", 42),
        context="knowledge|sort_by=update_time",
    )
    login_user = _make_login_user()

    with pytest.raises(KnowledgeInvalidCursorError):
        await mod.KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=cursor_for_update_time,
            page_size=20,
            sort_by="create_time",  # different sort_by → context mismatch
            permission_id="view_kb",
        )


# ---------------------------------------------------------------------------
# AC-11: acount_user_knowledge / acount_all_knowledge are not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acount_user_knowledge_not_called():
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()
    rows = [_make_knowledge_row(i) for i in range(1, 6)]

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={i: {"view_kb"} for i in [1, 2, 3]}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(mod.KnowledgeDao, "acount_user_knowledge", new_callable=AsyncMock, return_value=0) as count_mock, \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=None,
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )

    count_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# AD-15: sort_by=name uses internal offset (pseudo-cursor), still no total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sort_by_name_uses_pseudo_cursor_encoding_page_num():
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()
    rows = [_make_knowledge_row(i) for i in range(1, 22)]  # 21 rows → has_more

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={i: {"view_kb"} for i in [1, 2, 3]}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        result = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=KnowledgeTypeEnum.NORMAL,
            cursor=None,
            page_size=20,
            sort_by="name",
            permission_id="view_kb",
        )

    assert result.has_more is True
    assert result.next_cursor is not None
    # Pseudo-cursor for name sort: k = [page_num]
    decoded = decode_cursor(
        result.next_cursor,
        expected_key_len=1,
        expected_context="knowledge|sort_by=name",
    )
    assert decoded == [2]  # first page → next page is 2


# ---------------------------------------------------------------------------
# AC-01: type=0 and type=1 both follow cursor protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("ktype", [KnowledgeTypeEnum.NORMAL, KnowledgeTypeEnum.QA])
async def test_both_kb_types_follow_cursor_protocol(ktype):
    mod = _load_service()
    KnowledgeService = mod.KnowledgeService
    login_user = _make_login_user()
    rows = [_make_knowledge_row(i) for i in range(1, 6)]

    with patch.object(mod.KnowledgeDao, "aget_knowledge_ids_created_by", new_callable=AsyncMock, return_value=[]), \
         patch.object(KnowledgeService.permission_service, "get_knowledge_permission_map_async", new_callable=AsyncMock, return_value={i: {"view_kb"} for i in [1, 2, 3]}), \
         patch.object(mod.KnowledgeDao, "aget_user_knowledge", new_callable=AsyncMock, return_value=rows), \
         patch.object(KnowledgeService, "aconvert_knowledge_read", new_callable=AsyncMock, side_effect=lambda u, r, **kw: r):
        result = await KnowledgeService.get_knowledge(
            request=MagicMock(),
            login_user=login_user,
            knowledge_type=ktype,
            cursor=None,
            page_size=20,
            sort_by="update_time",
            permission_id="view_kb",
        )

    assert hasattr(result, "page_size")
    assert hasattr(result, "has_more")
    assert hasattr(result, "next_cursor")
    assert not hasattr(result, "total")
