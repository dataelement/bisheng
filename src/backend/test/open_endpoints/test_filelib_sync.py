import json
import subprocess
import sys
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.filelib_sync import (
    FilelibSyncConflictError,
    FilelibSyncInvalidParamsError,
    FilelibSyncNotFoundError,
)
from bisheng.common.errcode.knowledge_space import DepartmentKnowledgeSpaceAmbiguousError
from bisheng.database.models.department import Department, UserDepartment
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.open_endpoints.api.dependencies import get_filelib_sync_service
from bisheng.open_endpoints.api.endpoints.filelib_sync import _sync_file, router
from bisheng.open_endpoints.domain.schemas.filelib_sync import (
    FilelibSyncParams,
    FilelibSyncResponseData,
)
from bisheng.knowledge.domain.services.department_space_target_resolver import (
    DepartmentSpaceTargetKind,
)
from bisheng.open_endpoints.domain.services.filelib_sync_service import (
    FilelibSyncService,
    ResolvedFileSyncTarget,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import PortalDomainConfig


def _department(department_id: int, name: str, path: str) -> Department:
    return Department(
        id=department_id,
        dept_id=f"D-{department_id}",
        name=name,
        path=path,
    )


def _rule() -> DeveloperTokenFileSyncRule:
    return DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {"mode": "fixed", "knowledge_id": 8},
            "dynamic_source": None,
        }
    )


def _service(repository=None, knowledge_space_service=None) -> FilelibSyncService:
    login_user = UserPayload(
        user_id=1,
        user_name="caller",
        user_role=[2],
        tenant_id=1,
    )
    return FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=login_user,
        token_id=42,
        file_sync_rule=_rule(),
        repository=repository or SimpleNamespace(),
        knowledge_space_service=knowledge_space_service or SimpleNamespace(),
    )


def test_only_unified_sync_route_is_registered():
    old_codes = {"03", "04", "05", "06", "07", "09", "10", "11", "12", "14", "15"}
    paths = {route.path for route in router.routes}
    assert "/filelib/file/sync" in paths
    assert not {f"/filelib/file/sync/{code}" for code in old_codes} & paths


def test_static_numbered_rules_are_removed_from_runtime_schema():
    from bisheng.open_endpoints.domain.schemas import filelib_sync

    assert not hasattr(filelib_sync, "FILELIB_SYNC_RULES")


@pytest.mark.parametrize(
    ("raw_params", "message"),
    [
        ("not-json", "params must be valid JSON"),
        ("[]", "params must be a JSON object"),
        ('{"file_name":"a.pdf"}', "external_file_id must not be empty"),
        ('{"external_file_id":"x"}', "file_name must not be empty"),
    ],
)
def test_parse_params_rejects_invalid_payload(raw_params, message):
    with pytest.raises(FilelibSyncInvalidParamsError, match=message):
        FilelibSyncService.parse_params(raw_params)


def test_parse_params_normalizes_string_ids():
    params = FilelibSyncService.parse_params(
        json.dumps(
            {
                "external_file_id": " ext-1 ",
                "file_name": " report.pdf ",
                "department_id": "12",
                "responsible_person_id": "34",
            }
        )
    )
    assert params.external_file_id == "ext-1"
    assert params.file_name == "report.pdf"
    assert params.department_id == "12"
    assert params.responsible_person_id == "34"


def test_portal_domain_config_preserves_department_bindings():
    domain = PortalDomainConfig(
        name="信息",
        code="it",
        space_ids=[8, 8],
        department_ids=[3, 3, 5],
        color="#000",
        bg="#fff",
        icon="Info",
    )
    assert domain.code == "IT"
    assert domain.space_ids == [8, 8]
    assert domain.department_ids == [3, 5]


async def test_unknown_responsible_external_id_is_rejected():
    caller_department = _department(10, "调用人部门", "/10/")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
        find_users_by_external_id=AsyncMock(return_value=[]),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        responsible_person="someone-else",
    )
    with pytest.raises(FilelibSyncNotFoundError, match="responsible person does not exist"):
        await _service(repository)._resolve_identity(params)


