"""Model-menu tasks use real routes/SQLite; remote training/storage is stubbed."""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.request_scope import RequestScope, inherit_scope
from bisheng.core.context.tenant import bypass_tenant_filter, set_visible_tenant_ids, tenant_execution_scope
from bisheng.finetune.api.server import router as server_router
from bisheng.finetune.domain.models import finetune, model_deploy, server, sft_model
from bisheng.finetune.domain.services import finetune as service
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.llm.api import router as llm_api
from test.finetune.test_dataset_admin_visibility import datasets as datasets
from test.finetune.test_dataset_menu_api import result
from test.finetune.test_dataset_menu_api import web as web
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


@pytest.fixture
async def tasks(web, monkeypatch):
    web.model_menu = True
    web.menu = False
    modules = (server, model_deploy, finetune, sft_model)
    models = (server.Server, model_deploy.ModelDeploy, finetune.Finetune, sft_model.SftModel)
    async with web.sessions() as session:
        for model in models:
            await session.run_sync(lambda session, model=model: model.__table__.create(session.get_bind()))
    for module in modules:
        monkeypatch.setattr(module, "get_async_db_session", web.sessions)
    with bypass_tenant_filter():
        async with web.sessions() as session:
            for tenant in (1, 60, 70):
                session.add(
                    server.Server(
                        id=tenant,
                        tenant_id=tenant,
                        server=f"FT-{tenant}",
                        endpoint="runtime",
                        sft_endpoint=f"http://training-{tenant}.test",
                    )
                )
                session.add(
                    model_deploy.ModelDeploy(
                        id=tenant,
                        tenant_id=tenant,
                        server=str(tenant),
                        model="base",
                        endpoint="private endpoint",
                        config="private config",
                    )
                )
                session.add(
                    finetune.Finetune(
                        id=f"job-{tenant}",
                        tenant_id=tenant,
                        server=tenant,
                        server_name=f"FT-{tenant}",
                        rt_endpoint="runtime",
                        base_model_name="base",
                        model_id=tenant,
                        model_name=f"trained-{tenant}",
                        extra_params={"gpus": "0"},
                        user_id=849,
                        user_name="same historical creator",
                        sft_endpoint=f"http://training-{tenant}.test",
                    )
                )
                session.add(sft_model.SftModel(tenant_id=tenant, model_name="same-name"))
            await session.commit()
    for router in (server_router, llm_api.router):
        inherit_scope(router, RequestScope.TENANT)
        web.app.include_router(router, prefix="/api/v1")
    from bisheng.admin.application.request_admission import install_request_admission

    install_request_admission(web.app)
    monkeypatch.setattr(
        service.SFTBackend, "_base_request", AsyncMock(side_effect=AssertionError("Unstubbed FT transport"))
    )
    for name in ("create_job", "cancel_job", "delete_job", "publish_job", "cancel_publish_job", "change_model_name"):
        mock = AsyncMock(return_value=(True, {}))
        monkeypatch.setattr(service.SFTBackend, name, mock)
    monkeypatch.setattr(service.SFTBackend, "get_all_model", AsyncMock(side_effect=lambda *_args: (True, ["base"])))
    monkeypatch.setattr(service.SFTBackend, "get_gpu_info", AsyncMock(return_value=(False, "unavailable")))
    monkeypatch.setattr(FinetuneService, "sync_all_job_status", AsyncMock())
    monkeypatch.setattr(FinetuneService, "sync_job_status", AsyncMock())
    monkeypatch.setattr(FinetuneService, "delete_job_log", AsyncMock())
    web.signed = []

    def sign(key, **kwargs):
        web.signed.append(key)
        return f"https://objects.test/{key}?signed=1"

    web.objects.get_share_link_sync = sign
    monkeypatch.setattr(service, "get_minio_storage_sync", lambda: web.objects)
    return web


def payload(**overrides):
    return {
        "server": 60,
        "base_model": 60,
        "model_name": "new-training",
        "method": "full",
        "extra_params": {"gpus": "0"},
        "preset_data": [{"id": "60-0", "name": "dataset", "url": "dataset/60/0.json"}],
        **overrides,
    }


