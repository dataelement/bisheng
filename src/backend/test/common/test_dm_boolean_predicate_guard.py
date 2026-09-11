"""Repo-level guard: never write ``.is_(True)`` / ``.is_(False)`` in a query.

SQLAlchemy renders those as ``IS true`` / ``IS false``. The DaMeng dialect turns
the literal into ``0`` / ``1``, producing ``col IS 0`` — which DM8 rejects with a
plain syntax error (``[CODE:-2007] ... nearby [0] has error``), so the endpoint
500s on DM while passing every MySQL test.

``col == False`` renders as ``col = 0`` and runs on both engines. That is why the
codebase carries ``# noqa: E712`` on boolean comparisons instead of "fixing" them
into the idiomatic ``.is_()`` form — the noqa is load-bearing (constitution C2,
dual-DB support).

Precedent: F053's session-subject scope filter shipped ``.is_(False)`` and took
``GET /api/v1/chat/list`` down on the COFCO DM deployment (2026-09-07).
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = BACKEND_ROOT / "bisheng"


def _is_boolean_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _offending_lines(path: Path) -> list[int]:
    """Lines holding a ``<expr>.is_(True)`` / ``.is_(False)`` call."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"is_", "isnot"}:
            continue
        if len(node.args) == 1 and _is_boolean_literal(node.args[0]):
            hits.append(node.lineno)
    return hits


def test_no_is_boolean_predicates_in_backend_sources():
    offenders = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        lines = _offending_lines(path)
        if lines:
            offenders[str(path.relative_to(BACKEND_ROOT))] = lines

    assert not offenders, (
        "`.is_(True)`/`.is_(False)`/`.isnot(...)` on a boolean renders as `IS 0`/`IS 1`, "
        "which DM8 rejects as a syntax error. Use `col == False  # noqa: E712` instead. "
        f"Offenders: {offenders}"
    )
