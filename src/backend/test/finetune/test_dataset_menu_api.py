# ruff: noqa: F811
"""Real dataset routes and ORM isolation for ordinary menu-authorized people."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.finetune.api import dependencies
from bisheng.finetune.domain.models.preset_train import PresetTrainDao
from bisheng.finetune.domain.repositories.file_download_repository import FileDownloadRepository
from bisheng.finetune.domain.services import finetune_file as service
from bisheng.knowledge.domain import upload_file_size
from bisheng.knowledge.domain.models import knowledge as knowledge_model
from bisheng.knowledge.domain.models import knowledge_file as qa_model
from test.finetune.test_dataset_admin_visibility import datasets as datasets
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


class Objects:
    bucket = "datasets"
    tmp_bucket = "staging"

    def __init__(self):
        self.data = {}
        self.signatures = []
        self.reads = []

    async def put_object(self, *, object_name, file, bucket_name=None, **kwargs):
        self.data[bucket_name or self.bucket, object_name] = file if isinstance(file, bytes) else file.read()

    async def put_object_tmp(self, object_name, file, **kwargs):
        await self.put_object(bucket_name=self.tmp_bucket, object_name=object_name, file=file)

    async def get_object(self, bucket_name, object_name):
        self.reads.append((bucket_name, object_name))
        return self.data[bucket_name, object_name]

    async def get_share_link(self, object_name, bucket=None, **kwargs):
        self.signatures.append((bucket or self.bucket, object_name))
        return f"https://objects.test/{bucket or self.bucket}/{object_name}?signature=test"


@pytest.fixture
async def web(datasets, monkeypatch):
    web = datasets
    web.user.user_name = "ordinary dataset operator"
    web.menu = True
    web.model_menu = False
    web.tenant_admin = False
    web.objects = Objects()
    web.app.dependency_overrides[UserPayload.get_login_user] = lambda: web.user

    async def model_gate():
        raise LLMModelSharedReadonlyError()

    web.app.dependency_overrides[UserPayload.get_tenant_admin_user] = model_gate

    async def menu(user_id, key):
        assert user_id == web.user.user_id and key in {"dataset", "model"}
        if not (web.menu if key == "dataset" else web.model_menu):
            raise UnAuthorizedError.http_exception()

    web.menu_check = AsyncMock(side_effect=menu)
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", web.menu_check)
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=web.objects))
    monkeypatch.setattr(FileDownloadRepository, "preset_by_object", AsyncMock(return_value=None))
    monkeypatch.setattr(FileDownloadRepository, "owned_jobs", AsyncMock(return_value=[]))

    class MemoryRedis:
        def __init__(self):
            self.store = {}

        async def aset(self, key, value, expiration=None):
            self.store[key] = value

        async def aget(self, key):
            return self.store.get(key)

    redis = MemoryRedis()

    async def redis_client():
        return redis

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.preview_source_service.get_redis_client",
        redis_client,
    )
    monkeypatch.setattr(
        dependencies,
        "check_tenant_admin",
        AsyncMock(side_effect=lambda _user, tenant: web.tenant_admin and tenant == web.user.tenant_id),
    )
    monkeypatch.setattr(type(upload_file_size.settings), "get_from_db", lambda *_args, **_kwargs: {})

    @web.app.exception_handler(BaseErrorCode)
    async def error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump(mode="json"))

    return web


def result(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status_code"] == 200, body
    return body["data"]


async def create_local(web):
    uploaded = result(
        await web.client.post(
            "/api/v1/finetune/job/file/preset/upload",
            files={"file": ("sample.json", b'[{"instruction":"test","output":"ok"}]')},
        )
    )
    return result(
        await web.client.post(
            "/api/v1/finetune/job/file/preset",
            json={"name": "Created in child", "files": uploaded["file_path"]},
        )
    )


async def test_ordinary_menu_user_can_list_create_download_delete_in_own_tenant(web):
    page = result(await web.client.get("/api/v1/finetune/job/file/preset", params={"page_size": 1, "page_num": 1}))
    assert page["total"] == 3 and page["list"][0]["tenant_id"] == 60
    created = await create_local(web)
    assert created["tenant_id"] == 60 and str(created["user_id"]) == str(web.user.user_id)
    result(await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": created["url"]}))
    assert web.objects.signatures[-1] == (web.objects.bucket, created["url"])
    result(await web.client.delete("/api/v1/finetune/job/file/preset", params={"file_id": created["id"]}))
    deleted = await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": created["url"]})
    assert deleted.json()["status_code"] == 10120
    with tenant_execution_scope(60):
        assert await PresetTrainDao.find_one(created["id"]) is None
    assert web.menu_check.await_count >= 5


@pytest.mark.parametrize("operation", ["list", "upload", "create", "download", "delete"])
async def test_no_dataset_menu_denies_every_operation_before_storage_or_mutation(web, operation):
    web.menu = False
    paths = {
        "list": ("GET", "/job/file/preset", {}),
        "upload": ("POST", "/job/file/preset/upload", {"files": {"file": ("sample.json", b"[]")}}),
        "create": ("POST", "/job/file/preset", {"json": {"name": "Denied", "files": "anything"}}),
        "download": ("GET", "/job/file/download", {"params": {"file_url": "dataset/60/0.json"}}),
        "delete": ("DELETE", "/job/file/preset", {"params": {"file_id": "60-0"}}),
    }
    method, path, options = paths[operation]
    response = await web.client.request(method, "/api/v1/finetune" + path, **options)
    assert response.status_code == 403, response.text
    assert "19801" not in response.text
    assert not web.objects.data and not web.objects.signatures and not web.objects.reads
    with tenant_execution_scope(60):
        assert await PresetTrainDao.find_one("60-0") is not None


@pytest.mark.parametrize("foreign", [1, 70])
async def test_same_historical_creator_cannot_download_or_delete_foreign_dataset(web, foreign):
    download = await web.client.get(
        "/api/v1/finetune/job/file/download", params={"file_url": f"dataset/{foreign}/0.json"}
    )
    deletion = await web.client.delete("/api/v1/finetune/job/file/preset", params={"file_id": f"{foreign}-0"})
    assert download.json()["status_code"] == deletion.json()["status_code"] == 10120
    assert not web.objects.signatures
    with tenant_execution_scope(foreign):
        assert await PresetTrainDao.find_one(f"{foreign}-0") is not None


@pytest.mark.parametrize(
    "reference",
    [
        "https://objects.test/datasets/dataset/1/0.json",
        "https://objects.test/staging/finetune/dataset-upload/1/849/" + "a" * 32 + ".json",
        "https://objects.test/staging/finetune/dataset-upload/60/900/" + "a" * 32 + ".json",
        "/etc/passwd",
        "https://outside.test/sample.json",
    ],
)
async def test_create_rejects_unbound_sources_before_reading_any_object(web, reference):
    response = await web.client.post("/api/v1/finetune/job/file/preset", json={"name": "Invalid", "files": reference})
    assert response.json()["status_code"] == 10120
    assert not web.objects.reads and not web.objects.data


async def test_upload_from_old_tenant_cannot_be_used_after_reassignment(web):
    uploaded = result(
        await web.client.post("/api/v1/finetune/job/file/preset/upload", files={"file": ("sample.json", b"[]")})
    )
    web.user.tenant_id = 70
    response = await web.client.post(
        "/api/v1/finetune/job/file/preset", json={"name": "Moved", "files": uploaded["file_path"]}
    )
    assert response.json()["status_code"] == 10120 and not web.objects.reads


@pytest.mark.parametrize("path", ["/job", "/gpu", "/server/filters", "/model/list?server_id=1"])
async def test_dataset_menu_does_not_grant_finetune_tasks(web, path):
    response = await web.client.get("/api/v1/finetune" + path)
    assert response.status_code == 403


@pytest.fixture
async def qa_sources(web, monkeypatch):
    async with web.sessions() as session:
        await session.run_sync(lambda session: knowledge_model.Knowledge.__table__.create(session.get_bind()))
        await session.run_sync(lambda session: qa_model.QAKnowledge.__table__.create(session.get_bind()))
        with bypass_tenant_filter():
            for tenant in (1, 60, 70):
                for index in (1, 2, 3):
                    ident = tenant * 100 + index
                    session.add(
                        knowledge_model.Knowledge(
                            id=ident, tenant_id=tenant, user_id=900, name=f"QA {ident}", type=1 if index < 3 else 0
                        )
                    )
                    session.add(
                        qa_model.QAKnowledge(
                            knowledge_id=ident,
                            tenant_id=tenant,
                            user_id=900,
                            questions=[f"Question {ident}"],
                            answers=json.dumps([f"Answer {ident}"]),
                        )
                    )
            await session.commit()
    monkeypatch.setattr(knowledge_model, "get_async_db_session", web.sessions)
    monkeypatch.setattr(qa_model, "get_async_db_session", web.sessions)
    web.source_access = AsyncMock()
    monkeypatch.setattr(service, "require_business_action", web.source_access, raising=False)
    return web


async def test_qa_creation_keeps_source_read_checks_and_exports_real_rows(qa_sources):
    web = qa_sources
    created = result(
        await web.client.post("/api/v1/finetune/job/file/preset", json={"name": "QA dataset", "qa_list": [6001, 6002]})
    )
    assert created["tenant_id"] == 60 and created["type"] == 1
    samples = json.loads(web.objects.data[web.objects.bucket, created["url"]])
    assert {row["instruction"] for row in samples} == {"Question 6001", "Question 6002"}
    assert web.source_access.await_count == 2
    for call in web.source_access.await_args_list:
        assert call.args == (web.user,)
        assert call.kwargs["resource_type"] == "knowledge_library" and call.kwargs["action"] == "visible"


@pytest.mark.parametrize("ids", [[101], [7001], [6001, 101], [6001, 7001], [99999], [6003]])
async def test_qa_creation_rejects_missing_or_foreign_sources_atomically(qa_sources, ids):
    response = await qa_sources.client.post(
        "/api/v1/finetune/job/file/preset", json={"name": "Invalid", "qa_list": ids}
    )
    assert response.json()["status_code"] == 10120
    assert not qa_sources.objects.data
    qa_sources.source_access.assert_not_awaited()


async def test_dataset_menu_is_not_a_grant_to_read_qa_sources(qa_sources):
    qa_sources.source_access.side_effect = UnAuthorizedError()
    response = await qa_sources.client.post(
        "/api/v1/finetune/job/file/preset", json={"name": "Denied source", "qa_list": [6001]}
    )
    assert response.json()["status_code"] == 403
    assert not qa_sources.objects.data


async def test_super_selected_tenant_stamps_created_data_in_selection_not_home(web):
    web.user.is_global_super = True
    web.user.tenant_id = 1
    web.selected.tenant_id = 70
    web.client.headers["X-Management-Tenant"] = "70"
    created = await create_local(web)
    assert created["tenant_id"] == 70 and "/70/" in created["url"]


async def test_menu_grants_tenant_dataset_management_not_only_own_creations(web):
    web.user.user_id = 900
    result(await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": "dataset/60/0.json"}))
    result(await web.client.delete("/api/v1/finetune/job/file/preset", params={"file_id": "60-0"}))
    with tenant_execution_scope(60):
        assert await PresetTrainDao.find_one("60-0") is None


async def test_menu_revocation_is_honored_on_the_next_operation(web):
    result(await web.client.get("/api/v1/finetune/job/file/preset"))
    web.menu = False
    response = await web.client.delete("/api/v1/finetune/job/file/preset", params={"file_id": "60-0"})
    assert response.status_code == 403
    with tenant_execution_scope(60):
        assert await PresetTrainDao.find_one("60-0") is not None


async def test_current_tenant_admin_keeps_implicit_dataset_capability(web):
    web.menu = False
    web.tenant_admin = True
    result(await web.client.get("/api/v1/finetune/job/file/preset"))
    created = await create_local(web)
    assert created["tenant_id"] == 60
    web.menu_check.assert_not_awaited()


async def test_global_admin_keeps_implicit_dataset_capability_in_selected_tenant(web):
    web.menu = False
    web.user.is_global_super = True
    web.user.tenant_id = 1
    web.selected.tenant_id = 70
    web.client.headers["X-Management-Tenant"] = "70"
    created = await create_local(web)
    assert created["tenant_id"] == 70
    web.menu_check.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "original/secret.json",
        "finetune/train_file/personal/1/849/" + "a" * 32 + ".json",
        "finetune/train_file/personal/60/900/" + "a" * 32 + ".json",
        "finetune/train_file/personal/60/849/../secret.json",
        "finetune/train_file/personal/old-unbound.json",
    ],
)
async def test_unknown_or_foreign_personal_uploads_are_not_signed(web, url):
    response = await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": url})
    assert response.json()["status_code"] == 10120 and not web.objects.signatures


async def test_personal_model_uploads_stay_downloadable_only_in_their_original_scope(web):
    web.model_menu = True
    uploaded = result(await web.client.post("/api/v1/finetune/job/file", files={"files": ("training.json", b"[]")}))[0]
    assert "/60/849/" in uploaded["url"]
    result(await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": uploaded["url"]}))
    web.user.tenant_id = 70
    response = await web.client.get("/api/v1/finetune/job/file/download", params={"file_url": uploaded["url"]})
    assert response.json()["status_code"] == 10120
