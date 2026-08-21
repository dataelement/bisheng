from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.department import Department, UserDepartment
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.open_endpoints.domain.models.filelib_department_mapping import FilelibDepartmentMapping
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


def _department(department_id: int, name: str, *, external_id: str | None = None) -> Department:
    return Department(
        id=department_id,
        dept_id=f"D-{department_id}",
        name=name,
        path=f"/{department_id}/",
        external_id=external_id,
    )


def _service(repository: SimpleNamespace) -> FilelibSyncService:
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=1, user_name="caller", user_role=[2], tenant_id=5),
        token_id=42,
        file_sync_rule=DeveloperTokenFileSyncRule.model_validate(
            {
                "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
                "business_domain": {"mode": "fixed", "code": "IT"},
                "target_space": {"mode": "fixed", "knowledge_id": 8},
            }
        ),
        repository=repository,
        knowledge_space_service=SimpleNamespace(),
    )


def _token_user():
    return SimpleNamespace(user_id=1, user_name="caller", external_id="caller-ext")


@pytest.mark.asyncio
async def test_missing_department_id_uses_caller_primary_department() -> None:
    caller_department = _department(10, "调用人部门")
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(return_value=_token_user()),
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
        find_department_mapping_by_external_department_id=AsyncMock(),
        find_department_by_external_id=AsyncMock(),
    )
    params = _service(repository).parse_params(
        json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"})
    )

    identity = await _service(repository)._resolve_identity(params)

    assert identity.main_department.id == 10
    repository.find_department_mapping_by_external_department_id.assert_not_awaited()
    repository.find_department_by_external_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_department_id_resolves_through_mapping_and_org_code() -> None:
    caller_department = _department(10, "调用人部门")
    mapped_department = _department(200, "映射部门", external_id="ORG-200")
    mapping = FilelibDepartmentMapping(
        id=1,
        external_department_id="20",
        external_department_name="外部部门",
        org_code="ORG-200",
    )
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(return_value=_token_user()),
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
        find_department_mapping_by_external_department_id=AsyncMock(return_value=mapping),
        find_department_by_external_id=AsyncMock(return_value=mapped_department),
    )
    params = _service(repository).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": "20",
            }
        )
    )

    identity = await _service(repository)._resolve_identity(params)

    assert identity.main_department.id == 200
    repository.find_department_mapping_by_external_department_id.assert_awaited_once_with("20")
    repository.find_department_by_external_id.assert_awaited_once_with("ORG-200", tenant_id=5)


@pytest.mark.asyncio
async def test_missing_mapping_falls_back_to_uploader_primary_department() -> None:
    uploader_department = _department(10, "上传人部门")
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(return_value=_token_user()),
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=uploader_department),
        find_department_mapping_by_external_department_id=AsyncMock(return_value=None),
        find_department_by_external_id=AsyncMock(),
    )
    params = _service(repository).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": "20",
            }
        )
    )

    identity = await _service(repository)._resolve_identity(params)

    assert identity.main_department.id == 10
    repository.find_department_by_external_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_department_for_org_code_falls_back_to_uploader_primary_department() -> None:
    uploader_department = _department(10, "上传人部门")
    mapping = FilelibDepartmentMapping(
        id=1,
        external_department_id="20",
        external_department_name="外部部门",
        org_code="ORG-200",
    )
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(return_value=_token_user()),
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=uploader_department),
        find_department_mapping_by_external_department_id=AsyncMock(return_value=mapping),
        find_department_by_external_id=AsyncMock(return_value=None),
    )
    params = _service(repository).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": "20",
            }
        )
    )

    identity = await _service(repository)._resolve_identity(params)

    assert identity.main_department.id == 10
    repository.find_department_by_external_id.assert_awaited_once_with("ORG-200", tenant_id=5)
