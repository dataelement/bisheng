"""T023 — F027 ReBAC static-verification sweep (AC-10, AC-11, AC-15, AC-16).

Consolidates the spec §2.3 static grep checklist into one test file so a
single ``pytest -k f027_rebac_static_grep`` confirms the cursor refactor
removed all the old count / OFFSET / scan-everything code paths and kept the
two boundary cases (single-dept GET + resource-permission tree) intact.

Why this file exists alongside T010/T012/T014's per-module asserts: the
per-module checks scope their AST to a single function; this file runs a
project-wide grep so any *new* caller of the deleted patterns (regardless of
which module added it) fails CI immediately.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


_BISHENG = Path(__file__).resolve().parents[2] / "bisheng"


def _grep_count(pattern: str, *paths: str, extra_args: list[str] | None = None) -> int:
    """Count grep hits across ``paths`` (relative to ``bisheng/``).

    Uses POSIX-extended regex (``-E``). Returns 0 when grep finds nothing.
    """
    cmd = ["grep", "-rE", pattern]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(str(_BISHENG / p) for p in paths)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 1:  # 1 = no matches, normal
        return 0
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    return len(lines)


# ---------------------------------------------------------------------------
# AC-11: `acount_user_knowledge(` no longer called from any service / endpoint
# ---------------------------------------------------------------------------


def test_no_callers_of_acount_user_knowledge():
    # The DAO method definition itself is allowed; only call sites are forbidden.
    proc = subprocess.run(
        ["grep", "-rnE", r"acount_user_knowledge\(", str(_BISHENG)],
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in proc.stdout.splitlines()
        if "def acount_user_knowledge" not in line
    ]
    assert hits == [], f"acount_user_knowledge still has callers: {hits}"


# ---------------------------------------------------------------------------
# AC-11: aget_all_apps no longer uses count_statement / count over sub_query
# ---------------------------------------------------------------------------


def test_aget_all_apps_no_count_statement():
    """Scoped to the body of FlowDao.aget_all_apps via source-text extraction."""
    src = (_BISHENG / "database" / "models" / "flow.py").read_text()
    # Slice from "async def aget_all_apps" to the next top-level def / @classmethod.
    m = re.search(r"async def aget_all_apps\b.*?(?=\n    @classmethod|\nclass )", src, re.DOTALL)
    assert m, "aget_all_apps not found"
    body = m.group(0)
    assert "count_statement" not in body
    assert "func.count(sub_query.c.id)" not in body


# ---------------------------------------------------------------------------
# AC-10: SpaceFileDao.async_list_children no longer called with page=N
# ---------------------------------------------------------------------------


def test_no_callers_pass_page_to_async_list_children():
    # Match `async_list_children(...page=...)` across multiple lines via grep -z
    # which treats input as null-separated lines (matches across newlines).
    proc = subprocess.run(
        [
            "grep", "-rnE", "-z",
            r"async_list_children\([^)]*\bpage=",
            str(_BISHENG),
        ],
        capture_output=True,
        text=True,
    )
    hits = [line for line in proc.stdout.split("\x00") if line.strip()]
    assert hits == [], f"async_list_children still receives page=: {hits}"


# ---------------------------------------------------------------------------
# AC-10: _scan_visible_child_items uses the "fetch until enough" cursor loop
# ---------------------------------------------------------------------------


def test_scan_visible_child_items_has_cursor_loop_invariants():
    src = (_BISHENG / "knowledge" / "domain" / "services" / "knowledge_space_service.py").read_text()
    # Function header → next def-at-same-indent.
    m = re.search(
        r"async def _scan_visible_child_items\b.*?(?=\n    async def |\n    def |\n    @classmethod|\nclass )",
        src,
        re.DOTALL,
    )
    assert m, "_scan_visible_child_items not found"
    body = m.group(0)
    assert "batch_cursor" in body
    assert "_compute_ext_rank_python" in body
    assert re.search(r"len\(visible_page_items\)\s*>\s*page_size", body)
    # The old OFFSET-style scan_page state is gone
    assert "scan_page" not in body


# ---------------------------------------------------------------------------
# AC-15: aget_department still populates member_count (boundary preserved)
# ---------------------------------------------------------------------------


def test_aget_department_still_uses_member_count():
    src = (_BISHENG / "department" / "domain" / "services" / "department_service.py").read_text()
    m = re.search(
        r"async def aget_department\b.*?(?=\n    async def |\n    def |\n    @classmethod|\nclass )",
        src,
        re.DOTALL,
    )
    assert m, "aget_department not found"
    body = m.group(0)
    assert "member_count" in body, "single-dept GET must retain member_count (AC-15)"


# ---------------------------------------------------------------------------
# AC-16: resource_permission endpoint still emits member_count (boundary)
# ---------------------------------------------------------------------------


def test_resource_permission_endpoint_still_emits_member_count():
    src = (_BISHENG / "permission" / "api" / "endpoints" / "resource_permission.py").read_text()
    assert "member_count" in src, (
        "resource_permission.py must retain member_count emission (AC-16)"
    )
