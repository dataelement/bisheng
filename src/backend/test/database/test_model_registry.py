"""Guards for convention-based SQLModel discovery used by DB bootstrap."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from bisheng.core.database import model_discovery
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names, import_all_sqlmodel_models

_BISHENG_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _declares_sqlmodel_table(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.ClassDef)
        and any(
            keyword.arg == "table" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in node.keywords
        )
        for node in ast.walk(tree)
    )


def _module_name(path: Path) -> str:
    module_parts = list(path.relative_to(_BISHENG_ROOT.parent).with_suffix("").parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts)


def test_discovery_covers_every_literal_sqlmodel_table_module():
    discovered_modules = {_module_name(path) for path in _BISHENG_ROOT.rglob("*.py") if _declares_sqlmodel_table(path)}
    convention_modules = set(discover_sqlmodel_module_names())

    missing_modules = discovered_modules - convention_modules

    assert not missing_modules, (
        f"SQLModel table modules outside the model-directory conventions: {sorted(missing_modules)}"
    )


def test_strict_model_loading_registers_space_channel_member():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlmodel import SQLModel; "
            "from bisheng.core.database.model_discovery import import_all_sqlmodel_models; "
            "import_all_sqlmodel_models(); "
            "assert 'space_channel_member' in SQLModel.metadata.tables",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_strict_model_loading_raises_when_a_discovered_module_cannot_import(monkeypatch):
    missing_module = "bisheng.common.models.does_not_exist"
    monkeypatch.setattr(model_discovery, "discover_sqlmodel_module_names", lambda: (missing_module,))

    with pytest.raises(RuntimeError, match=missing_module):
        import_all_sqlmodel_models()


def test_strict_model_loading_rejects_empty_discovery(monkeypatch):
    monkeypatch.setattr(model_discovery, "discover_sqlmodel_module_names", tuple)

    with pytest.raises(RuntimeError, match="No SQLModel table modules"):
        import_all_sqlmodel_models()
