"""F040 AC-31: static-scan guardrails locking in the read-path refactors.

These assert the anti-patterns stay removed — if a future change reintroduces a
fetch-all, a per-item permission loop, a mount-time permission fan-out, or routes
channel unread back through the detail path, the corresponding test fails. The
performance *baseline* (P95 / round-trip counts) needs seeded data + middleware
and runs in CI; this file is the cheap, always-runnable half of T10.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / "bisheng"
_CLIENT = Path(__file__).resolve().parents[3] / "frontend" / "client" / "src"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _func_src(src: str, name: str) -> str:
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)
    return ast.get_source_segment(src, node)


# ─────────────────────────── A — channel detail ───────────────────────────


def test_channel_detail_reuses_context_and_drops_unread():
    src = _read(_BACKEND / "channel" / "domain" / "services" / "channel_service.py")
    detail = _func_src(src, "get_channel_detail")
    # permission ids computed with a reused context (no context-less rebuild branch)
    assert "context=" in detail, "get_channel_detail must pass a reused permission context"
    # unread moved to its own endpoint — detail must not compute sub-channel unread
    assert "_calculate_sub_channel_unread_counts" not in detail
    # article total goes through the Redis count cache
    assert "ArticleCountCache" in src


def test_unread_counts_live_on_their_own_endpoint():
    src = _read(_BACKEND / "channel" / "api" / "endpoints" / "channel_manager.py")
    assert "/{channel_id}/unread-counts" in src


# ─────────────────────────── B — space plaza ──────────────────────────────


def test_format_accessible_spaces_shares_context_and_parallelizes():
    """T5 方案1 (D3): the per-space serial loop is replaced by a shared binding
    index + parallel evaluation. (The per-space get_permission_level -> single
    cross-space batch_check is 方案2, deferred — so it may still appear, but only
    inside asyncio.gather with a shared context, never a serial await-in-for.)"""
    src = _read(_BACKEND / "knowledge" / "domain" / "services" / "knowledge_space_service.py")
    fmt = _func_src(src, "_format_accessible_spaces")
    # Shared context built once, threaded into every per-space eval.
    assert "binding_index" in fmt and "shared=" in fmt, "T5: shared binding index must be threaded"
    # Per-space work is parallelized via gather, not a serial await-in-for loop.
    assert "asyncio.gather" in fmt


# ─────────────────────────── C — lists ────────────────────────────────────


def test_assistant_list_endpoint_uses_cursor_envelope():
    src = _read(_BACKEND / "api" / "v1" / "assistant.py")
    ep = _func_src(src, "get_assistant")
    assert "aget_assistant_envelope" in ep
    assert "cursor" in ep


def test_assistant_dao_has_keyset_cursor_no_offset_slice():
    src = _read(_BACKEND / "database" / "models" / "assistant.py")
    cur = _func_src(src, "aget_all_assistants_cursor")
    assert "build_keyset_where" in cur
    assert "has_more" in cur


def test_search_space_children_batch_scans_no_python_slice():
    src = _read(_BACKEND / "knowledge" / "domain" / "services" / "knowledge_space_service.py")
    search = _func_src(src, "search_space_children")
    assert "_scan_visible_search_items" in search, "search must batch-scan, not fetch-all"
    assert "has_more" in search and '"total"' not in search, "search drops exact total -> has_more"
    # the old python-slice helper is fully removed
    assert "_paginate_items" not in src


def test_search_batch_scan_uses_id_tiebreaker():
    scan = _func_src(
        _read(_BACKEND / "knowledge" / "domain" / "services" / "knowledge_space_service.py"),
        "_scan_visible_search_items",
    )
    assert "id_tiebreaker=True" in scan, "OFFSET batch-scan needs a deterministic id-tie-broken order"


def test_used_apps_enriches_after_paginate():
    src = _read(_BACKEND / "workstation" / "api" / "endpoints" / "apps.py")
    used = _func_src(src, "get_used_apps")
    # tags fetched for the page's ids only (slice before enrich)
    assert "page_flow_ids" in used
    assert '{"list": result, "total": total}' in used or '"list": result' in used


# ─────────────────────────── D — client sidebar lazy ──────────────────────


def test_client_sidebar_permissions_are_lazy():
    p = _CLIENT / "pages" / "knowledge" / "hooks" / "useKnowledgeSpacePermissions.ts"
    if not p.exists():  # frontend tree may be absent in some CI shards
        return
    src = _read(p)
    assert "ensureSpacePermissions" in src, "lazy per-space resolver must exist"
    # No mount-time fan-out: checkPermission must not be mapped over a space list.
    assert ".map(" not in src or "checkPermission" not in src.split("ensureSpacePermissions")[0], (
        "checkPermission must not be fanned out at mount time"
    )


def test_client_file_search_drives_pagination_off_has_more():
    p = _CLIENT / "pages" / "knowledge" / "hooks" / "useFileManager.ts"
    if not p.exists():
        return
    src = _read(p)
    assert "has_more" in src, "search pagination must read has_more (T6c)"


# ─────────────────────────── E — roster version cache ─────────────────────


def test_roster_cache_key_is_version_derived():
    src = _read(_BACKEND / "permission" / "domain" / "services" / "relation_roster_cache.py")
    build = _func_src(src, "get_or_build")
    assert "version" in build, "roster cache must key on a data version (fail-safe when None)"


def test_roster_cache_wired_with_config_version_probe():
    src = _read(_BACKEND / "permission" / "api" / "endpoints" / "resource_permission.py")
    assert "aget_config_version" in src, "roster cache version comes from a lightweight config probe"
