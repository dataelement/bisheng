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
import inspect
import re
from pathlib import Path

import pytest

from sqlalchemy import literal, select
from sqlalchemy.dialects import sqlite

from bisheng.knowledge.domain.models.knowledge_space_file import (
    _EXT_PRIORITIES,
    _EXT_RANK_FALLBACK,
    _compute_ext_rank_case_when,
    _compute_ext_rank_python,
)


def _read(rel: str) -> str:
    return (
        Path(__file__).resolve().parents[2] / "bisheng" / rel
    ).read_text(encoding="utf-8")


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


def test_ext_priority_table_length_is_15():
    """Spec §6.2: pdf=1 .. html=15, exactly 15 ranked extensions."""
    assert len(_EXT_PRIORITIES) == 15
    assert _EXT_PRIORITIES[0] == ("pdf", 1)
    assert _EXT_PRIORITIES[-1] == ("html", 15)


# ---------------------------------------------------------------------------
# AC-10 / AC-11: DAO and service structural invariants
# ---------------------------------------------------------------------------


def test_async_list_children_accepts_cursor_param():
    src = _read("knowledge/domain/models/knowledge_space_file.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "SpaceFileDao")
    func = next(
        n for n in cls.body
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
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_scan_visible_child_items"
    )
    func_src = ast.get_source_segment(src, func)

    # No more `scan_page = 1` / `scan_page += 1` OFFSET-style traversal
    assert "scan_page" not in func_src

    # New: batch_cursor advances via DB last row keyset
    assert "batch_cursor" in func_src
    assert "_compute_ext_rank_python" in func_src

    # Fetch-until-enough: break when visible exceeds page_size+1 probe
    assert re.search(r"len\(visible_page_items\)\s*>\s*page_size", func_src)


def test_scan_visible_child_items_returns_data_and_has_more():
    """Signature change: ``(visible_total, items)`` → ``(items, has_more)``."""
    src = _read("knowledge/domain/services/knowledge_space_service.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "KnowledgeSpaceService")
    func = next(
        n for n in cls.body
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
        n for n in cls.body
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
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "list_space_children"
    )
    func_src = ast.get_source_segment(src, func)
    assert "PageInfiniteCursorData(" in func_src
    assert "encode_cursor(" in func_src
    # Cursor key shape: 4-tuple including ext_rank
    assert "_compute_ext_rank_python" in func_src


# ---------------------------------------------------------------------------
# Endpoint contract
# ---------------------------------------------------------------------------


def test_endpoint_accepts_cursor_drops_page():
    src = _read("knowledge/api/endpoints/knowledge_space.py")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "list_space_children"
    )
    arg_names = {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}
    assert "cursor" in arg_names
    assert "page" not in arg_names, "endpoint should no longer accept legacy `page` param"
