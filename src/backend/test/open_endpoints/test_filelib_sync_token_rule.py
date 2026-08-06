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
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.open_endpoints.domain.models.filelib_department_mapping import FilelibDepartmentMapping
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


def _department(department_id: int, name: str, path: str | None = None, *, external_id: str | None = None) -> Department:
    return Department(
        id=department_id,
        dept_id=f"D-{department_id}",
        name=name,
        path=path or f"/{department_id}/",
        external_id=external_id,
    )


def _department_mapping(
    external_department_id: str,
    org_code: str,
    *,
    external_department_name: str | None = None,
) -> FilelibDepartmentMapping:
    return FilelibDepartmentMapping(
        id=1,
        external_department_id=external_department_id,
        external_department_name=external_department_name,
        org_code=org_code,
    )


def _mapping_repository(
    *,
    caller_department: Department,
    mapped_department: Department | None = None,
    mapping: FilelibDepartmentMapping | None = None,
    **extra: object,
) -> SimpleNamespace:
    repository = SimpleNamespace(
        find_user_by_id=AsyncMock(
            return_value=SimpleNamespace(user_id=1, user_name="caller", external_id="caller-ext"),
        ),
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=caller_department.id, is_primary=1)]),
        find_department_by_id=AsyncMock(
            side_effect=lambda department_id: caller_department if department_id == caller_department.id else mapped_department,
        ),
        find_department_mapping_by_external_department_id=AsyncMock(return_value=mapping),
        find_department_by_external_id=AsyncMock(return_value=mapped_department),
        **extra,
    )
    return repository


def _rule(
    business_domain_mode: str = "fixed",
    target_space_mode: str = "fixed",
    dynamic_source: str | None = None,
    *,
    business_domain_source: str | None = None,
    target_space_source: str | None = None,
) -> DeveloperTokenFileSyncRule:
    bd_source = business_domain_source
    if bd_source is None and dynamic_source and business_domain_mode == "dynamic":
        bd_source = dynamic_source
    ts_source = target_space_source
    if ts_source is None and dynamic_source and target_space_mode == "dynamic":
        ts_source = dynamic_source
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {
                "mode": business_domain_mode,
                "code": "IT" if business_domain_mode == "fixed" else None,
                "dynamic_source": bd_source if business_domain_mode == "dynamic" else None,
            },
            "target_space": {
                "mode": target_space_mode,
                "knowledge_id": 8 if target_space_mode == "fixed" else None,
                "dynamic_source": ts_source if target_space_mode == "dynamic" else None,
            },
        }
    )


def _service(rule, repository=None, knowledge_space_service=None) -> FilelibSyncService:
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
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


def test_responsible_person_satisfies_responsible_person_id_requirement() -> None:
    service = _service(_rule("dynamic", "fixed", "responsible_person_id"))
    params = service.parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "responsible_person": "gzx01",
            }
        )
    )

    service._require_dynamic_source_id(params)


@pytest.mark.asyncio
async def test_department_dynamic_source_selects_explicit_department() -> None:
    caller_department = _department(10, "调用人部门")
    selected_department = _department(20, "动态部门", external_id="ORG-20")
    mapping = _department_mapping("20", "ORG-20", external_department_name="动态部门")
    repository = _mapping_repository(
        caller_department=caller_department,
        mapped_department=selected_department,
        mapping=mapping,
    )
    params = _service(_rule()).parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": "20",
            }
        )
    )

    identity = await _service(
        _rule("dynamic", "dynamic", "department_id"),
        repository,
    )._resolve_identity(params)

    assert identity.main_department.id == 20
    assert identity.business_domain_department.id == 20
    assert identity.target_space_department.id == 20
    assert identity.responsible_user_id == 1
    repository.find_department_mapping_by_external_department_id.assert_awaited_once_with("20")
    repository.find_department_by_external_id.assert_awaited_once_with("ORG-20", tenant_id=5)