async def test_model_menu_can_complete_task_form_without_dataset_or_admin_menu(tasks):
    assert result(await tasks.client.get("/api/v1/finetune/server/options")) == [{"id": 60, "server": "FT-60"}]
    models = result(await tasks.client.get("/api/v1/finetune/model/list?server_id=60"))
    assert models == [{"id": 60, "model": "base", "sft_support": True}]
    presets = result(await tasks.client.get("/api/v1/finetune/training-data"))
    assert presets["total"] == 3 and {row["tenant_id"] for row in presets["list"]} == {60}
    result(await tasks.client.get("/api/v1/finetune/training-data/download", params={"file_url": "dataset/60/0.json"}))
    upload = result(await tasks.client.post("/api/v1/finetune/job/file", files={"files": ("train.json", b'[{"instruction": "q", "output": "a"}]')}))[0]
    created = result(
        await tasks.client.post(
            "/api/v1/finetune/job", json=payload(train_data=[{"name": "personal", "url": upload["url"]}])
        )
    )
    assert created["tenant_id"] == 60 and created["user_id"] == 849
    assert tasks.signed == [upload["url"], "dataset/60/0.json"]
    service.SFTBackend.create_job.assert_awaited_once()
    assert {row["tenant_id"] for row in result(await tasks.client.get("/api/v1/finetune/job"))["data"]} == {60}
    result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))
    result(await tasks.client.post("/api/v1/finetune/job/cancel?job_id=job-60"))
    result(await tasks.client.patch("/api/v1/finetune/job/model", json={"id": "job-60", "model_name": "renamed"}))
    result(await tasks.client.delete("/api/v1/finetune/job?job_id=job-60"))
    service.SFTBackend.cancel_job.assert_awaited_once()
    service.SFTBackend.delete_job.assert_awaited_once()


async def test_model_menu_can_publish_and_unpublish_task_artifact(tasks):
    with tenant_execution_scope(60):
        job = await finetune.FinetuneDao.find_job("job-60")
        job.status = finetune.FinetuneStatus.SUCCESS.value
        await finetune.FinetuneDao.update_job(job)
    published = result(await tasks.client.post("/api/v1/finetune/job/publish?job_id=job-60"))
    assert published["status"] == 5 and published["model_id"]
    with tenant_execution_scope(60):
        model = await model_deploy.ModelDeployDao.find_model(published["model_id"])
        assert model.tenant_id == 60
        model.status = "已上线"
        await model_deploy.ModelDeployDao.update_model(model)
    assert result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))["model_online"] is True
    unpublished = result(await tasks.client.post("/api/v1/finetune/job/publish/cancel?job_id=job-60"))
    assert unpublished["status"] == 4 and unpublished["model_id"] == 0
    with tenant_execution_scope(60):
        assert await model_deploy.ModelDeployDao.find_model(published["model_id"]) is None
    service.SFTBackend.publish_job.assert_awaited_once()
    service.SFTBackend.cancel_publish_job.assert_awaited_once()


TASK_REQUESTS = [
    ("get", "/job", {}),
    ("post", "/job", {"json": payload()}),
    ("get", "/job/info?job_id=job-60", {}),
    ("delete", "/job?job_id=job-60", {}),
    ("post", "/job/cancel?job_id=job-60", {}),
    ("post", "/job/publish?job_id=job-60", {}),
    ("post", "/job/publish/cancel?job_id=job-60", {}),
    ("patch", "/job/model", {"json": {"id": "job-60", "model_name": "renamed"}}),
    ("post", "/job/file", {"files": {"files": ("train.json", b'[{"instruction": "q", "output": "a"}]')}}),
    ("get", "/server/filters", {}),
    ("get", "/server/options", {}),
    ("get", "/model/list?server_id=60", {}),
    ("get", "/gpu", {}),
    ("get", "/training-data", {}),
    ("get", "/training-data/download?file_url=dataset/60/0.json", {}),
]


