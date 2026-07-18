"""Convention-based SQLModel discovery for schema bootstrap tooling."""

import ast
import importlib
from pathlib import Path

_BISHENG_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_SQLMODEL_DIRECTORY_PATTERNS = (
    "database/models",
    "common/models",
    "*/domain/models",
)


def _declares_sqlmodel_table(module_path: Path) -> bool:
    """Return whether a module declares a literal ``table=True`` class."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    return any(
        isinstance(node, ast.ClassDef)
        and any(
            keyword.arg == "table" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in node.keywords
        )
        for node in ast.walk(tree)
    )


def _module_name(module_path: Path) -> str:
    relative_path = module_path.relative_to(_BISHENG_PACKAGE_ROOT.parent).with_suffix("")
    module_parts = list(relative_path.parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts)


def discover_sqlmodel_module_names() -> tuple[str, ...]:
    """Find table modules under the repository's model-directory conventions."""
    model_directories = {
        model_directory
        for pattern in _SQLMODEL_DIRECTORY_PATTERNS
        for model_directory in _BISHENG_PACKAGE_ROOT.glob(pattern)
        if model_directory.is_dir()
    }
    module_names = {
        _module_name(module_path)
        for model_directory in model_directories
        for module_path in model_directory.rglob("*.py")
        if _declares_sqlmodel_table(module_path)
    }
    return tuple(sorted(module_names))


def import_all_sqlmodel_models() -> None:
    """Strictly import every discovered model so metadata is complete."""
    module_names = discover_sqlmodel_module_names()
    if not module_names:
        raise RuntimeError("No SQLModel table modules found under the model-directory conventions")

    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to import SQLModel module {module_name}") from exc
