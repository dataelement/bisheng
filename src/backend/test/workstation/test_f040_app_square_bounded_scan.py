"""F040 F-group static guards for the two legacy app-square endpoints."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _function_source(relative_path: str, function_name: str) -> str:
    source = (BACKEND / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name
    )
    return ast.get_source_segment(source, function)


def test_chat_online_default_path_delegates_to_cursor_service():
    source = _function_source("bisheng/api/v1/chat.py", "get_online_chat")
    # Default ranked path is now an F027 cursor waterfall, not an offset scan.
    assert "get_online_flows_cursor" in source
    assert "get_all_flows_envelope" in source
    assert "cursor=cursor" in source
    assert "MessageSessionDao" not in source
    assert "skip_pagination=True" not in source
    assert "data.sort" not in source
    # The offset page helper must be gone from the default path.
    assert "get_online_flows_page" not in source


def test_uncategorized_path_is_cursor_waterfall_without_sync_fetch_all():
    source = _function_source("bisheng/api/services/workflow.py", "get_uncategorized_flows_envelope")
    assert "TagDao.asearch_tags" in source
    assert "TagDao.aget_resources_by_tags" in source
    assert "FlowDao.get_all_apps" not in source
    assert "return [], 0" not in source
    # Cursor scan, not the retired offset page scan.
    assert "_scan_visible_apps_cursor" in source
    assert "decode_cursor" in source
    assert "encode_cursor" in source
    assert "PageInfiniteCursorData" in source


def test_cursor_scan_uses_keyset_batches_and_page_size_bounded_probe():
    source = _function_source("bisheng/api/services/workflow.py", "_scan_visible_apps_cursor")
    # page_size + 1 probe instead of the old offset target_visible.
    assert "while len(visible) <= normalized_page_size" in source
    assert "cursor=batch_cursor" in source
    assert "has_more = len(visible) > normalized_page_size" in source
    assert "requested_actions" in source
    assert "_application_action_map" in source
    assert '"edit"' in source
    assert '"share"' in source


def test_ranked_dao_uses_dm8_safe_keyset_helper_with_mixed_directions():
    source = _function_source("bisheng/database/models/flow.py", "aget_all_apps")
    assert "ranking_user_id" in source
    assert "build_keyset_where" in source
    assert "descending=(False, True, True)" in source
    assert "count_statement" not in source
