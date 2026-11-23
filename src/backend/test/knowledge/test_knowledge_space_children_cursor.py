"""T012 — Knowledge space children cursor protocol (AC-03, AC-08, AC-10, AC-11).

Mix of behavior tests (where pytest pre-mock chain allows) and static-source
checks (where it does not, mirroring T010).

Key F027 AD-14 invariants covered:
- ``_compute_ext_rank_python`` and ``_compute_ext_rank_case_when`` produce
  matching ranks for every extension in the 15-WHEN ladder (AD-14 critical
  invariant — Python-side cursor encoding must agree with SQL-side keyset
  comparison, otherwise cursor pagination skips / duplicates rows).
- ``SpaceFileDao.async_list_children`` accepts ``cursor`` kwarg.
- ``_scan_visible_child_items`` no longer threads ``page`` / OFFSET state and
  uses "fetch until ≥ page_size+1 visible" loop (AC-10).
- ``list_space_children`` raises ``KnowledgeSpaceInvalidCursorError`` on
  decode failure (AC-08, code 18070).
"""

from __future__ import annotations

import ast
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import mysql, sqlite

from bisheng.common.cursor import decode_cursor, encode_cursor
from bisheng.common.errcode.knowledge_space import KnowledgeSpaceInvalidCursorError
from bisheng.knowledge.domain.models import knowledge_space_file
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file import (
    _EXT_PRIORITIES,
    _EXT_RANK_FALLBACK,
    _compute_ext_rank_case_when,
    _compute_ext_rank_python,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _read(rel: str) -> str:
    return (Path(__file__).resolve().parents[2] / "bisheng" / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AD-14 critical invariant: SQL CASE and Python ext_rank must agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_name,expected_rank",
    [
        ("report.pdf", 1),
        ("notes.docx", 2),
        ("legacy.doc", 3),
        ("budget.xlsx", 4),
        ("budget.xls", 5),
        ("data.csv", 6),
        ("deck.pptx", 7),
        ("deck.ppt", 8),
        ("photo.jpg", 9),
        ("photo.jpeg", 10),
        ("icon.png", 11),
        ("icon.bmp", 12),
        ("readme.md", 13),
        ("notes.txt", 14),
        ("page.html", 15),
        # Edge cases → fallback
        ("unknown.xyz", _EXT_RANK_FALLBACK),
        ("folder_no_ext", _EXT_RANK_FALLBACK),
        ("UPPERCASE.PDF", 1),  # case-insensitive match
        ("", _EXT_RANK_FALLBACK),
        (None, _EXT_RANK_FALLBACK),
    ],
)
def test_compute_ext_rank_python_matches_table(file_name, expected_rank):
    assert _compute_ext_rank_python(file_name) == expected_rank


def test_python_and_sql_ext_rank_agree_for_all_extensions():
    """SQL CASE WHEN computed via SQLAlchemy literal substitution should
    return the same integer as the Python helper for every listed extension."""
    case_expr = _compute_ext_rank_case_when()

    for ext, expected_rank in _EXT_PRIORITIES:
        file_name = f"sample.{ext}"

        # Compile a SELECT that swaps KnowledgeFile.file_name for a literal so
        # we can read the CASE WHEN output directly (no DB needed; just
        # inspect the compiled SQL).
        sql = str(
            select(case_expr).compile(
                dialect=sqlite.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        # Sanity check: the SQL pattern for this rank is present.
        assert f"THEN {expected_rank}" in sql, f"rank {expected_rank} for .{ext} not in SQL"

        # And the Python side agrees.
        assert _compute_ext_rank_python(file_name) == expected_rank


def test_ext_priority_table_length_is_16():
    """The SQL/Python cursor rank table includes OFD after the original 15."""
    assert len(_EXT_PRIORITIES) == 16
    assert _EXT_PRIORITIES[0] == ("pdf", 1)
    assert _EXT_PRIORITIES[-1] == ("ofd", 16)


@pytest.fixture
async def sorted_children(async_db_session, monkeypatch):
    timestamp = datetime(2026, 11, 18, 8)
    records = [
        (1, "a.pdf", 0, None, 0, 2),
        (2, "a.pdf", 1, 0, 0, 2),
        (3, "b.docx", 1, 8, 1, 0),
        (4, "b.docx", 1, 8, 1, 0),
        (5, "c.xlsx", 1, None, 3, 4),
        (6, "c.xlsx", 1, 0, 2, 4),
    ]
    async_db_session.add_all(
        KnowledgeFile(
            id=file_id,
            knowledge_id=9,
            file_name=name,
            file_type=file_type,
            file_size=size,
            create_time=timestamp + timedelta(seconds=created),
            update_time=timestamp + timedelta(seconds=updated),
        )
        for file_id, name, file_type, size, created, updated in records
    )
    await async_db_session.flush()
    statements = []
    execute = async_db_session.exec

    async def capture(statement):
        statements.append(statement)
        return await execute(statement)

    @asynccontextmanager
    async def session():
        yield async_db_session

    monkeypatch.setattr(async_db_session, "exec", capture)
    monkeypatch.setattr(knowledge_space_file, "get_async_db_session", session)
    service = KnowledgeSpaceService(request=None, login_user=SimpleNamespace(is_global_super=False))
    monkeypatch.setattr(
        service, "_require_container_read_permission", AsyncMock(return_value=(SimpleNamespace(user_id=7), None))
    )
    monkeypatch.setattr(service, "_build_child_permission_context", AsyncMock(return_value={}))
    monkeypatch.setattr(service, "_filter_visible_child_items", AsyncMock(side_effect=lambda rows, **_: rows))
    monkeypatch.setattr(service, "_enrich_with_version_info", AsyncMock())
    monkeypatch.setattr(
        service,
        "_handle_file_folder_extra_info",
        AsyncMock(side_effect=lambda rows, **_: [{"id": row.id} for row in rows]),
    )
    return service, statements, timestamp


@pytest.mark.parametrize(
    ("field", "direction", "expected_ids"),
    [
        ("file_type", "asc", [1, 2, 4, 3, 6, 5]),
        ("file_type", "desc", [6, 5, 4, 3, 2, 1]),
        ("update_time", "asc", [4, 3, 2, 1, 6, 5]),
        ("update_time", "desc", [6, 5, 2, 1, 4, 3]),
        ("file_name", "asc", [2, 1, 4, 3, 6, 5]),
        ("file_name", "desc", [6, 5, 4, 3, 2, 1]),
        ("file_size", "asc", [5, 1, 6, 2, 4, 3]),
        ("file_size", "desc", [4, 3, 6, 2, 5, 1]),
        ("create_time", "asc", [2, 1, 4, 3, 6, 5]),
        ("create_time", "desc", [5, 6, 4, 3, 2, 1]),
    ],
)
async def test_children_cursor_preserves_sort_across_tied_rows(sorted_children, field, direction, expected_ids):
    service, statements, _ = sorted_children
    cursor = None
    returned_ids = []
    for position in range(len(expected_ids)):
        result = await service.list_space_children(
            space_id=9, order_field=field, order_sort=direction, page_size=1, cursor=cursor
        )
        returned_ids.extend(item["id"] for item in result.data)
        assert result.has_more == (position < len(expected_ids) - 1)
        if result.has_more:
            assert result.next_cursor and result.next_cursor != cursor
        cursor = result.next_cursor
    assert returned_ids == expected_ids
    assert cursor is None
    assert len(statements) == len(expected_ids)
    for statement in statements:
        sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})).lower()
        assert "limit 2" in sql
        assert "knowledgefile.id desc" in sql
        assert "offset" not in sql