@pytest.mark.parametrize("method,path,kwargs", TASK_REQUESTS)
async def test_dataset_menu_and_revoked_model_menu_cannot_admit_any_task_endpoint(tasks, method, path, kwargs):
    tasks.menu = True
    tasks.model_menu = False
    response = await tasks.client.request(method, "/api/v1/finetune" + path, **kwargs)
    assert response.status_code == 403, response.text
    service.SFTBackend.create_job.assert_not_awaited()


@pytest.mark.parametrize("tenant", [1, 70])
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/job/info"),
        ("delete", "/job"),
        ("post", "/job/cancel"),
        ("post", "/job/publish"),
        ("post", "/job/publish/cancel"),
        ("patch", "/job/model"),
    ],
)
async def test_foreign_historical_creator_jobs_never_reach_remote_backend(tasks, tenant, method, path):
    kwargs = (
        {"json": {"id": f"job-{tenant}", "model_name": "renamed"}}
        if method == "patch"
        else {"params": {"job_id": f"job-{tenant}"}}
    )
    response = await tasks.client.request(method, "/api/v1/finetune" + path, **kwargs)
    assert response.json()["status_code"] == 10102
    for name in ("create_job", "cancel_job", "delete_job", "publish_job", "cancel_publish_job", "change_model_name"):
        getattr(service.SFTBackend, name).assert_not_awaited()


async def test_reassignment_revokes_old_jobs_services_and_training_sources(tasks):
    upload = result(await tasks.client.post("/api/v1/finetune/job/file", files={"files": ("train.json", b'[{"instruction": "q", "output": "a"}]')}))[0]
    result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))
    tasks.user.tenant_id = 70
    assert result(await tasks.client.get("/api/v1/finetune/server/options")) == [{"id": 70, "server": "FT-70"}]
    assert (await tasks.client.get("/api/v1/finetune/model/list?server_id=60")).json()["status_code"] != 200
    assert (await tasks.client.delete("/api/v1/finetune/job?job_id=job-60")).json()["status_code"] == 10102
    for source in [upload["url"], "dataset/60/0.json"]:
        response = await tasks.client.get("/api/v1/finetune/training-data/download", params={"file_url": source})
        assert response.json()["status_code"] == 10120
    response = await tasks.client.post(
        "/api/v1/finetune/job",
        json=payload(
            server=70, base_model=70, preset_data=[], train_data=[{"name": "old upload", "url": upload["url"]}]
        ),
    )
    assert response.json()["status_code"] == 10120 and not tasks.signed
    service.SFTBackend.delete_job.assert_not_awaited()
    service.SFTBackend.create_job.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [
        {"server": 1},
        {"server": 70},
        {"base_model": 1},
        {"base_model": 70},
        {"preset_data": [{"id": "1-0", "url": "dataset/1/0.json", "name": "foreign"}]},
        {"preset_data": [{"id": "70-0", "url": "dataset/70/0.json", "name": "foreign"}]},
        {"preset_data": [{"id": "1-0", "url": "dataset/60/0.json", "name": "mismatched id"}]},
        {"train_data": [{"url": "original/secret.json", "name": "secret"}]},
        {"train_data": [{"url": "finetune/train_file/personal/60/900/" + "a" * 32 + ".json", "name": "other person"}]},
    ],
)
async def test_creation_rejects_unowned_references_before_signing_or_remote_calls(tasks, overrides):
    response = await tasks.client.post("/api/v1/finetune/job", json=payload(**overrides))
    assert response.json()["status_code"] != 200
    assert not tasks.signed
    service.SFTBackend.create_job.assert_not_awaited()


async def test_same_tenant_base_model_must_belong_to_selected_service(tasks):
    with tenant_execution_scope(60):
        await server.ServerDao.insert(
            server.Server(id=61, server="another FT", endpoint="", sft_endpoint="http://another.test")
        )
    response = await tasks.client.post("/api/v1/finetune/job", json=payload(server=61))
    assert response.json()["status_code"] != 200 and not tasks.signed
    service.SFTBackend.create_job.assert_not_awaited()


