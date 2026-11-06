"""Names used at runtime must be imported (they were not, which raised NameError)."""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "bisheng"


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def test_audit_log_service_imports_group_resource_dao():
    # The group-admin branch of the audit-log query calls GroupResourceDao.get_groups_resource.
    assert "GroupResourceDao" in _imported_names(BACKEND / "api/services/audit_log.py")


def test_input_node_imports_media_file_count_limit_error():
    # InputNode raises it when a variable holds too many media files.
    assert "WorkflowMediaFileCountLimitError" in _imported_names(BACKEND / "workflow/nodes/input/input.py")
