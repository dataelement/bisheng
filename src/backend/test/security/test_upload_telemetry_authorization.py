"""Focused regressions for authenticated, owned uploads and telemetry enums."""

from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

from bisheng.api.v1 import endpoints
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.cache import utils
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.api.endpoints import knowledge
from bisheng.knowledge.domain.services.preview_source_service import PreviewSourceService
from bisheng.permission.application import business_authorization
from bisheng.telemetry_search.api.endpoints import dashboard as dashboard_api
from bisheng.telemetry_search.domain.services import dashboard


@pytest.fixture(autouse=True)
def upload_tenant(monkeypatch):
    from bisheng.common.services.config_service import ConfigService

    monkeypatch.setattr(ConfigService, "get_from_db", lambda *args, **kwargs: {})
    token = current_tenant_id.set(7)
    yield
    current_tenant_id.reset(token)


def upload(name="invoice.png", content=b"first"):
    return UploadFile(filename=name, file=BytesIO(content), size=len(content))


@pytest.fixture
def object_store(monkeypatch, tmp_path):
    objects = {}

    async def put(*, object_name, file):
        objects[object_name] = file.read()

    async def link(name, bucket, **kwargs):
        return f"https://storage.example/{bucket}/{name}"

    storage = SimpleNamespace(tmp_bucket="tmp", put_object_tmp=AsyncMock(side_effect=put), get_share_link=link)
    monkeypatch.setattr(utils, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr("bisheng.core.storage.minio.minio_manager.get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(knowledge, "get_minio_storage", AsyncMock(return_value=storage))
    from bisheng.knowledge.domain.services import preview_source_service

    monkeypatch.setattr(
        preview_source_service, "get_redis_client", AsyncMock(return_value=SimpleNamespace(aset=AsyncMock()))
    )
    monkeypatch.setattr(utils, "CACHE_DIR", str(tmp_path / "cache"))
    return objects, storage


@pytest.fixture
def upload_permissions(monkeypatch):
    check = AsyncMock(return_value=True)
    require = AsyncMock()
    monkeypatch.setattr(business_authorization, "check_business_action", check)
    monkeypatch.setattr(business_authorization, "require_business_action", require)
    monkeypatch.setattr(PreviewSourceService, "issue", AsyncMock(return_value="owned-reference"))
    return check, require


@pytest.mark.parametrize("path", ["/upload/flow-1", "/knowledge/upload"])
def test_upload_routes_require_login(path, monkeypatch):
    async def no_login():
        raise HTTPException(status_code=401)

    app = FastAPI()
    app.include_router(endpoints.router)
    app.include_router(knowledge.router)
    app.dependency_overrides[UserPayload.get_login_user] = no_login
    store = AsyncMock()
    monkeypatch.setattr(endpoints, "save_uploaded_file", store)
    monkeypatch.setattr(knowledge, "save_uploaded_file", store)
    with TestClient(app) as client:
        response = client.post(path, files={"file": ("invoice.png", b"data")})
    assert response.status_code == 401
    store.assert_not_awaited()


@pytest.mark.parametrize("flow_id", ["..", "../escape", "/tmp/escape", "%2e%2e", "a\\b", "a/b"])
async def test_upload_rejects_path_flow_id_before_storage(flow_id, upload_permissions, object_store):
    file = upload()
    with pytest.raises(HTTPException) as error:
        await endpoints.create_upload_file(file, flow_id, UserPayload.model_construct(user_id=8, tenant_id=7))
    assert error.value.status_code == 422
    assert not object_store[0]
    assert file.file.closed
    upload_permissions[0].assert_not_awaited()


async def test_same_filename_uploads_do_not_replace_first_object(upload_permissions, object_store):
    first = await endpoints.create_upload_file(upload(), "flow-1", UserPayload.model_construct(user_id=8, tenant_id=7))
    second = await endpoints.create_upload_file(
        upload(content=b"replacement"), "flow-2", UserPayload.model_construct(user_id=9, tenant_id=7)
    )
    third = await endpoints.create_upload_file(
        upload(content=b"third"), "flow-1", UserPayload.model_construct(user_id=8, tenant_id=7)
    )
    assert len(object_store[0]) == 3
    assert first.data.file_path != second.data.file_path != third.data.file_path
    assert first.data.file_path.endswith(".png")
    first_key = first.data.file_path.split("/tmp/", 1)[1]
    assert first_key.startswith("uploads/7/8/")
    assert object_store[0][first_key] == b"first"
    assert first.data.preview_upload_ref == "owned-reference"


async def test_builder_upload_uses_edit_if_not_runtime_user(upload_permissions, object_store):
    check, require = upload_permissions
    check.return_value = False
    await endpoints.create_upload_file(upload(), "flow-1", UserPayload.model_construct(user_id=8, tenant_id=7))
    assert check.await_args.kwargs["action"] == "visible"
    assert require.await_args.kwargs == {"resource_type": "workflow", "resource_id": "flow-1", "action": "edit"}


async def test_no_workflow_permission_does_not_upload(upload_permissions, object_store):
    check, require = upload_permissions
    check.return_value = False
    require.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await endpoints.create_upload_file(upload(), "flow-1", UserPayload.model_construct(user_id=8, tenant_id=7))
    assert not object_store[0]


async def test_upload_tenant_mismatch_does_not_upload(upload_permissions, object_store):
    with pytest.raises(HTTPException) as error:
        await endpoints.create_upload_file(upload(), "flow-1", UserPayload.model_construct(user_id=8, tenant_id=9))
    assert error.value.status_code == 403
    assert not object_store[0]


@pytest.mark.parametrize("folder", ["../../escape", "/tmp/outside"])
async def test_upload_helper_rejects_directory_escape(folder, object_store):
    with pytest.raises(ValueError):
        await utils.save_uploaded_file(upload(), folder, "invoice.png")
    assert not object_store[0]


@pytest.mark.parametrize("name", ["../invoice.png", "/invoice.png", "a\\b", "%252e%252e/x", "a/./b"])
async def test_upload_helper_rejects_object_path_escape(name, object_store):
    with pytest.raises(ValueError):
        await utils.save_uploaded_file(upload(), "bisheng", name)
    assert not object_store[0]


async def test_helper_keeps_server_selected_preview_and_openapi_keys(object_store):
    for key in ["preview-uuid.pdf", "open-api/service-account/7/customer/uuid.pdf"]:
        link = await utils.save_uploaded_file(upload(), "bisheng", key)
        assert link.endswith(key)
        assert object_store[0][key] == b"first"


async def test_generic_knowledge_upload_is_owned(monkeypatch, object_store):
    monkeypatch.setattr(knowledge, "generate_uuid", lambda: "uuid")
    issue = AsyncMock(return_value="owned-reference")
    monkeypatch.setattr(PreviewSourceService, "issue", issue)
    result = await knowledge.upload_file(file=upload(), login_user=UserPayload.model_construct(user_id=8, tenant_id=7))
    assert result.data.file_path.endswith("uploads/7/8/uuid.png")
    assert result.data.preview_upload_ref == "owned-reference"
    assert issue.await_args.kwargs["user_id"] == 8
    assert issue.await_args.kwargs["object_name"] == "uploads/7/8/uuid.png"


@pytest.mark.parametrize("caller_user,caller_tenant", [(8, 7), (9, 7), (8, 9)])
async def test_knowledge_staging_reference_roundtrip(monkeypatch, object_store, caller_user, caller_tenant):
    from bisheng.api.v1.schemas import KnowledgeFileOne
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.services import preview_source_service

    records = {}

    async def aset(key, value, **kwargs):
        records[key] = value

    async def aget(key):
        return records.get(key)

    redis = SimpleNamespace(aset=aset, aget=aget)
    monkeypatch.setattr(preview_source_service, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(preview_source_service, "get_minio_storage", AsyncMock(return_value=object_store[1]))
    monkeypatch.setattr(
        knowledge.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=4, user_id=1, tenant_id=7, type=KnowledgeTypeEnum.SPACE.value)),
    )
    monkeypatch.setattr(knowledge, "generate_uuid", lambda: "uuid")
    monkeypatch.setattr(knowledge.KnowledgeFileDao, "get_repeat_file", AsyncMock(return_value=None))
    response = await knowledge.upload_knowledge_file.__wrapped__(
        request=None, file=upload(), knowledge_id=4, login_user=UserPayload.model_construct(user_id=8, tenant_id=7)
    )
    item = KnowledgeFileOne(file_path=response.data.file_path, preview_upload_ref=response.data.preview_upload_ref)
    token = current_tenant_id.set(caller_tenant)
    try:
        if (caller_user, caller_tenant) == (8, 7):
            source = await PreviewSourceService.resolve(
                item=item, login_user=SimpleNamespace(user_id=caller_user), knowledge_id=4
            )
            assert source.object_name == "uploads/7/8/uuid.png"
            assert object_store[0][source.object_name] == b"first"
        else:
            with pytest.raises(HTTPException) as error:
                await PreviewSourceService.resolve(
                    item=item, login_user=SimpleNamespace(user_id=caller_user), knowledge_id=4
                )
            assert error.value.status_code == 404
    finally:
        current_tenant_id.reset(token)


@pytest.fixture
def telemetry(monkeypatch):
    monkeypatch.setattr(dashboard, "is_commercial", lambda: False)
    user = UserPayload.model_construct(user_id=8, tenant_id=7)
    service = dashboard.DashboardService(login_user=user)
    actor = SimpleNamespace(subject_type="user", data_scope="all_visible", tenant_id=7, super_admin=False)
    monkeypatch.setattr(dashboard, "resolve_permission_actor", AsyncMock(return_value=actor))
    monkeypatch.setattr(UserPayload, "async_access_check", AsyncMock(return_value=True))
    dataset = SimpleNamespace(
        es_index_name="mid_app_increment",
        schema_config={
            "metrics": [],
            "dimensions": [
                {"name": "User", "field": "user_name"},
                {"name": "Group", "field": "user_group_infos.user_group_name"},
            ],
        },
    )

    @asynccontextmanager
    async def session():
        yield object()

    repository = SimpleNamespace(find_all=AsyncMock(return_value=[dataset]))
    monkeypatch.setattr(dashboard, "get_async_db_session", session)
    monkeypatch.setattr(dashboard, "DashboardDatasetRepositoryImpl", lambda session: repository)
    from bisheng.database.models.tenant import UserTenantDao

    members = AsyncMock(return_value=[8, 9])
    monkeypatch.setattr(UserTenantDao, "aget_active_user_ids_by_tenant", members)
    es = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    "total_count": {"value": 2},
                    "enum_values": {"buckets": [{"key": "Alice"}, {"key": "Bob"}]},
                }
            }
        )
    )
    monkeypatch.setattr(dashboard, "get_es_connection", AsyncMock(return_value=es))
    return service, actor, members, es


