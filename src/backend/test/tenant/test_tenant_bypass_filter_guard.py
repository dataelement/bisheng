"""Guard rail: every ``with bypass_tenant_filter():`` block that issues a
``select(<TenantAwareModel>)`` MUST manually carry a ``tenant_id`` predicate,
otherwise it silently leaks rows across tenants.

Why this exists
---------------
The companion guard ``test_tenant_id_default_guard`` covers the *write* side
(no ``default=1`` on ``tenant_id``). This guard covers the *read* side: once
a caller wraps work in ``bypass_tenant_filter()``, the auto-injected
``WHERE tenant_id = ?`` from ``do_orm_execute`` is gone, and the caller must
re-supply the predicate by hand. The v2.5 role-list bug had exactly this
shape — it was caught only because someone hand-traced it.

Scan model
----------
Pure AST, no imports. For every ``with`` whose context manager mentions
``bypass_tenant_filter``:
  1. Collect the names referenced inside ``select(<Name>, ...)`` /
     ``select(<Name>.col, ...)`` calls in that block.
  2. If any of those names is a known tenant-aware ORM class **and** the
     block source text does not contain the literal token ``tenant_id``,
     flag it.

Token-based matching is intentionally loose: we do not parse ``.where(...)``
chains. Any reference to ``tenant_id`` anywhere in the block — predicate,
column projection, comment, helper call — clears the row. False negatives
are acceptable here; the goal is to make naked bypass+select reads loud,
not to verify correctness.

Locking strategy
----------------
We snapshot the current offender set as ``ALLOWLIST`` below. New entries
fail the test red — the author either (a) adds a ``tenant_id`` predicate
or (b) reviews the call site and adds it to the allowlist with a one-line
reason. Removing an entry by fixing the underlying caller is encouraged
and only requires deleting the line.
"""

import ast
import os

_BISHENG_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "bisheng"),
)
_SKIP_DIR_FRAGMENTS = (
    f"{os.sep}test{os.sep}",
    f"{os.sep}scripts{os.sep}",
    f"{os.sep}alembic{os.sep}",
    f"{os.sep}migrations{os.sep}",
    f"{os.sep}.venv{os.sep}",
)

# Hardcoded so the guard runs without importing the ORM (third-party deps may
# not be installed). Sourced from ``grep -rn "tenant_id" .../models`` plus the
# v2.5 audit. Update when adding a new tenant-aware table.
TENANT_AWARE_MODELS: set[str] = {
    "Role",
    "Knowledge",
    "KnowledgeFile",
    "Flow",
    "FlowVersion",
    "Group",
    "GroupResource",
    "Department",
    "Assistant",
    "Message",
    "ChatMessage",
    "MessageSession",
    "LLMServer",
    "LLMServerModel",
    "LLMCallLog",
    "LLMTokenLog",
    "FailedTuple",
    "AuditLog",
    "DepartmentKnowledgeSpace",
    "ApprovalRequest",
    "OrgSyncConfig",
    "OrgSyncLog",
}

# Allowlist of (relative_filename_suffix, lineno_of_with). Each entry needs
# a one-line reason. Lineno is the line where ``with bypass_tenant_filter``
# appears, which is the same line the offender report prints.
#
# Why a list of (file, lineno) instead of a hash: the lineno is what authors
# see in the failure message, so reproducing it is a pure copy-paste, and a
# stable lineno is enough to localize the call (file moves are rare and
# would re-trigger the guard, which is the right outcome).
ALLOWLIST: set[tuple[str, int]] = {
    # ``_resource_ids_by_creator_user_ids`` deliberately walks resources
    # across tenants — it is a ReBAC reverse-lookup helper ("which resources
    # did these users create?"). The two callers (``_finalize_accessible_ids``
    # and ``_resource_ids_implicit_dept_admin_scope``) both fold the result
    # into ``_filter_ids_by_tenant_gate``, which re-applies the tenant
    # boundary. The helper itself must stay cross-tenant; tightening it
    # would break dept-admin and child-tenant-admin scope union semantics.
    ("permission/domain/services/permission_service.py", 1010),
}


