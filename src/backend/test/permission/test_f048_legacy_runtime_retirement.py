"""Static retirement gate for the pre-F048 permission runtime.

覆盖 AC: AC-05, AC-34, AC-103, AC-104, AC-105, AC-112, AC-115,
AC-116, AC-117, AC-144, AC-145
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bisheng.core.openfga.authorization_model_f048 import (
    LEGACY_RESOURCE_TYPES,
    MIGRATED_RESOURCE_TYPES,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import (
    PermissionService,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BISHENG_ROOT = BACKEND_ROOT / "bisheng"
REPO_ROOT = BACKEND_ROOT.parents[1]
PLATFORM_SOURCE = REPO_ROOT / "src/frontend/platform/src"
CLIENT_SOURCE = REPO_ROOT / "src/frontend/client/src"

RETIRED_RUNTIME_FILES = (
    "permission/domain/services/fine_grained_permission_service.py",
    "permission/domain/services/application_permission_service.py",
    "permission/domain/services/tool_permission_service.py",
    "permission/domain/services/relation_roster_cache.py",
    "permission/domain/knowledge_space_permission_template.py",
    "permission/domain/knowledge_library_permission_template.py",
    "permission/domain/application_permission_template.py",
    "permission/domain/tool_permission_template.py",
    "permission/domain/channel_permission_template.py",
    "permission/domain/workflow_app_permission.py",
    "permission/domain/relation_model_backfill.py",
    "permission/api/endpoints/permission_check.py",
    "permission/api/endpoints/resource_permission.py",
    "permission/migration/batch_utils.py",
    "permission/migration/f006_cli.py",
    "permission/migration/f006_constants.py",
    "permission/migration/f006_migrator.py",
    "permission/migration/f006_schemas.py",
    "permission/migration/migrate_rbac_to_rebac.py",
    "permission/migration/reconcile_role_access_fga.py",
)

RETIRED_SCRIPT_FILES = (
    "backfill_channel_member_rebac_grants.py",
    "backfill_channel_member_rebac_grants.sh",
    "backfill_relation_model_move_permissions.py",
    "clean_department_space_user_group_grants.py",
    "migrate_channel_permissions_for_relation_models.py",
    "migrate_channel_permissions_for_relation_models.sh",
    "permission_migration.sh",
    "permission_rbac_to_rebac_migration.py",
)

MIGRATED_RESOURCE_ROOTS = (
    "api/services",
    "channel",
    "knowledge",
    "telemetry_search",
    "tool",
    "workstation",
)

FORBIDDEN_IMPORTS = frozenset(
    {
        "bisheng.permission.domain.services.fine_grained_permission_service",
        "bisheng.permission.domain.services.application_permission_service",
        "bisheng.permission.domain.services.tool_permission_service",
        "bisheng.permission.domain.services.relation_roster_cache",
        "bisheng.permission.domain.knowledge_space_permission_template",
        "bisheng.permission.domain.knowledge_library_permission_template",
        "bisheng.permission.domain.application_permission_template",
        "bisheng.permission.domain.tool_permission_template",
        "bisheng.permission.domain.channel_permission_template",
        "bisheng.permission.domain.workflow_app_permission",
        "bisheng.permission.domain.relation_model_backfill",
        "bisheng.permission.api.endpoints.permission_check",
        "bisheng.permission.api.endpoints.resource_permission",
    }
)

FORBIDDEN_FRONTEND_TOKENS = (
    "permission_id",
    "permissionId",
    "usePermissionLevels",
    "getResourceGrant",
    "resource-permissions",
    "relation-models",
    "grantable-relations",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_pre_f048_runtime_modules_are_deleted() -> None:
    existing = [relative for relative in RETIRED_RUNTIME_FILES if (BISHENG_ROOT / relative).exists()]
    assert existing == []


def test_pre_f048_data_and_backfill_scripts_are_deleted() -> None:
    scripts_root = BACKEND_ROOT / "scripts"
    existing = [relative for relative in RETIRED_SCRIPT_FILES if (scripts_root / relative).exists()]
    assert existing == []
    assert (scripts_root / "migrate_f048_permission_data.py").is_file()


def test_migrated_business_modules_do_not_import_retired_runtime() -> None:
    violations: list[str] = []
    for relative_root in MIGRATED_RESOURCE_ROOTS:
        for path in (BISHENG_ROOT / relative_root).rglob("*.py"):
            for imported in _imports(path):
                if imported in FORBIDDEN_IMPORTS:
                    violations.append(f"{path.relative_to(BACKEND_ROOT)}: {imported}")
    assert violations == []


@pytest.mark.parametrize("resource_type", MIGRATED_RESOURCE_TYPES)
def test_legacy_permission_service_rejects_migrated_resources(
    resource_type: str,
) -> None:
    with pytest.raises(RuntimeError, match="F048 business resource"):
        PermissionService._require_allowed_runtime_type(resource_type)


def test_only_llm_resources_are_exposed_by_the_legacy_model_allowlist() -> None:
    assert LEGACY_RESOURCE_TYPES == ("llm_server", "llm_model")


@pytest.mark.asyncio
async def test_legacy_tuple_writer_rejects_migrated_resources() -> None:
    with pytest.raises(RuntimeError, match="F048 business resource"):
        await PermissionService.batch_write_tuples(
            [
                TupleOperation(
                    action="write",
                    user="user:7",
                    relation="owner",
                    object="workflow:42",
                )
            ]
        )


def test_legacy_department_subject_uses_userset_without_business_query() -> None:
    assert PermissionService._subject_userset("department", 9, True) == "department:9#subtree_member"


def test_role_access_and_owner_compatibility_are_identity_only() -> None:
    role_sync_source = (BISHENG_ROOT / "permission/domain/services/legacy_rbac_sync_service.py").read_text(
        encoding="utf-8"
    )
    owner_source = (BISHENG_ROOT / "permission/domain/services/owner_service.py").read_text(encoding="utf-8")

    assert "ACCESS_TYPE_TO_FGA: dict[int, tuple[str, str]] = {}" in role_sync_source
    assert "_role_access_rows" not in role_sync_source
    assert "SELECT role_id" not in role_sync_source
    assert "get_async_db_session" not in role_sync_source
    assert "transfer_ownership" not in owner_source
    assert "write_owner_tuple" not in owner_source
    assert "delete_non_owner_resource_tuples" not in owner_source
    assert "identity-only after F048" in owner_source


def test_legacy_role_resource_routes_are_retired() -> None:
    user_api_source = (BISHENG_ROOT / "user/api/user.py").read_text(encoding="utf-8")
    group_api_source = (BISHENG_ROOT / "api/v1/usergroup.py").read_text(encoding="utf-8")
    group_service_source = (BISHENG_ROOT / "api/services/role_group_service.py").read_text(encoding="utf-8")

    assert '"/role_access/refresh"' not in user_api_source
    assert '"/role_access/list"' not in user_api_source
    assert '"/get_group_resources"' not in group_api_source
    assert "def get_group_resources" not in group_service_source
    assert "def get_group_dashboards" not in group_service_source


def test_frontends_do_not_expose_retired_permission_contracts() -> None:
    violations: list[str] = []
    for source_root in (PLATFORM_SOURCE, CLIENT_SOURCE):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
                continue
            source = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_FRONTEND_TOKENS:
                if token in source:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert violations == []


def test_openfga_runtime_rejects_dual_or_legacy_clients() -> None:
    manager_source = (BISHENG_ROOT / "core/openfga/manager.py").read_text(encoding="utf-8")
    config_source = (BISHENG_ROOT / "core/config/openfga.py").read_text(encoding="utf-8")
    assert "does not support legacy or dual-model clients" in manager_source
    assert "F048 requires false" in config_source
    assert "F048 requires an empty value" in config_source
    assert "mirror to legacy_model_id" not in config_source
    assert "Rollback to the legacy model" not in config_source