@pytest.mark.asyncio
async def test_responsible_person_requires_unique_primary_department() -> None:
    caller_department = _department(10, "调用人部门")
    repository = SimpleNamespace(
        find_users_by_external_id=AsyncMock(
            return_value=[SimpleNamespace(user_id=2, user_name="owner", external_id="owner-ext")],
        ),
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
                "responsible_person_id": "owner-ext",
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
    service = _service(_rule(domain_mode, space_mode, dynamic_source=source), repository)
    selected_department = _department(20, "动态部门", "/1/20/")
    identity = SimpleNamespace(
        business_domain_department=selected_department if domain_mode == "dynamic" else None,
        target_space_department=selected_department if space_mode == "dynamic" else None,
    )
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
        domain = service._resolve_business_domain(config, identity.business_domain_department)
        target = await service._resolve_target_space(identity)

    assert domain.code == expected_domain
    assert target.space.id == expected_space
    assert target.folder_id is None


@pytest.mark.asyncio
async def test_dynamic_space_ambiguity_falls_back_to_token_user_personal_space() -> None:
    personal_space = Knowledge(id=99, name="admin的知识库", type=3)
    fallback_folder = KnowledgeFile(id=5001, knowledge_id=99, file_name="leaf", file_type=0)
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    knowledge_space_service = SimpleNamespace(
        ensure_personal_default_space=AsyncMock(return_value=personal_space),
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=fallback_folder),
    )
    service = _service(_rule("fixed", "dynamic", "department_id"), repository, knowledge_space_service)
    service.token_name = "联调Token"
    identity = SimpleNamespace(
        target_space_department=_department(20, "动态部门", "/1/20/"),
        business_domain_department=None,
        main_department=_department(20, "动态部门", "/1/20/"),
        caller_department=_department(30, "绑定部门", "/1/30/"),
    )

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=DepartmentKnowledgeSpaceAmbiguousError()),
    ):
        target = await service._resolve_target_space(identity)

    assert target.used_personal_fallback is True
    assert target.space.id == 99
    assert target.folder_id == 5001
    repository.find_knowledge_by_id.assert_not_awaited()
    knowledge_space_service.ensure_personal_default_space.assert_awaited_once()
    knowledge_space_service.find_or_create_folder_path_for_file_sync.assert_awaited_once_with(
        99,
        "业务接口未分配/联调Token",
    )


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


def test_split_dynamic_sources_require_union_of_configured_ids() -> None:
    service = _service(
        _rule(
            "dynamic",
            "dynamic",
            business_domain_source="responsible_person_id",
            target_space_source="department_id",
        )
    )
    params = service.parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "responsible_person_id": "owner-ext",
            }
        )
    )

    with pytest.raises(FilelibSyncInvalidParamsError, match="department_id"):
        service._require_dynamic_source_id(params)


@pytest.mark.asyncio
async def test_split_dynamic_sources_resolve_independent_departments() -> None:
    caller_department = _department(10, "调用人部门")
    responsible_department = _department(30, "责任人部门")
    explicit_department = _department(20, "请求部门", external_id="ORG-20")
    mapping = _department_mapping("20", "ORG-20", external_department_name="请求部门")
    departments = {
        caller_department.id: caller_department,
        responsible_department.id: responsible_department,
        explicit_department.id: explicit_department,
    }
    repository = SimpleNamespace(
        find_users_by_external_id=AsyncMock(
            return_value=[SimpleNamespace(user_id=2, user_name="owner", external_id="owner-ext")],
        ),
        find_primary_departments=AsyncMock(
            side_effect=[
                [UserDepartment(user_id=1, department_id=10, is_primary=1)],
                [UserDepartment(user_id=2, department_id=30, is_primary=1)],
            ]
        ),
        find_department_by_id=AsyncMock(side_effect=lambda department_id: departments.get(department_id)),
        find_department_mapping_by_external_department_id=AsyncMock(return_value=mapping),
        find_department_by_external_id=AsyncMock(return_value=explicit_department),
    )
    service = _service(
        _rule(
            "dynamic",
            "dynamic",
            business_domain_source="responsible_person_id",
            target_space_source="department_id",
        ),
        repository,
    )
    params = service.parse_params(
        json.dumps(
            {
                "external_file_id": "ext-1",
                "file_name": "a.pdf",
                "department_id": "20",
                "responsible_person_id": "owner-ext",
            }
        )
    )

    identity = await service._resolve_identity(params)

    assert identity.business_domain_department.id == 30
    assert identity.target_space_department.id == 20


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
