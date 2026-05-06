"""Guard rail: every tenant-aware ORM table must declare ``tenant_id`` with
``default=None``. A non-None Python default (e.g. ``default=1``) bypasses the
``before_flush`` hook in ``bisheng.core.database.tenant_filter`` because the
hook only auto-fills when ``current_val is None or current_val == 0``. The
v2.5 rollout had 13 tables silently writing child-tenant resources to root
because their models declared ``tenant_id: int = Field(default=1, ...)``.

This guard runs as a pure static AST scan — no module imports — so it stays
green regardless of whether optional third-party deps (pandas, elasticsearch,
celery, redis, ...) are installed in the developer's local venv.
"""

import ast
import os
from typing import List, Tuple

# Roots to walk. Limit to the bisheng package; skip test/scripts/migrations.
_BISHENG_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'bisheng'),
)
_SKIP_DIR_FRAGMENTS = (
    f'{os.sep}test{os.sep}',
    f'{os.sep}scripts{os.sep}',
    f'{os.sep}alembic{os.sep}',
    f'{os.sep}migrations{os.sep}',
    f'{os.sep}.venv{os.sep}',
)

# Allowlist for known non-ORM declarations. Each entry is
# (relative_filename_suffix, class_name). Add only with a recorded reason.
ALLOWLIST: List[Tuple[str, str]] = [
    # LoginUser is a Pydantic DTO populated from JWT payload, not an ORM
    # table. Its default=1 means "absence of tenant_id in JWT falls back to
    # root", which is its own design question (auth.py:169) — out of scope
    # for this storage-layer guard.
    ('user/domain/services/auth.py', 'LoginUser'),
    # AddSecondaryMembersRequest is a request DTO (root_tenant_id, not the
    # ORM tenant_id column).
    ('sso_sync/domain/schemas/payloads.py', 'AddSecondaryMembersRequest'),
]


def _is_allowlisted(file_path: str, class_name: str) -> bool:
    rel = os.path.relpath(file_path, _BISHENG_ROOT).replace(os.sep, '/')
    for suffix, allowed_cls in ALLOWLIST:
        suffix_norm = suffix.replace(os.sep, '/')
        if rel.endswith(suffix_norm) and class_name == allowed_cls:
            return True
    return False


def _extract_field_default(call_node: ast.Call) -> Tuple[bool, str]:
    """If ``call_node`` is a ``Field(...)`` call, return (has_default, repr).

    ``has_default == False`` means no ``default=`` kwarg (SQLModel treats
    this as PydanticUndefined → safe).
    """
    func = call_node.func
    if isinstance(func, ast.Name):
        if func.id != 'Field':
            return False, ''
    elif isinstance(func, ast.Attribute):
        if func.attr != 'Field':
            return False, ''
    else:
        return False, ''
    for kw in call_node.keywords:
        if kw.arg == 'default':
            return True, ast.unparse(kw.value)
    return False, ''


def _scan_file(path: str) -> List[str]:
    """Return offender description strings for one .py file."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            src = fh.read()
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError:
        return []
    offenders: List[str] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for stmt in cls.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            tgt = stmt.target
            if not (isinstance(tgt, ast.Name) and tgt.id == 'tenant_id'):
                continue
            if stmt.value is None:
                continue
            if not isinstance(stmt.value, ast.Call):
                continue
            has_default, default_repr = _extract_field_default(stmt.value)
            if not has_default:
                continue
            if default_repr in ('None',):
                continue
            if _is_allowlisted(path, cls.name):
                continue
            rel = os.path.relpath(path, _BISHENG_ROOT)
            offenders.append(
                f'  - bisheng/{rel}:{stmt.lineno} class {cls.name} '
                f'tenant_id default={default_repr}'
            )
    return offenders


def test_tenant_id_default_must_be_none():
    """Static AST scan: no ORM/SQLModel class may declare a non-None default
    for ``tenant_id``. Allowlisted DTOs are documented in ``ALLOWLIST``.
    """
    offenders: List[str] = []
    for root, dirs, files in os.walk(_BISHENG_ROOT):
        if any(frag in (root + os.sep) for frag in _SKIP_DIR_FRAGMENTS):
            dirs[:] = []
            continue
        for fname in files:
            if not fname.endswith('.py'):
                continue
            offenders.extend(_scan_file(os.path.join(root, fname)))

    assert not offenders, (
        'Tenant-aware ORM tables must declare tenant_id with default=None '
        'so before_flush can auto-fill from current_tenant_id. A non-None '
        'default bypasses the hook and silently writes child-tenant '
        'resources to root.\n\nOffenders:\n' + '\n'.join(offenders)
    )