@pytest.mark.parametrize(
    "path", ["/dashboard/dataset/list", "/dashboard/dataset/field/enums?index_name=mid_user_increment&field=user_name"]
)
def test_telemetry_dataset_routes_require_login(path):
    async def no_login():
        raise HTTPException(status_code=401)

    app = FastAPI()
    app.include_router(dashboard_api.router)
    app.dependency_overrides[UserPayload.get_login_user] = no_login
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "index,field",
    [
        ("*", "user_name"),
        ("mid_app_increment,secret", "user_name"),
        ("secret", "user_name"),
        ("mid_app_increment", "secret"),
        ("mid_app_increment", "user_name.text"),
    ],
)
async def test_enum_rejects_unknown_index_or_field(telemetry, index, field):
    service, _, _, es = telemetry
    with pytest.raises(NotFoundError):
        await service.get_dataset_field_enums(index, field)
    es.search.assert_not_awaited()


@pytest.mark.parametrize("admin", [False, True])
async def test_authorized_enum_preserves_tenant_wide_results(telemetry, admin):
    service, actor, members, es = telemetry
    actor.super_admin = admin
    result = await service.get_dataset_field_enums("mid_app_increment", "user_name")
    assert result == {"total": 2, "enums": ["Alice", "Bob"]}
    members.assert_awaited_once_with(7)
    assert es.search.await_args.kwargs["index"] == "mid_app_increment"
    assert es.search.await_args.kwargs["body"]["query"] == {"terms": {"user_id": [8, 9]}}


