"""Retired action labels belong only to historical migrations and model guards."""

import ast
import re
from pathlib import Path


def test_online_backend_has_no_retired_action_literals():
    backend = Path(__file__).resolve().parents[2]
    violations = []
    for path in (backend / "bisheng").rglob("*.py"):
        relative = path.relative_to(backend).as_posix()
        if (
            relative.startswith("bisheng/permission/migration/")
            or relative == "bisheng/core/openfga/authorization_model_f048.py"
        ):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in ("use", "use_kb", "use_app", "use_tool"):
                violations.append(f"{relative}:{node.lineno}")
    assert not violations, violations


def test_online_frontends_have_no_retired_action_literals():
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    violations = []
    for app in ("client", "platform"):
        for path in (frontend / app / "src").rglob("*"):
            if path.suffix not in {".ts", ".tsx", ".js", ".jsx"} or ".test." in path.name or ".spec." in path.name:
                continue
            if re.search(r"""(["'])use(?:_kb|_app|_tool)?\1""", path.read_text()):
                violations.append(path.relative_to(frontend).as_posix())
    assert not violations, violations
