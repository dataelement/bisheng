import json
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
    assert params.department_id == 12
    assert params.responsible_person_id == 34


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


def test_department_chain_starts_at_self_and_walks_to_root():
    department = _department(3, "三级部门", "/1/2/3/")
    assert FilelibSyncService._department_chain(department) == [3, 2, 1]


async def test_other_responsible_name_without_id_is_rejected():
    caller_department = _department(10, "调用人部门", "/10/")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        responsible_person="someone-else",
    )
    with pytest.raises(FilelibSyncInvalidParamsError, match="responsible_person does not match"):
        await _service(repository)._resolve_identity(params)


async def test_main_department_name_without_id_must_match_caller_department():
    caller_department = _department(10, "调用人部门", "/10/")
    repository = SimpleNamespace(
        find_primary_departments=AsyncMock(return_value=[UserDepartment(user_id=1, department_id=10, is_primary=1)]),
        find_department_by_id=AsyncMock(return_value=caller_department),
    )
    params = FilelibSyncParams(
        external_file_id="ext-1",
        file_name="a.pdf",
        department="其他部门",
    )
    with pytest.raises(FilelibSyncInvalidParamsError, match="department does not match"):
        await _service(repository)._resolve_identity(params)


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
    resolve.assert_awaited_once_with([3, 2, 1])


async def test_ambiguous_department_binding_is_rejected_before_space_lookup():
    department = _department(3, "三级部门", "/1/2/3/")
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=DepartmentKnowledgeSpaceAmbiguousError()),
    ):
        with pytest.raises(FilelibSyncConflictError, match="multiple target"):
            await _service(repository)._find_nearest_department_space(department)

    repository.find_knowledge_by_id.assert_not_awaited()


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


def test_fastapi_route_returns_actual_422_for_missing_params():
    app = FastAPI()
    app.include_router(router, prefix="/api/v2")
    app.dependency_overrides[get_filelib_sync_service] = lambda: SimpleNamespace()
    with TestClient(app) as client:
        response = client.post(
            "/api/v2/filelib/file/sync",
            files={"file": ("a.pdf", b"content", "application/pdf")},
        )
    assert response.status_code == 422
    assert response.json()["data"]["error_code"] == 19905


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
        enqueue_file_processing=Mock(),
    )
    events = Mock()
    events.attach_mock(repository.update, "persist")
    events.attach_mock(knowledge_space_service.enqueue_file_processing, "enqueue")
    service = _service(repository, knowledge_space_service)
    identity = SimpleNamespace(
        responsible_user_id=2,
        responsible_user_name="owner",
        responsible_department=_department(20, "责任人部门", "/20/"),
        main_department=_department(10, "主责单位", "/10/"),
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
    repository.find_by_id.return_value = knowledge_file
    repository.update.side_effect = lambda value: value

    service._resolve_identity = AsyncMock(return_value=identity)
    service._get_portal_config = AsyncMock(return_value=SimpleNamespace())
    service._resolve_document_type = Mock(return_value=(category, subcategory))
    service._resolve_business_domain = Mock(return_value=domain)
    service._resolve_target_space = AsyncMock(
        return_value=ResolvedFileSyncTarget(space=target_space, folder_id=None)
    )
    service._ensure_domain_bound = Mock()
    service._require_upload_permission = AsyncMock()
    service._save_temporary_file = AsyncMock(return_value="temporary-url")

    async def _generate_fixed_encoding(**kwargs):
        kwargs["knowledge_file"].file_encoding = "SGGF-POL-IT-20260700000001"
        return kwargs["knowledge_file"].file_encoding

    upload = UploadFile(filename="a.pdf", file=BytesIO(b"content"), size=7)
    with patch.object(
        FileEncodingTransformer,
        "generate_fixed_encoding",
        side_effect=_generate_fixed_encoding,
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
        "responsible_person": "owner",
        "responsible_person_id": 2,
        "filelib_sync_endpoint": "sync",
    }
    assert repository.update.await_count == 2
    assert knowledge_space_service.add_file.await_count == 2
    assert knowledge_space_service.enqueue_file_processing.call_count == 2
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
    }
    assert events.method_calls == [
        call.persist(knowledge_file),
        call.enqueue([knowledge_file], ["cache-key"]),
        call.persist(knowledge_file),
        call.enqueue([knowledge_file], ["cache-key"]),
    ]
    assert "token_id" not in knowledge_file.user_metadata
    assert result.file_encoding == "SGGF-POL-IT-20260700000001"
    assert repeated_result.external_file_id == "ext-1"


def test_external_file_id_is_not_reserved_by_sync_service():
    assert not hasattr(FilelibSyncService, "_reserve_external_file_id")
