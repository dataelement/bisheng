from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BISHENG_ROOT = _BACKEND_ROOT / "bisheng"
_COMPOSITION_ROOT = Path("bootstrap/approval_scenarios.py")

_APPROVAL_FORBIDDEN_IMPORTS = (
    "bisheng.permission.domain.services.resource_authorization_service",
    "bisheng.channel.domain.services.channel_authorization_service",
    "bisheng.knowledge.domain.services.knowledge_space_file_change",
    "bisheng.knowledge.domain.services.knowledge_space_mutation",
)
_BUSINESS_FORBIDDEN_IMPORTS = (
    "bisheng.approval.domain.models",
    "bisheng.approval.domain.repositories",
)
_BUSINESS_IMPLEMENTATION_IMPORTS = (
    "bisheng.permission.domain.services.resource_user_invite_approval_policy",
    "bisheng.permission.domain.services.resource_user_invite_decision_subscriber",
    "bisheng.knowledge.domain.services.knowledge_space_file_change_approval_policy",
    "bisheng.knowledge.domain.services.knowledge_space_file_change_decision_subscriber",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _matches_any(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def _format_violations(violations: list[tuple[Path, str]]) -> list[str]:
    return [f"{path.relative_to(_BISHENG_ROOT)}: {module}" for path, module in violations]


def test_approval_domain_does_not_import_f045_or_f046_business_implementations():
    violations: list[tuple[Path, str]] = []
    roots = (_BISHENG_ROOT / "approval", _BISHENG_ROOT / "worker" / "approval")

    for root in roots:
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if _matches_any(module, _APPROVAL_FORBIDDEN_IMPORTS):
                    violations.append((path, module))

    assert _format_violations(violations) == []


def test_f045_and_f046_business_domains_use_only_approval_application_ports():
    violations: list[tuple[Path, str]] = []
    roots = (_BISHENG_ROOT / "permission", _BISHENG_ROOT / "knowledge")

    for root in roots:
        for path in root.rglob("*.py"):
            for module in _imports(path):
                if _matches_any(module, _BUSINESS_FORBIDDEN_IMPORTS):
                    violations.append((path, module))

    assert _format_violations(violations) == []


def test_only_composition_root_imports_approval_ports_and_business_implementations():
    violations: list[Path] = []

    for path in _BISHENG_ROOT.rglob("*.py"):
        imports = _imports(path)
        imports_approval_ports = any(
            module == "bisheng.approval.domain.ports" or module.startswith("bisheng.approval.domain.ports.")
            for module in imports
        )
        imports_business_implementation = any(
            _matches_any(module, _BUSINESS_IMPLEMENTATION_IMPORTS) for module in imports
        )
        if imports_approval_ports and imports_business_implementation:
            relative_path = path.relative_to(_BISHENG_ROOT)
            if relative_path != _COMPOSITION_ROOT:
                violations.append(relative_path)

    assert [str(path) for path in violations] == []