async def test_responsible_person_resolves_user_by_external_id():
    caller_department = _department(10, "调用人部门", "/10/")
    responsible_department = _department(20, "责任部门", "/20/")
    responsible_user = SimpleNamespace(user_id=2, user_name="owner", external_id="gzx01")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(
            side_effect=[
                [UserDepartment(user_id=1, department_id=10, is_primary=1)],
                [UserDepartment(user_id=2, department_id=20, is_primary=1)],
            ]
        ),
        find_department_by_id=AsyncMock(
            side_effect=lambda department_id: caller_department if department_id == 10 else responsible_department,
        ),
        find_users_by_external_id=AsyncMock(return_value=[responsible_user]),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        responsible_person="gzx01",
    )
    identity = await _service(repository)._resolve_identity(params)
    assert identity.responsible_user_id == 2
    assert identity.responsible_user_external_id == "gzx01"
    assert identity.main_department.id == 20
    assert identity.main_department.name == "责任部门"
    repository.find_users_by_external_id.assert_awaited_once_with("gzx01", tenant_id=1)


async def test_responsible_person_id_must_match_external_id():
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        responsible_person_id="gzx01",
        responsible_person="other-id",
    )
    with pytest.raises(FilelibSyncInvalidParamsError, match="responsible_person does not match"):
        FilelibSyncService._resolve_responsible_external_id(params)


async def test_responsible_person_id_resolves_user_by_external_id():
    caller_department = _department(10, "调用人部门", "/10/")
    responsible_department = _department(20, "责任部门", "/20/")
    responsible_user = SimpleNamespace(user_id=2, user_name="owner", external_id="gzx01")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(
            side_effect=[
                [UserDepartment(user_id=1, department_id=10, is_primary=1)],
                [UserDepartment(user_id=2, department_id=20, is_primary=1)],
            ]
        ),
        find_department_by_id=AsyncMock(
            side_effect=lambda department_id: caller_department if department_id == 10 else responsible_department,
        ),
        find_users_by_external_id=AsyncMock(return_value=[responsible_user]),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        responsible_person_id="gzx01",
    )
    identity = await _service(repository)._resolve_identity(params)
    assert identity.responsible_user_id == 2
    assert identity.responsible_user_external_id == "gzx01"
    repository.find_users_by_external_id.assert_awaited_once_with("gzx01", tenant_id=1)


async def test_main_department_name_without_id_must_match_caller_department():
    caller_department = _department(10, "调用人部门", "/10/")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
        find_user_by_id=AsyncMock(
            return_value=SimpleNamespace(user_id=1, user_name="caller", external_id="caller-ext"),
        ),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        department="其他部门",
    )
    with pytest.raises(FilelibSyncInvalidParamsError, match="department does not match"):
        await _service(repository)._resolve_identity(params)


def test_department_chain_starts_at_self_and_walks_to_root():
    department = _department(3, "三级部门", "/1/2/3/")
    assert FilelibSyncService._department_chain(department) == [3, 2, 1]


async def test_department_binding_is_selected():
    department = _department(3, "三级部门", "/1/2/3/")
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=Knowledge(id=22, name="三级部门库", type=3)),
    )
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=22),
    ) as resolve:
        space = await _service(repository)._find_department_space(
            department,
            dynamic_source="department_id",
        )
    assert space.id == 22
    resolve.assert_awaited_once_with(
        [3, 2, 1],
        kind=DepartmentSpaceTargetKind.DEPARTMENT,
        allow_legacy=False,
    )


async def test_clinic_binding_is_selected_for_responsible_person_dynamic_source():
    department = _department(3, "三级科室", "/1/2/3/")
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=Knowledge(id=33, name="三级科室库", type=3)),
    )
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=33),
    ) as resolve:
        space = await _service(repository)._find_department_space(
            department,
            dynamic_source="responsible_person_id",
        )
    assert space.id == 33
    resolve.assert_awaited_once_with(
        [3],
        kind=DepartmentSpaceTargetKind.CLINIC,
        allow_legacy=False,
    )


async def test_responsible_person_target_space_falls_back_to_nearest_department_library():
    department = _department(3, "三级科室", "/1/2/3/")
    department_space = Knowledge(id=22, name="二级部门库", type=3)
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=department_space),
    )
    resolve = AsyncMock(side_effect=[None, 22])
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=resolve,
    ):
        space = await _service(repository)._find_department_space(
            department,
            dynamic_source="responsible_person_id",
        )
    assert space.id == 22
    assert resolve.await_args_list == [
        call([3], kind=DepartmentSpaceTargetKind.CLINIC, allow_legacy=False),
        call([3, 2, 1], kind=DepartmentSpaceTargetKind.DEPARTMENT, allow_legacy=False),
    ]