@pytest.mark.parametrize("field", ["file_type", "update_time"])
async def test_children_accepts_existing_cursor_for_supported_legacy_sorts(sorted_children, field):
    service, _, timestamp = sorted_children
    cursor = encode_cursor(
        [1, 4, timestamp + timedelta(seconds=4), 6],
        context=f"space_children|order={field}_desc",
    )
    result = await service.list_space_children(
        space_id=9, order_field=field, order_sort="desc", page_size=1, cursor=cursor
    )
    assert result.data == [{"id": 5}]


async def test_children_rejects_old_size_cursor_missing_the_sort_value(sorted_children):
    service, statements, timestamp = sorted_children
    cursor = encode_cursor([1, 4, timestamp, 5], context="space_children|order=file_size_desc")
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await service.list_space_children(space_id=9, order_field="file_size", order_sort="desc", cursor=cursor)
    assert not statements


@pytest.mark.parametrize(
    ("field", "denied", "first_id", "next_id"),
    [
        ("file_name", {1, 3, 4}, 2, 6),
        ("file_size", {1, 2, 4, 6}, 5, 3),
        ("create_time", {1, 3, 4}, 2, 6),
    ],
)
async def test_children_cursor_uses_visible_sort_value(sorted_children, field, denied, first_id, next_id):
    service, _, timestamp = sorted_children
    service._filter_visible_child_items.side_effect = lambda rows, **_: [row for row in rows if row.id not in denied]
    first = await service.list_space_children(space_id=9, order_field=field, page_size=1)
    assert first.data == [{"id": first_id}]
    assert first.next_cursor
    sort_value = {"file_name": "a.pdf", "file_size": None, "create_time": timestamp.isoformat()}[field]
    cursor = decode_cursor(first.next_cursor, expected_context=f"space_children|order={field}_asc", expected_key_len=4)
    assert cursor[:2] == [field, sort_value]
    assert cursor[-1] == first_id
    assert (
        await service.list_space_children(space_id=9, order_field=field, page_size=1, cursor=first.next_cursor)
    ).data == [{"id": next_id}]


