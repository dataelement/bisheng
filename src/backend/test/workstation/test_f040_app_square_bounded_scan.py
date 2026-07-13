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


def test_chat_online_default_path_delegates_to_bounded_service_page():
    source = _function_source("bisheng/api/v1/chat.py", "get_online_chat")
    assert "get_online_flows_page" in source
    assert "MessageSessionDao" not in source
    assert "skip_pagination=True" not in source
    assert "data.sort" not in source


def test_uncategorized_path_has_no_sync_fetch_all_or_empty_link_short_circuit():
    source = _function_source("bisheng/api/services/workflow.py", "get_uncategorized_flows")
    assert "TagDao.asearch_tags" in source
    assert "TagDao.aget_resources_by_tags" in source
    assert "FlowDao.get_all_apps" not in source
    assert "return [], 0" not in source
    assert "_scan_visible_apps_page" in source


def test_compat_scan_uses_keyset_batches_and_page_bounded_target():
    source = _function_source("bisheng/api/services/workflow.py", "_scan_visible_apps_page")
    assert "while len(visible) < target_visible" in source
    assert "cursor=batch_cursor" in source
    assert "target_visible = normalized_page * normalized_page_size" in source
    assert "build_app_permission_context_async" in source
    assert "context=permission_context" in source


def test_ranked_dao_uses_dm8_safe_keyset_helper_with_mixed_directions():
    source = _function_source("bisheng/database/models/flow.py", "aget_all_apps")
    assert "ranking_user_id" in source
    assert "build_keyset_where" in source
    assert "descending=(False, True, True)" in source
    assert "count_statement" not in source
