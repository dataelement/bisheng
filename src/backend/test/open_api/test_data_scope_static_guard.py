"""F066 static fences: no new admin-identity reads sneak onto the v2 path.

覆盖 AC: AC-R3

The narrowing is enforced inside the F048 permission service, which any
``login_user.is_admin()`` / ``is_global_super`` consumption bypasses.  The two
service files below carry the audited legacy consumption points (design
decision 5); a rising count means someone opened a new bypass and must either
route it through the permission actor or extend the audit here — with review.
"""

from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# file (relative to src/backend) -> exact number of "is_global_super" tokens.
AUDITED_ADMIN_READS = {
    # 2x system_scope (both guarded by _f066_data_scope_narrowed) + one helper.
    "bisheng/knowledge/domain/services/knowledge_space_service.py": 3,
    # init_login_user real-role resolution feeding the v2 operator facade.
    "bisheng/open_endpoints/domain/utils.py": 2,
}


def test_admin_identity_reads_on_v2_knowledge_path_are_pinned():
    for relative, expected in AUDITED_ADMIN_READS.items():
        text = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
        assert text.count("is_global_super") == expected, (
            f"{relative} now reads is_global_super {text.count('is_global_super')} times"
            f" (audited: {expected}). A new admin-identity read bypasses the F066"
            " data-scope narrowing — consult the permission actor instead, or"
            " extend this audit with review."
        )


def test_open_endpoints_grow_no_new_admin_identity_reads():
    hits = []
    for path in sorted((BACKEND_ROOT / "bisheng" / "open_endpoints").rglob("*.py")):
        count = path.read_text(encoding="utf-8").count("is_global_super")
        if count:
            hits.append((str(path.relative_to(BACKEND_ROOT)), count))
    assert hits == [("bisheng/open_endpoints/domain/utils.py", 2)], hits


def test_narrowed_guard_is_wired_to_both_system_scope_reads():
    text = (BACKEND_ROOT / "bisheng" / "knowledge" / "domain" / "services" / "knowledge_space_service.py").read_text(
        encoding="utf-8"
    )
    assert text.count("bool(self.login_user.is_global_super) and not _f066_data_scope_narrowed()") == 2, (
        "a system_scope read lost its F066 guard"
    )