def _qualname(node: ast.expr) -> str:
    """Return ``foo.bar.baz`` for an Attribute / Name chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qualname(node.value)}.{node.attr}"
    return ""


def _is_bypass_with(node: ast.With) -> bool:
    """True iff any context-manager item in this ``with`` is bypass_tenant_filter."""
    for item in node.items:
        ctx = item.context_expr
        # ``with bypass_tenant_filter():`` → Call(func=Name('bypass_tenant_filter'))
        # ``with bypass_tenant_filter(), strict_tenant_filter():`` is a tuple of items
        if isinstance(ctx, ast.Call):
            name = _qualname(ctx.func)
            if name.endswith("bypass_tenant_filter"):
                return True
        elif isinstance(ctx, (ast.Name, ast.Attribute)):
            name = _qualname(ctx)
            if name.endswith("bypass_tenant_filter"):
                return True
    return False


def _select_argument_names(call: ast.Call) -> list[str]:
    """For ``select(<expr>, ...)`` return identifier roots of each positional arg.

    Examples:
        select(Role)              → ['Role']
        select(Role.id, Role.name) → ['Role', 'Role']
        select(func.count(Role.id)) → ['Role']  (recurses)
    """
    names: list[str] = []
    for arg in call.args:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                root = sub
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    names.append(root.id)
    return names


def _block_source(src_lines: list[str], block: ast.With) -> str:
    """Return the source text covered by this ``with`` block, inclusive of body."""
    start = block.lineno - 1
    end = block.end_lineno or block.lineno
    return "\n".join(src_lines[start:end])


def _scan_file(path: str) -> list[tuple[str, int, str]]:
    """Return list of (rel_path, lineno, summary) offender tuples for one file."""
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    src_lines = src.splitlines()

    offenders: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not _is_bypass_with(node):
            continue

        # Walk the body for select(<TenantAware>) calls.
        tenant_aware_hits: list[str] = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func_name = _qualname(sub.func)
            if not (func_name == "select" or func_name.endswith(".select")):
                continue
            for n in _select_argument_names(sub):
                if n in TENANT_AWARE_MODELS:
                    tenant_aware_hits.append(n)

        if not tenant_aware_hits:
            continue

        # Block source must mention the literal token tenant_id somewhere.
        block_src = _block_source(src_lines, node)
        if "tenant_id" in block_src:
            continue

        rel = os.path.relpath(path, _BISHENG_ROOT)
        offenders.append(
            (
                rel,
                node.lineno,
                f"select({'/'.join(sorted(set(tenant_aware_hits)))}) inside "
                f"bypass_tenant_filter without any tenant_id predicate",
            )
        )
    return offenders


def test_bypass_tenant_filter_must_carry_tenant_id_predicate():
    """Naked ``select(<TenantAware>)`` inside ``bypass_tenant_filter`` blocks."""
    offenders: list[tuple[str, int, str]] = []
    for root, dirs, files in os.walk(_BISHENG_ROOT):
        if any(frag in (root + os.sep) for frag in _SKIP_DIR_FRAGMENTS):
            dirs[:] = []
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            offenders.extend(_scan_file(os.path.join(root, fname)))

    # Convert to a set of (file_suffix, lineno) for allowlist comparison.
    actual = {(o[0].replace(os.sep, "/"), o[1]) for o in offenders}
    allowed = {(f.replace(os.sep, "/"), ln) for f, ln in ALLOWLIST}

    new_violations = sorted(actual - allowed)
    stale_allowlist = sorted(allowed - actual)

    msgs = []
    if new_violations:
        lookup = {(o[0].replace(os.sep, "/"), o[1]): o[2] for o in offenders}
        msgs.append(
            "New bypass_tenant_filter blocks select tenant-aware tables "
            "without a tenant_id predicate. Add ``tenant_id`` to the WHERE "
            "clause, or — if the cross-tenant read is intentional — append "
            "an ALLOWLIST entry in this file with a one-line reason.\n\n"
            "New violations:\n"
            + "\n".join(f"  - bisheng/{path}:{ln} — {lookup[(path, ln)]}" for path, ln in new_violations)
        )
    if stale_allowlist:
        msgs.append(
            "ALLOWLIST entries no longer match any offender (the call site "
            "was likely fixed or moved). Remove these entries:\n"
            + "\n".join(f"  - {path}:{ln}" for path, ln in stale_allowlist)
        )

    assert not msgs, "\n\n".join(msgs)
