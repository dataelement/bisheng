"""Repo-level guard: never pass ``exc_info=`` to the loguru logger.

Loguru has no ``exc_info`` parameter. Any kwarg makes it run ``str.format()`` on
the message, so a message embedding a provider error payload — which routinely
contains literal braces, e.g. ``Error code: 429 - {'error': {...}}`` — raises
``KeyError`` from inside ``Logger._log``, *before* any handler runs.

That is not a cosmetic logging bug. It fired in a ``except`` clause in
``task_exec.async_run``, which killed the failure handler on the line after it
and left the Linsight session stuck ``IN_PROGRESS`` forever (frontend spinning
on a task that died hours earlier).

Files using stdlib ``logging`` are exempt — there ``exc_info=`` is correct, and
``core/logger.py``'s ``InterceptHandler`` forwards it to loguru properly.
"""

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = BACKEND_ROOT / "bisheng"


def _loguru_modules() -> list[Path]:
    """Every module that binds ``logger`` to loguru."""
    found = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "from loguru import logger" in text:
            found.append(path)
    return found


def _exc_info_call_lines(path: Path) -> list[int]:
    """Lines where a ``logger.<method>(..., exc_info=...)`` call appears."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `logger.error(...)`, `logger.warning(...)`, ... but NOT
        # `logger.opt(exception=...)` (keyword is `exception`, which is correct).
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "logger"):
            continue
        if any(kw.arg == "exc_info" for kw in node.keywords):
            hits.append(node.lineno)
    return hits


def test_no_exc_info_passed_to_loguru():
    modules = _loguru_modules()
    assert modules, "sanity: expected to find loguru modules under bisheng/"

    offenders = []
    for path in modules:
        for line in _exc_info_call_lines(path):
            offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{line}")

    assert not offenders, (
        "loguru takes no exc_info= kwarg; passing one makes it str.format() the "
        "message, which raises KeyError on any message containing braces.\n"
        "Use logger.exception(msg) for ERROR, or logger.opt(exception=True).<level>(msg).\n"
        "Offending call sites:\n  " + "\n  ".join(offenders)
    )


def test_exc_info_kwarg_really_breaks_on_a_provider_payload():
    """Pin the mechanism, so the guard above never looks like cargo cult."""
    from loguru import logger

    payload = "Error code: 429 - {'error': {'message': 'quota', 'type': 'insufficient_quota'}}"
    message = f"Task execution failed: {payload}"

    with pytest.raises(KeyError) as excinfo:
        logger.error(message, exc_info=True)
    # KeyError carries the brace content verbatim -> str is "'error'" (with quotes)
    assert str(excinfo.value) == "\"'error'\""

    # The sanctioned forms stay quiet on the exact same message.
    logger.exception(message)
    logger.opt(exception=True).warning(message)