async def test_responsible_person_target_space_prefers_clinic_before_department_walk():
    department = _department(3, "三级科室", "/1/2/3/")
    clinic_space = Knowledge(id=33, name="三级科室库", type=3)
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=clinic_space),
    )
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=33),
    ) as resolve:
        space = await _service(repository)._find_department_space(
            department,
            dynamic_source="responsible_person_id",
        )
    assert space.id == 33
    resolve.assert_awaited_once_with(
        [3],
        kind=DepartmentSpaceTargetKind.CLINIC,
        allow_legacy=False,
    )


async def test_responsible_person_target_space_picks_first_clinic_when_ambiguous():
    department = _department(3, "三级科室", "/1/2/3/")
    clinic_space = Knowledge(id=100, name="科室库A", type=3)
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=clinic_space),
    )
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(
            side_effect=DepartmentKnowledgeSpaceAmbiguousError(
                department_id=3,
                candidate_space_ids=[101, 100],
            ),
        ),
    ) as resolve:
        space = await _service(repository)._find_department_space(
            department,
            dynamic_source="responsible_person_id",
        )
    assert space.id == 100
    resolve.assert_awaited_once_with(
        [3],
        kind=DepartmentSpaceTargetKind.CLINIC,
        allow_legacy=False,
    )
    repository.find_knowledge_by_id.assert_awaited_once_with(100)


async def test_responsible_person_target_space_raises_when_clinic_and_department_missing():
    department = _department(3, "三级科室", "/1/2/3/")
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=None),
    ) as resolve:
        with pytest.raises(FilelibSyncNotFoundError, match="不存在知识库"):
            await _service(repository)._find_department_space(
                department,
                dynamic_source="responsible_person_id",
            )
    assert resolve.await_args_list == [
        call([3], kind=DepartmentSpaceTargetKind.CLINIC, allow_legacy=False),
        call([3, 2, 1], kind=DepartmentSpaceTargetKind.DEPARTMENT, allow_legacy=False),
    ]


async def test_nearest_department_binding_is_selected():
    department = _department(3, "三级部门", "/1/2/3/")
    repository = SimpleNamespace(
        find_knowledge_by_id=AsyncMock(return_value=Knowledge(id=22, name="二级部门库", type=3)),
    )
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=22),
    ) as resolve:
        space = await _service(repository)._find_nearest_department_space(department)
    assert space.id == 22
    resolve.assert_awaited_once_with(
        [3, 2, 1],
        kind=DepartmentSpaceTargetKind.DEPARTMENT,
        allow_legacy=False,
    )


async def test_ambiguous_department_binding_is_rejected_before_space_lookup():
    department = _department(3, "三级部门", "/1/2/3/")
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=DepartmentKnowledgeSpaceAmbiguousError()),
    ):
        with pytest.raises(FilelibSyncConflictError, match="multiple target"):
            await _service(repository)._find_department_space(
                department,
                dynamic_source="department_id",
            )

    repository.find_knowledge_by_id.assert_not_awaited()


async def test_nearest_ambiguous_department_binding_is_rejected_before_space_lookup():
    department = _department(3, "三级部门", "/1/2/3/")
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=DepartmentKnowledgeSpaceAmbiguousError()),
    ):
        with pytest.raises(FilelibSyncConflictError, match="multiple target"):
            await _service(repository)._find_nearest_department_space(department)

    repository.find_knowledge_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_target_space_falls_back_to_token_user_personal_space():
    personal_space = Knowledge(id=99, name="admin的知识库", type=3)
    fallback_folder = KnowledgeFile(id=5001, knowledge_id=99, file_name="leaf", file_type=0)
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock(return_value=None))
    knowledge_space_service = SimpleNamespace(
        ensure_personal_default_space=AsyncMock(return_value=personal_space),
        find_or_create_folder_path_for_file_sync=AsyncMock(return_value=fallback_folder),
    )
    service = _service(repository, knowledge_space_service)
    service.token_name = "联调Token"
    service.file_sync_rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {
                "mode": "fixed",
                "knowledge_id": 118,
                "folder_mode": "fixed",
                "folder_path": "政策文件/管理制度",
            },
        }
    )
    identity = SimpleNamespace(
        target_space_department=None,
        main_department=SimpleNamespace(id=1, name="同步部门"),
        caller_department=SimpleNamespace(id=2, name="绑定用户主责部门"),
    )

    target = await service._resolve_target_space(identity)

    assert target.used_personal_fallback is True
    assert target.space.id == 99
    assert target.folder_id == 5001
    knowledge_space_service.ensure_personal_default_space.assert_awaited_once()
    knowledge_space_service.find_or_create_folder_path_for_file_sync.assert_awaited_once_with(
        99,
        "业务接口未分配/联调Token/政策文件/管理制度",
    )


