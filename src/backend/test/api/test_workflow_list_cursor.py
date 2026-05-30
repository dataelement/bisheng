"""T010 — Workflow/app list cursor protocol static checks (AC-02, AC-08, AC-11).

Behavior-level cursor protocol semantics (decode → query → encode) are already
exercised in T004 (cursor codec) and T008 (knowledge list — same pattern).
This file focuses on the *workflow-specific* invariants that AC-02/08/11 demand:

- ``FlowDao.aget_all_apps`` no longer contains ``count_statement`` or
  ``func.count(sub_query.c.id)`` (AC-11 static grep).
- ``FlowDao.aget_all_apps`` accepts a ``cursor`` keyword and returns
  ``(data, has_more)`` (signature/contract).
- ``WorkFlowService.get_all_flows_envelope`` exists, uses
  ``"flow|sort=update_time"`` as the cursor context (AC-02), and routes
  cursor-decode failures through ``AppInvalidCursorError`` (AC-08).
- ``PageInfiniteCursorData`` is the wrapped return shape.

The pytest pre-mock chain (``test/conftest.py``) breaks
``class WorkFlowService(BaseService)`` instantiation because
``bisheng.common.services.base`` is replaced with a ``MagicMock`` at collect
time. We therefore validate via the source code of the file rather than
importing the live class.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path


def _read(rel: str) -> str:
    return (
        Path(__file__).resolve().parents[2] / "bisheng" / rel
    ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-11: count_statement removed from FlowDao.aget_all_apps
# ---------------------------------------------------------------------------


def test_flowdao_aget_all_apps_no_count_statement():
    src = _read("database/models/flow.py")
    # Extract the aget_all_apps function source via AST so an unrelated
    # `count_statement` token elsewhere in the file doesn't cause a false fail.
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "aget_all_apps"
    )
    func_src = ast.get_source_segment(src, func)
    assert "count_statement" not in func_src
    assert "func.count(sub_query.c.id)" not in func_src


def test_flowdao_aget_all_apps_takes_cursor_returns_has_more():
    src = _read("database/models/flow.py")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "aget_all_apps"
    )
    # Args include `cursor`
    kwonly = {a.arg for a in func.args.kwonlyargs}
    pos = {a.arg for a in func.args.args}
    assert "cursor" in (kwonly | pos), "aget_all_apps must accept `cursor` parameter"

    # Return tuple ends in has_more (bool), not total (int)
    func_src = ast.get_source_segment(src, func)
    assert "return data, has_more" in func_src
    assert "return data, total" not in func_src


# ---------------------------------------------------------------------------
# AC-02 / AC-08: get_all_flows_envelope contract
# ---------------------------------------------------------------------------


def test_get_all_flows_envelope_exists_and_uses_flow_sort_update_time_context():
    src = _read("api/services/workflow.py")
    assert "async def get_all_flows_envelope" in src
    assert '"flow|sort=update_time"' in src or "'flow|sort=update_time'" in src


def test_get_all_flows_envelope_raises_app_invalid_cursor_error_on_decode_failure():
    src = _read("api/services/workflow.py")
    tree = ast.parse(src)

    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "WorkFlowService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "get_all_flows_envelope"
    )
    func_src = ast.get_source_segment(src, func)
    # Translate CursorDecodeError → AppInvalidCursorError per AC-08
    assert "CursorDecodeError" in func_src
    assert "AppInvalidCursorError" in func_src
    assert re.search(r"raise\s+AppInvalidCursorError\b", func_src)


def test_get_all_flows_envelope_returns_page_infinite_cursor_data():
    src = _read("api/services/workflow.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "WorkFlowService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "get_all_flows_envelope"
    )
    func_src = ast.get_source_segment(src, func)
    # next_cursor encodes (update_time, id) tuple
    assert "encode_cursor(" in func_src
    assert "update_time" in func_src
    # Wraps in PageInfiniteCursorData
    assert "PageInfiniteCursorData(" in func_src


# ---------------------------------------------------------------------------
# AC-11 additional: get_all_flows internal also abandoned `total`
# ---------------------------------------------------------------------------


def test_get_all_flows_returns_has_more_not_total():
    src = _read("api/services/workflow.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "WorkFlowService")
    func = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "get_all_flows"
    )
    func_src = ast.get_source_segment(src, func)
    assert "return data, has_more" in func_src
    assert "return data, total" not in func_src


# ---------------------------------------------------------------------------
# Endpoint contract: cursor query param + cursor envelope wrapper call
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fetch-until-enough scan loop: thin-page fix for fine-grained ReBAC filtering
# ---------------------------------------------------------------------------


def test_envelope_uses_fetch_until_enough_scan_loop():
    """F027 update: when fine-grained permission filtering shrinks a DB batch,
    the envelope must loop and refill from the next keyset window instead of
    returning a thin page. Mirrors the ``_scan_visible_child_items`` pattern
    used by knowledge-space children.
    """
    src = _read("api/services/workflow.py")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "WorkFlowService")

    scan = next(
        (n for n in cls.body
         if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_scan_visible_flows_cursor"),
        None,
    )
    assert scan is not None, "_scan_visible_flows_cursor helper must exist"
    # Core of fetch-until-enough is a while loop that refetches batches.
    assert any(isinstance(node, ast.While) for node in ast.walk(scan)), (
        "_scan_visible_flows_cursor must contain a while loop"
    )

    envelope = next(
        n for n in cls.body
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "get_all_flows_envelope"
    )
    envelope_src = ast.get_source_segment(src, envelope)
    assert "_scan_visible_flows_cursor" in envelope_src, (
        "envelope must delegate fetching to the scan loop"
    )


def test_workflow_list_endpoint_accepts_cursor_param():
    src = _read("api/v1/workflow.py")
    tree = ast.parse(src)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "read_flows"
    )
    func_src = ast.get_source_segment(src, func)
    # Endpoint declares a cursor query parameter
    assert "cursor" in {a.arg for a in func.args.kwonlyargs} | {a.arg for a in func.args.args}
    # Endpoint calls the envelope wrapper
    assert "get_all_flows_envelope" in func_src