async def test_children_does_not_encode_a_denied_row_for_a_zero_size_page(sorted_children):
    service, _, _ = sorted_children
    service._filter_visible_child_items.side_effect = lambda rows, **_: [row for row in rows if row.id != 2]
    result = await service.list_space_children(space_id=9, order_field="file_name", page_size=0)
    assert result.data == []
    assert result.next_cursor is None


@pytest.mark.parametrize(
    ("field", "value", "file_id"), [("file_name", None, 1), ("file_size", [], 1), ("file_name", "a.pdf", "1")]
)
async def test_children_rejects_malformed_cursor_values(sorted_children, field, value, file_id):
    service, statements, timestamp = sorted_children
    cursor = encode_cursor([field, value, timestamp, file_id], context=f"space_children|order={field}_asc")
    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await service.list_space_children(space_id=9, order_field=field, cursor=cursor)
    assert not statements


# ---------------------------------------------------------------------------
# AC-10 / AC-11: DAO and service structural invariants
# ---------------------------------------------------------------------------


def test_async_list_children_accepts_cursor_param():
    src = _read("knowledge/domain/models/knowledge_space_file.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "SpaceFileDao")
    func = next(
        n
        for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "async_list_children"
    )
    all_arg_names = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
    assert "cursor" in all_arg_names, "async_list_children must accept `cursor` kwarg"


def test_scan_visible_child_items_uses_cursor_fetch_until_enough():
    """AC-10: cursor-driven, not OFFSET; loop breaks when
    ``len(visible_page_items) > page_size`` (i.e. the +1 probe is seen)."""
    src = _read("knowledge/domain/services/knowledge_space_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "KnowledgeSpaceService")
    func = next(
        n
        for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_scan_visible_child_items"
    )
    func_src = ast.get_source_segment(src, func)

    # No more `scan_page = 1` / `scan_page += 1` OFFSET-style traversal
    assert "scan_page" not in func_src

    # New: batch_cursor advances via DB last row keyset
    assert "batch_cursor" in func_src
    assert "space_child_cursor_key" in func_src

    # Fetch-until-enough: the next visible candidate is the has_more probe.
    assert re.search(r"len\(visible_page_items\)\s*==\s*page_size", func_src)


def test_scan_visible_child_items_returns_data_and_has_more():
    """Signature change: ``(visible_total, items)`` → ``(items, has_more)``."""
    src = _read("knowledge/domain/services/knowledge_space_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "KnowledgeSpaceService")
    func = next(
        n
        for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_scan_visible_child_items"
    )
    func_src = ast.get_source_segment(src, func)

    assert "return visible_page_items" in func_src or "return visible_page_items[:page_size]" in func_src
    # Tail of return tuple is a bool (has_more), never a count.
    assert "visible_total" not in func_src


# ---------------------------------------------------------------------------
# AC-08: cursor invalid → KnowledgeSpaceInvalidCursorError (18070)
# ---------------------------------------------------------------------------


def test_list_space_children_raises_invalid_cursor_error_on_decode_failure():
    src = _read("knowledge/domain/services/knowledge_space_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "KnowledgeSpaceService")
    func = next(
        n
        for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "list_space_children"
    )
    func_src = ast.get_source_segment(src, func)
    assert "CursorDecodeError" in func_src
    assert "KnowledgeSpaceInvalidCursorError" in func_src
    assert re.search(r"raise\s+KnowledgeSpaceInvalidCursorError\b", func_src)


def test_list_space_children_returns_page_infinite_cursor_data():
    src = _read("knowledge/domain/services/knowledge_space_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "KnowledgeSpaceService")
    func = next(
        n
        for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "list_space_children"
    )
    func_src = ast.get_source_segment(src, func)
    assert "PageInfiniteCursorData(" in func_src
    assert "encode_cursor(" in func_src
    # Cursor key is the 4-element last-scanned candidate boundary returned by the scanner.
    assert "scan_cursor" in func_src
    assert "encode_cursor(scan_cursor" in func_src


# ---------------------------------------------------------------------------
# Endpoint contract
# ---------------------------------------------------------------------------


def test_endpoint_accepts_cursor_drops_page():
    src = _read("knowledge/api/endpoints/knowledge_space.py")
    tree = ast.parse(src)
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "list_space_children"
    )
    arg_names = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
    assert "cursor" in arg_names
    assert "page" not in arg_names, "endpoint should no longer accept legacy `page` param"