def test_build_personal_fallback_folder_path_uses_token_name_and_configured_target_path():
    service = _service()
    service.token_name = "联调Token"
    service.file_sync_rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "IT"},
            "target_space": {
                "mode": "fixed",
                "knowledge_id": 118,
                "folder_mode": "dynamic",
                "parent_folder_path": "政策文件",
                "folder_dynamic_source": "department_name",
            },
        }
    )
    identity = SimpleNamespace(
        main_department=SimpleNamespace(id=20, name="同步部门"),
        caller_department=SimpleNamespace(id=30, name="绑定用户主责部门"),
    )

    assert service.build_personal_fallback_folder_path(identity) == (
        "业务接口未分配/联调Token/政策文件/同步部门"
    )


def test_developer_token_display_name_uses_token_name_or_fallback_id():
    service = _service()
    assert service._developer_token_display_name() == "token-42"

    service.token_name = "联调Token"
    assert service._developer_token_display_name() == "联调Token"


def test_unbound_business_domain_is_rejected():
    space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["PP"])
    domain = SimpleNamespace(code="IT", name="信息", space_ids=[8])
    with pytest.raises(FilelibSyncNotFoundError, match="信息库不存在信息"):
        FilelibSyncService._ensure_domain_bound(space, domain)


def test_business_domain_requires_portal_space_and_code_bindings():
    space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"])
    domain = SimpleNamespace(code="IT", name="信息", space_ids=[9])
    with pytest.raises(FilelibSyncNotFoundError, match="信息库不存在信息"):
        FilelibSyncService._ensure_domain_bound(space, domain)

    domain.space_ids = [8]
    FilelibSyncService._ensure_domain_bound(space, domain)


async def test_fixed_encoding_uses_space_month_sequence_without_llm():
    knowledge_file = KnowledgeFile(
        id=99,
        knowledge_id=8,
        file_name="a.pdf",
        create_time=datetime(2026, 7, 16, 8, 0, 0),
    )
    with (
        patch(
            "bisheng.knowledge.rag.pipeline.transformer.file_encoding.bisheng_settings.aget_shougang_conf",
            new=AsyncMock(return_value=SimpleNamespace(prefix="SGGF")),
        ),
        patch.object(
            FileEncodingTransformer,
            "_compute_seq",
            new=AsyncMock(return_value=7),
        ),
    ):
        encoding = await FileEncodingTransformer.generate_fixed_encoding(
            invoke_user_id=1,
            knowledge_file=knowledge_file,
            document_type_code="POL",
            business_domain_code="IT",
        )
    assert encoding == "SGGF-POL-IT-20260700000007"


def test_regular_upload_keeps_enqueue_processing_enabled_by_default():
    default = (
        KnowledgeSpaceService.add_file.__signature__
        if hasattr(KnowledgeSpaceService.add_file, "__signature__")
        else None
    )
    if default is None:
        import inspect

        default = inspect.signature(KnowledgeSpaceService.add_file)
    assert default.parameters["enqueue_processing"].default is True


async def test_missing_multipart_fields_returns_actual_422():
    response = await _sync_file(
        file=None,
        params=None,
        service=SimpleNamespace(),
    )
    body = json.loads(response.body)
    assert response.status_code == 422
    assert body["status_code"] == 422
    assert body["data"]["error_code"] == 19905


async def test_missing_params_closes_uploaded_file():
    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    response = await _sync_file(
        file=upload,
        params=None,
        service=SimpleNamespace(),
    )
    assert response.status_code == 422
    assert upload.file.closed