async def test_lookups_and_bulk_mutations_ignore_root_visibility_and_old_server_reads(tasks):
    with tenant_execution_scope(1):
        assert (await FinetuneService.get_server(1)).tenant_id == 1
    with tenant_execution_scope(60):
        set_visible_tenant_ids(frozenset({1, 60, 70}))
        assert await FinetuneService.get_server(1) is None
        assert await finetune.FinetuneDao.find_job_by_model_name("trained-1") is None
        assert await finetune.FinetuneDao.find_job_by_model_id(1) is None
        await server.ServerDao.delete(1)
        await model_deploy.ModelDeployDao.delete_model_by_id(1)
        await sft_model.SftModelDao.delete_sft_model("same-name")
        assert not await finetune.FinetuneDao.change_status("job-1", 1, 3)
    with tenant_execution_scope(1):
        assert await server.ServerDao.find_server(1) is not None
        assert await model_deploy.ModelDeployDao.find_model(1) is not None
        assert await sft_model.SftModelDao.get_sft_model("same-name") is not None
        assert (await finetune.FinetuneDao.find_job("job-1")).status == 1


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/server/list_server", {}),
        ("post", "/server/add", {"json": {"server": "x", "endpoint": ""}}),
        ("delete", "/server/60", {}),
        ("get", "/server/model/60", {}),
        ("post", "/llm", {"json": {}}),
        ("put", "/llm", {"json": {}}),
        ("delete", "/llm", {"json": {"server_id": 60}}),
        ("get", "/llm/info?server_id=60", {}),
        ("post", "/llm/models/discover", {"json": {}}),
        ("post", "/llm/online", {"json": {}}),
        ("post", "/llm/verify", {"json": {}}),
        ("get", "/llm/system-settings", {}),
        ("get", "/llm/workbench/settings", {}),
    ],
)
async def test_model_menu_never_grants_ft_service_or_model_administration(tasks, monkeypatch, method, path, kwargs):
    from bisheng.common import permission_identity
    from bisheng.utils import http_middleware

    actual_gate = UserPayload.get_tenant_admin_user
    monkeypatch.setattr(UserPayload, "get_login_user", AsyncMock(return_value=tasks.user))
    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(permission_identity, "check_tenant_admin", AsyncMock(return_value=False))

    async def gate():
        return await actual_gate(None)

    tasks.app.dependency_overrides[actual_gate] = gate
    response = await tasks.client.request(method, "/api/v1" + path, **kwargs)
    assert response.json()["status_code"] == 19801, response.text


@pytest.mark.parametrize("admin", ["tenant", "super"])
async def test_admins_retain_implicit_task_access_without_model_menu(tasks, admin):
    tasks.model_menu = False
    tasks.tenant_admin = admin == "tenant"
    tasks.user.is_global_super = admin == "super"
    if admin == "super":
        tasks.user.tenant_id = 1
        tasks.selected.tenant_id = 70
        tasks.client.headers["X-Management-Tenant"] = "70"
    selected = 60 if admin == "tenant" else 70
    assert result(await tasks.client.get("/api/v1/finetune/server/options")) == [
        {"id": selected, "server": f"FT-{selected}"}
    ]
    tasks.menu_check.assert_not_awaited()


async def test_task_menu_manages_current_tenant_jobs_created_by_other_members(tasks):
    tasks.user.user_id = 900
    info = result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))
    assert info["finetune"]["user_id"] == 849
    result(await tasks.client.post("/api/v1/finetune/job/cancel?job_id=job-60"))
    service.SFTBackend.cancel_job.assert_awaited_once()


async def test_model_list_remains_readable_for_ordinary_model_menu_user(tasks, monkeypatch):
    read = AsyncMock(return_value=[{"id": 60, "name": "tenant model provider", "models": []}])
    monkeypatch.setattr(llm_api.LLMService, "get_all_llm", read)
    assert result(await tasks.client.get("/api/v1/llm"))[0]["id"] == 60
    read.assert_awaited_once_with(only_shared=False, operator=tasks.user)
