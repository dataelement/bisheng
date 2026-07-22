from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import (
    FilelibSyncConflictError,
    FilelibSyncInvalidParamsError,
)
from bisheng.common.errcode.knowledge_space import DepartmentKnowledgeSpaceAmbiguousError
from bisheng.database.models.department import Department, UserDepartment
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


def _department(department_id: int, name: str, path: str | None = None) -> Department:
    return Department(
        id=department_id,
        dept_id=f"D-{department_id}",
        name=name,
        path=path or f"/{department_id}/",
    )


def _rule(
    business_domain_mode: str = "fixed",
    target_space_mode: str = "fixed",
    dynamic_source: str | None = None,
) -> DeveloperTokenFileSyncRule:
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {
                "mode": business_domain_mode,
                "code": "IT" if business_domain_mode == "fixed" else None,
            },
            "target_space": {
                "mode": target_space_mode,
                "knowledge_id": 8 if target_space_mode == "fixed" else None,
            },
            "dynamic_source": dynamic_source,
        }
    )


def _service(rule, repository=None, knowledge_space_service=None) -> FilelibSyncService:
    return FilelibSyncService(
        login_user=UserPayload(
            user_id=1,
            user_name="caller",
            user_role=[2],
            tenant_id=5,
        ),
        token_id=42,
        file_sync_rule=rule,
        repository=repository or SimpleNamespace(),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


@pytest.mark.parametrize(
    ("domain_mode", "space_mode", "source", "missing_field"),
    [
        ("fixed", "dynamic", "department_id", "department_id"),
        ("dynamic", "fixed", "responsible_person_id", "responsible_person_id"),
        ("dynamic", "dynamic", "department_id", "department_id"),
    ],
)
def test_dynamic_rule_requires_exact_configured_id(
    domain_mode,
    space_mode,
    source,
    missing_field,
) -> None:
    service = _service(_rule(domain_mode, space_mode, source))
    params = service.parse_params(json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"}))

    with pytest.raises(FilelibSyncInvalidParamsError, match=missing_field):
        service._require_dynamic_source_id(params)


def test_fixed_fixed_rule_does_not_require_dynamic_id() -> None:
    service = _service(_rule())
    params = service.parse_params(json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"}))

    service._require_dynamic_source_id(params)


@pytest.mark.asyncio
async def test_department_dynamic_source_selects_explicit_department() -> None:
    caller_department = _department(10, "调用人部门")
    selected_department = _department(20, "动态部门")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(
            side_effect=lambda department_id: {
                10: caller_department,
                20: selected_department,
            }.get(department_id)
        ),
    )
    params = _service(_rule()).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": 20,
            }
        )
    )

    identity = await _service(
        _rule("dynamic", "dynamic", "department_id"),
        repository,
    )._resolve_identity(params)

    assert identity.main_department.id == 20
    assert identity.selected_department.id == 20
    assert identity.responsible_user_id == 1


@pytest.mark.asyncio
async def test_responsible_person_requires_unique_primary_department() -> None:
    caller_department = _department(10, "调用人部门")
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(return_value=SimpleNamespace(user_id=2, user_name="owner")),
        find_primary_departments=AsyncMock(
            side_effect=[
                [UserDepartment(user_id=1, department_id=10, is_primary=1)],
                [
                    UserDepartment(user_id=2, department_id=20, is_primary=1),
                    UserDepartment(user_id=2, department_id=21, is_primary=1),
                ],
            ]
        ),
        find_department_by_id=AsyncMock(return_value=caller_department),
    )
    service = _service(
        _rule("dynamic", "fixed", "responsible_person_id"),
        repository,
    )
    params = service.parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "responsible_person_id": 2,
            }
        )
    )

    with pytest.raises(FilelibSyncConflictError, match="multiple primary departments"):
        await service._resolve_identity(params)