async def test_nested_enums_keep_tenant_filter_and_keyword(telemetry):
    service, _, _, es = telemetry
    es.search.return_value = {
        "aggregations": {
            "nested_agg": {
                "filter_wrapper": {"total_count": {"value": 1}, "enum_values": {"buckets": [{"key": "Team"}]}}
            }
        }
    }
    result = await service.get_dataset_field_enums(
        "mid_app_increment", "user_group_infos.user_group_name", keyword="Tea", size=10, page=2
    )
    assert result == {"total": 1, "enums": ["Team"]}
    body = es.search.await_args.kwargs["body"]
    assert body["query"] == {"terms": {"user_id": [8, 9]}}
    nested = body["aggs"]["nested_agg"]
    assert nested["nested"] == {"path": "user_group_infos"}
    wrapper = nested["aggs"]["filter_wrapper"]
    assert wrapper["filter"] == {"match_phrase": {"user_group_infos.user_group_name.text": "Tea"}}
    assert wrapper["aggs"]["enum_values"]["aggs"]["pagination"]["bucket_sort"] == {"from": 10, "size": 10}


async def test_empty_tenant_does_not_fall_back_to_global(telemetry):
    service, _, members, es = telemetry
    members.return_value = []
    await service.get_dataset_field_enums("mid_app_increment", "user_name")
    assert es.search.await_args.kwargs["body"]["query"] == {"terms": {"user_id": []}}


async def test_unauthorized_board_actor_never_reaches_es(telemetry, monkeypatch):
    service, _, _, es = telemetry
    monkeypatch.setattr(UserPayload, "async_access_check", AsyncMock(return_value=False))
    with pytest.raises(UnAuthorizedError):
        await service.get_dataset_field_enums("mid_app_increment", "user_name")
    es.search.assert_not_awaited()


@pytest.mark.parametrize("change", [{"tenant_id": 9}, {"data_scope": "owned"}, {"subject_type": "service_account"}])
async def test_actor_scope_fails_closed(telemetry, change):
    service, actor, _, es = telemetry
    for key, value in change.items():
        setattr(actor, key, value)
    with pytest.raises(UnAuthorizedError):
        await service.get_dataset_field_enums("mid_app_increment", "user_name")
    es.search.assert_not_awaited()


@pytest.mark.parametrize("size,page", [(0, 1), (-1, 1), (101, 1), (20, 0), (100, 1000)])
async def test_enum_pagination_is_bounded(telemetry, size, page):
    service, _, _, es = telemetry
    with pytest.raises(HTTPException) as error:
        await service.get_dataset_field_enums("mid_app_increment", "user_name", size=size, page=page)
    assert error.value.status_code == 422
    es.search.assert_not_awaited()
