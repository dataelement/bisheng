"""Architecture boundaries for the F048 permission domain.

覆盖 AC: AC-30, AC-34, AC-35, AC-70, AC-155
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from bisheng.permission.application.resource_permission_coordinator import (
    ResourcePermissionCoordinator,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PERMISSION_ROOT = BACKEND_ROOT / "bisheng" / "permission"
SERVICE_ROOT = PERMISSION_ROOT / "domain" / "services"
F048_DOMAIN_FILES = (
    "catalog_policy.py",
    "model_policy.py",
    "catalog_service.py",
    "projection_plan.py",
    "projection_service.py",
    "grant_source_service.py",
    "grant_service.py",
    "mode_service.py",
    "resource_lifecycle_policy.py",
    "permission_action_service.py",
    "permission_explain_service.py",
    "permission_service.py",
)
FORBIDDEN_IMPORT_FRAGMENTS = (
    "bisheng.knowledge",
    "bisheng.flow",
    "bisheng.workflow",
    "bisheng.dashboard",
    "bisheng.tool",
    "bisheng.channel",
    "bisheng.api.services",
    "bisheng.database.models.assistant",
    "bisheng.database.models.department",
    "bisheng.database.models.flow",
    "bisheng.database.models.group",
    "bisheng.database.models.tenant",
    "bisheng.database.models.user_group",
    "bisheng.telemetry_search",
    "bisheng.tenant",
    "bisheng.user.domain",
    "bisheng.workstation",
    "bisheng.linsight",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def test_f048_domain_does_not_import_business_orm_repository_or_service() -> None:
    for filename in F048_DOMAIN_FILES:
        assert (SERVICE_ROOT / filename).exists(), filename

    violations: list[str] = []
    for path in PERMISSION_ROOT.rglob("*.py"):
        relative = path.relative_to(BACKEND_ROOT)
        for imported in _imports(path):
            if any(fragment in imported for fragment in FORBIDDEN_IMPORT_FRAGMENTS):
                violations.append(f"{relative}: {imported}")
    assert violations == []


def test_http_payload_cannot_construct_a_verified_permission_target() -> None:
    payload = {
        "tenant_id": 7,
        "resource_type": "workflow",
        "resource_id": "42",
        "resource_version": 3,
        "parent_type": None,
        "parent_id": None,
        "context_version": "forged",
        "status": "ACTIVE",
    }
    with pytest.raises(ValidationError, match="business Service"):
        VerifiedPermissionTarget.model_validate(payload)
    with pytest.raises(ValidationError, match="business Service"):
        VerifiedPermissionTarget(**{key: value for key, value in payload.items() if key != "status"})


def test_business_service_factory_creates_target_and_coordinator_rejects_dict() -> None:
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="workflow",
        resource_id="42",
        resource_version=3,
        parent_type=None,
        parent_id=None,
        context_version="repo-row-version-3",
    )
    assert target.tenant_id == 7
    coordinator = ResourcePermissionCoordinator(
        decision_service=object(),
        explain_service=object(),
        display_port=None,
    )
    assert coordinator.require_verified_target(target) is target
    with pytest.raises(TypeError, match="VerifiedPermissionTarget"):
        coordinator.require_verified_target(
            {
                "tenant_id": 7,
                "resource_type": "workflow",
                "resource_id": "42",
            }
        )