def test_document_type_resolves_codes_within_selected_parent() -> None:
    expected_child = SimpleNamespace(code="MGMT_POLICY", label="管理政策")
    expected_parent = SimpleNamespace(
        code="POLICY",
        label="政策制度",
        children=[expected_child],
    )
    other_parent = SimpleNamespace(
        code="OTHER",
        label="其他",
        children=[SimpleNamespace(code="MGMT_POLICY", label="同码")],
    )
    config = SimpleNamespace(portal=SimpleNamespace(document_types=[other_parent, expected_parent]))

    parent, child = _service(_rule())._resolve_document_type(config)

    assert parent is expected_parent
    assert child is expected_child


def test_duplicate_dynamic_business_domains_are_rejected() -> None:
    config = SimpleNamespace(
        portal=SimpleNamespace(
            domains=[
                SimpleNamespace(enabled=True, code="IT", name="信息", department_ids=[20]),
                SimpleNamespace(enabled=True, code="SA", name="安全", department_ids=[20]),
            ]
        )
    )
    service = _service(_rule("dynamic", "fixed", "department_id"))

    with pytest.raises(FilelibSyncConflictError, match="multiple business domains"):
        service._resolve_business_domain(config, _department(20, "动态部门"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("domain_mode", "space_mode", "source", "expected_domain", "expected_space"),
    [
        ("fixed", "fixed", None, "IT", 8),
        ("fixed", "dynamic", "department_id", "IT", 22),
        ("dynamic", "fixed", "department_id", "SA", 8),
        ("dynamic", "dynamic", "department_id", "SA", 22),
    ],
)
async def test_fixed_dynamic_matrix_resolves_independent_dimensions(
    domain_mode,
    space_mode,
    source,
    expected_domain,
    expected_space,
) -> None:
    fixed_space = Knowledge(id=8, name="固定库", type=3, business_domain_codes=[expected_domain])
    dynamic_space = Knowledge(id=22, name="动态库", type=3, business_domain_codes=[expected_domain])
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(
            side_effect=lambda knowledge_id: fixed_space if knowledge_id == 8 else dynamic_space
        )
    )
    service = _service(_rule(domain_mode, space_mode, source), repository)
    selected_department = _department(20, "动态部门", "/1/20/")
    identity = SimpleNamespace(selected_department=selected_department)
    config = SimpleNamespace(
        portal=SimpleNamespace(
            domains=[
                SimpleNamespace(
                    enabled=True,
                    code="IT",
                    name="信息",
                    department_ids=[],
                    space_ids=[8, 22],
                ),
                SimpleNamespace(
                    enabled=True,
                    code="SA",
                    name="安全",
                    department_ids=[20],
                    space_ids=[8, 22],
                ),
            ]
        )
    )

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=22),
    ):
        domain = service._resolve_business_domain(config, selected_department)
        target = await service._resolve_target_space(identity)

    assert domain.code == expected_domain
    assert target.space.id == expected_space
    assert target.folder_id is None


@pytest.mark.asyncio
async def test_dynamic_space_ambiguity_maps_to_19904_before_lookup() -> None:
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    service = _service(_rule("fixed", "dynamic", "department_id"), repository)
    identity = SimpleNamespace(selected_department=_department(20, "动态部门", "/1/20/"))

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=DepartmentKnowledgeSpaceAmbiguousError()),
    ):
        with pytest.raises(FilelibSyncConflictError):
            await service._resolve_target_space(identity)

    repository.find_knowledge_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_dynamic_id_fails_before_temporary_upload() -> None:
    service = _service(_rule("dynamic", "dynamic", "department_id"))
    service._save_temporary_file = AsyncMock()
    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)

    with pytest.raises(FilelibSyncInvalidParamsError, match="department_id"):
        await service.sync(
            raw_params=json.dumps({"external_file_id": "ext-1", "file_name": "a.pdf"}),
            upload_file=upload,
        )

    service._save_temporary_file.assert_not_awaited()


def test_rule_and_token_id_are_not_accepted_from_request_params() -> None:
    params = _service(_rule()).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "token_id": 999,
                "business_domain_code": "SA",
                "knowledge_id": 999,
            }
        )
    )

    assert not hasattr(params, "token_id")
    assert not hasattr(params, "business_domain_code")
    assert not hasattr(params, "knowledge_id")