def test_production_router_reaches_sync_handler_for_missing_params():
    script = """
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.api.router import router_rpc
from bisheng.open_endpoints.api.dependencies import get_filelib_sync_service

app = FastAPI()
app.include_router(router_rpc)
app.dependency_overrides[get_filelib_sync_service] = lambda: SimpleNamespace()
with TestClient(app) as client:
    response = client.post(
        "/api/v2/filelib/file/sync",
        files={"file": ("a.pdf", b"content", "application/pdf")},
    )
print("ROUTE_RESULT=" + json.dumps({"status_code": response.status_code, "body": response.json()}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result_line = next(line for line in completed.stdout.splitlines() if line.startswith("ROUTE_RESULT="))
    result = json.loads(result_line.removeprefix("ROUTE_RESULT="))
    assert result["status_code"] == 422
    assert result["body"]["data"]["error_code"] == 19905


@pytest.mark.parametrize("code", ["03", "04", "05", "06", "07", "09", "10", "11", "12", "14", "15"])
def test_numbered_routes_return_404_without_calling_service(code):
    service = SimpleNamespace(sync=AsyncMock())
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.dependency_overrides[get_filelib_sync_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v2/filelib/file/sync/{code}",
            files={
                "file": ("a.pdf", b"content", "application/pdf"),
                "params": (None, '{"external_file_id":"ext-1","file_name":"a.pdf"}'),
            },
        )

    assert response.status_code == 404
    service.sync.assert_not_awaited()


async def test_sync_endpoint_returns_success_payload_and_closes_file():
    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    result = FilelibSyncResponseData(
        external_file_id="ext-1",
        file_id=9,
        file_encoding="SGGF-POL-IT-20260700000001",
        knowledge_id=8,
        knowledge_name="信息库",
        status=5,
    )
    service = SimpleNamespace(sync=AsyncMock(return_value=result))
    response = await _sync_file(
        file=upload,
        params='{"external_file_id":"ext-1","file_name":"a.pdf"}',
        service=service,
    )
    assert response.status_code == 200
    assert response.data.file_encoding == result.file_encoding
    assert upload.file.closed


async def test_sync_endpoint_returns_actual_business_http_status():
    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    service = SimpleNamespace(sync=AsyncMock(side_effect=FilelibSyncNotFoundError(msg="knowledge space not found")))
    response = await _sync_file(
        file=upload,
        params='{"external_file_id":"ext-1","file_name":"a.pdf"}',
        service=service,
    )
    body = json.loads(response.body)
    assert response.status_code == 404
    assert body == {
        "status_code": 404,
        "status_message": "knowledge space not found",
        "data": {"error_code": 19903},
    }


async def test_sync_orchestration_allows_repeated_external_id_and_writes_source_metadata():
    repository = SimpleNamespace(
        find_by_id=AsyncMock(),
        update=AsyncMock(),
    )
    knowledge_space_service = SimpleNamespace(
        get_preview_cache_key=Mock(return_value="cache-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=9, status=5)]),
        enqueue_file_title_extraction=AsyncMock(),
    )
    events = Mock()
    events.attach_mock(knowledge_space_service.enqueue_file_title_extraction, "enqueue")
    service = _service(repository, knowledge_space_service)
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_user_external_id="owner-ext",
        responsible_department=_department(20, "责任人部门", "/20/"),
        main_department=_department(10, "主责单位", "/10/"),
        business_domain_department=None,
        target_space_department=None,
        selected_department=None,
    )
    category = SimpleNamespace(code="POL")
    subcategory = SimpleNamespace(code="POL-MGMT")
    domain = SimpleNamespace(code="IT", name="信息", space_ids=[8])
    target_space = Knowledge(
        id=8,
        name="信息库",
        type=3,
        business_domain_codes=["IT"],
    )
    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="a.pdf",
        status=5,
        create_time=datetime(2026, 7, 16),
    )
    repository.find_by_id = AsyncMock(return_value=knowledge_file)

    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(category, subcategory))
    service._resolve_business_domain = Mock(return_value=domain)
    service._resolve_target_space = AsyncMock(return_value=ResolvedFileSyncTarget(space=target_space, folder_id=None))
    service._ensure_domain_bound = Mock()
    service._require_upload_permission = AsyncMock()
    service._save_temporary_file = AsyncMock(return_value="temporary-url")
    service._resolve_same_name_version_overwrite = AsyncMock(return_value=(None, None))

    async def _generate_fixed_encoding(**kwargs):
        kwargs["knowledge_file"].file_encoding = "SGGF-POL-IT-20260700000001"
        return kwargs["knowledge_file"].file_encoding

    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    with (
        patch.object(
            FileEncodingTransformer,
            "generate_fixed_encoding",
            side_effect=_generate_fixed_encoding,
        ),
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ) as persist_update,
    ):
        result = await service.sync(
            raw_params='{"external_file_id":"ext-1","file_name":"a.pdf"}',
            upload_file=upload,
        )
        repeated_result = await service.sync(
            raw_params='{"external_file_id":"ext-1","file_name":"a.pdf"}',
            upload_file=UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7),
        )

    assert knowledge_file.user_metadata == {
        "external_file_id": "ext-1",
        "department": "主责单位",
        "department_id": 10,
        "responsible_person": "owner-ext",
        "responsible_person_id": 2,
        "filelib_sync_endpoint": "sync",
        "developer_token_id": 42,
        "developer_token_name": "token-42",
    }
    assert knowledge_file.user_id == 2
    assert knowledge_file.user_name == "owner"
    assert knowledge_file.updater_id == 2
    assert knowledge_file.updater_name == "owner"
    assert knowledge_file.original_uploader_id == 2
    service._ensure_domain_bound.assert_not_called()
    assert persist_update.call_count == 2
    assert knowledge_space_service.add_file.await_count == 2
    assert knowledge_space_service.enqueue_file_title_extraction.await_count == 2
    add_kwargs = knowledge_space_service.add_file.await_args_list[0].kwargs
    assert add_kwargs == {
        "knowledge_id": 8,
        "file_path": ["temporary-url"],
        "parent_id": None,
        "file_category_code": "POLICY",
        "file_subcategory_code": "MGMT_POLICY",
        "business_domain_code": "IT",
        "skip_approval": True,
        "enqueue_processing": False,
        "allow_duplicate_name": True,
        "allow_duplicate_content": True,
        "skip_space_business_domain_check": True,
    }
    assert persist_update.call_args_list == [call(knowledge_file), call(knowledge_file)]
    assert events.method_calls == [
        call.enqueue(
            [knowledge_file],
            ["cache-key"],
            operator_user_id=1,
            operator_is_global_super=False,
        ),
        call.enqueue(
            [knowledge_file],
            ["cache-key"],
            operator_user_id=1,
            operator_is_global_super=False,
        ),
    ]
    assert "token_id" not in knowledge_file.user_metadata
    assert result.file_encoding == "SGGF-POL-IT-20260700000001"
    assert repeated_result.external_file_id == "ext-1"


@pytest.mark.asyncio
async def test_sync_orchestration_skips_business_domain_when_dynamic_resolution_is_empty():
    repository = SimpleNamespace(find_by_id=AsyncMock(), update=AsyncMock())
    knowledge_space_service = SimpleNamespace(
        get_preview_cache_key=Mock(return_value="cache-key"),
        add_file=AsyncMock(return_value=[SimpleNamespace(id=9, status=5)]),
        enqueue_file_title_extraction=AsyncMock(),
    )
    service = _service(repository, knowledge_space_service)
    service.file_sync_rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POL", "subcategory_code": "POL01"},
            "business_domain": {"mode": "dynamic", "code": None, "dynamic_source": "department_id"},
            "target_space": {"mode": "fixed", "knowledge_id": 8},
        }
    )
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_user_external_id="owner-ext",
        responsible_department=_department(20, "责任人部门", "/20/"),
        main_department=_department(10, "主责单位", "/10/"),
        business_domain_department=_department(10, "主责单位", "/10/"),
        target_space_department=None,
    )
    target_space = Knowledge(id=8, name="信息库", type=3, business_domain_codes=["IT"])
    knowledge_file = KnowledgeFile(
        id=9,
        knowledge_id=8,
        file_name="a.pdf",
        status=5,
        create_time=datetime(2026, 7, 16),
    )
    repository.find_by_id = AsyncMock(return_value=knowledge_file)

    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(SimpleNamespace(code="POL"), SimpleNamespace(code="POL01")))
    service._resolve_business_domain = Mock(return_value=None)
    service._resolve_target_space = AsyncMock(return_value=ResolvedFileSyncTarget(space=target_space, folder_id=None))
    service._ensure_domain_bound = Mock()
    service._require_upload_permission = AsyncMock()
    service._save_temporary_file = AsyncMock(return_value="temporary-url")
    service._resolve_same_name_version_overwrite = AsyncMock(return_value=(None, None))

    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    with (
        patch.object(FileEncodingTransformer, "generate_fixed_encoding", AsyncMock()) as generate_encoding,
        patch(
            "bisheng.open_endpoints.domain.services.filelib_sync_service.KnowledgeFileDao.update",
            side_effect=lambda value: value,
        ),
    ):
        await service.sync(
            raw_params='{"external_file_id":"ext-1","file_name":"a.pdf","department_id":"A0311"}',
            upload_file=upload,
        )

    service._ensure_domain_bound.assert_not_called()
    generate_encoding.assert_not_awaited()
    add_kwargs = knowledge_space_service.add_file.await_args.kwargs
    assert add_kwargs["business_domain_code"] is None
    assert add_kwargs["skip_space_business_domain_check"] is True


def test_external_file_id_is_not_reserved_by_sync_service():
    assert not hasattr(FilelibSyncService, "_reserve_external_file_id")
