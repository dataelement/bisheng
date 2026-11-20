# ruff: noqa: F811
"""Adversarial references and FT transport scope, through real tenant HTTP routes."""

from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.finetune.domain.models.finetune import FinetuneDao
from bisheng.finetune.domain.models.server import ServerDao
from bisheng.finetune.domain.services import finetune as service
from bisheng.finetune.domain.services.finetune import FinetuneService
from test.finetune.test_dataset_admin_visibility import datasets as datasets
from test.finetune.test_dataset_menu_api import result
from test.finetune.test_dataset_menu_api import web as web
from test.finetune.test_finetune_menu_api import payload
from test.finetune.test_finetune_menu_api import tasks as tasks
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


def assert_no_mutations(tasks):
    assert not tasks.signed
    for name in ("create_job", "cancel_job", "delete_job", "publish_job", "cancel_publish_job", "change_model_name"):
        getattr(service.SFTBackend, name).assert_not_awaited()


@pytest.mark.parametrize(
    "extra",
    [
        {"output_dir": "/other-tenant/model"},
        {"resume_from_checkpoint": "/other-tenant/checkpoint"},
        {"dataset_dir": "/other-tenant/files"},
        {"adapter_name_or_path": "/other-tenant/model"},
        {"gpus": "0 --output_dir=/other-tenant"},
        {"cpu_load": "true --dataset=/other-tenant"},
    ],
)
async def test_training_options_cannot_forward_unapproved_paths_or_flags(tasks, extra):
    response = await tasks.client.post("/api/v1/finetune/job", json=payload(extra_params={"gpus": "0", **extra}))
    assert response.status_code == 422 or response.json()["status_code"] != 200
    assert_no_mutations(tasks)


@pytest.mark.parametrize("name", ["../root-model", "/root/model", "root\\model", "root/model", "x," + "a" * 50])
@pytest.mark.parametrize("method", ["create", "rename"])
async def test_model_artifact_names_cannot_address_paths(tasks, name, method):
    if method == "create":
        response = await tasks.client.post("/api/v1/finetune/job", json=payload(model_name=name))
    else:
        response = await tasks.client.patch("/api/v1/finetune/job/model", json={"id": "job-60", "model_name": name})
    assert response.status_code == 422 or response.json()["status_code"] != 200
    assert_no_mutations(tasks)


@pytest.mark.parametrize("num", ["0,/other-tenant/file", -1, 1.5, {"url": "original/secret.json"}])
async def test_sample_counts_are_not_raw_transport_arguments(tasks, num):
    body = payload(preset_data=[{"id": "60-0", "name": "dataset", "url": "dataset/60/0.json", "num": num}])
    response = await tasks.client.post("/api/v1/finetune/job", json=body)
    assert response.status_code == 422 or response.json()["status_code"] != 200
    assert_no_mutations(tasks)


@pytest.mark.parametrize(
    "mutation",
    [
        {"server": 1},
        {"sft_endpoint": "http://training-1.test"},
        {"status": 5, "model_id": 1},
        {"model_name": "../root-model"},
    ],
)
@pytest.mark.parametrize("action", ["info", "delete", "unpublish", "rename"])
async def test_legacy_own_job_cannot_follow_foreign_server_or_model_references(tasks, mutation, action):
    with tenant_execution_scope(60):
        job = await FinetuneDao.find_job("job-60")
        for key, value in mutation.items():
            setattr(job, key, value)
        await FinetuneDao.update_job(job)
    if action == "info":
        response = await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60")
    elif action == "delete":
        response = await tasks.client.delete("/api/v1/finetune/job?job_id=job-60")
    elif action == "unpublish":
        response = await tasks.client.post("/api/v1/finetune/job/publish/cancel?job_id=job-60")
    else:
        response = await tasks.client.patch(
            "/api/v1/finetune/job/model", json={"id": "job-60", "model_name": "safe-new-name"}
        )
    assert response.json()["status_code"] != 200
    assert_no_mutations(tasks)


@pytest.mark.parametrize(
    "action", ["models", "create", "cancel", "publish", "unpublish", "delete", "rename", "info", "gpu"]
)
async def test_shared_ft_transport_is_rejected_before_remote_access(tasks, action, monkeypatch):
    # The FT protocol has no tenant argument: a shared host is one global namespace.
    with bypass_tenant_filter():
        async with tasks.sessions() as session:
            server = await ServerDao.find_server(1)
            server.sft_endpoint = "http://training-60.test/some-path"
            session.add(server)
            await session.commit()
    get_status = AsyncMock(return_value=(True, {"status": "RUNNING"}))
    monkeypatch.setattr(service.SFTBackend, "get_job_status", get_status)
    service.SFTBackend.get_all_model.reset_mock()
    service.SFTBackend.get_gpu_info.reset_mock()
    if action == "models":
        response = await tasks.client.get("/api/v1/finetune/model/list?server_id=60")
    elif action == "create":
        response = await tasks.client.post("/api/v1/finetune/job", json=payload())
    elif action == "info":
        response = await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60")
    elif action == "gpu":
        response = await tasks.client.get("/api/v1/finetune/gpu")
    elif action == "rename":
        response = await tasks.client.patch(
            "/api/v1/finetune/job/model", json={"id": "job-60", "model_name": "safe-new-name"}
        )
    elif action == "delete":
        response = await tasks.client.delete("/api/v1/finetune/job?job_id=job-60")
    else:
        if action in {"publish", "unpublish"}:
            with tenant_execution_scope(60):
                job = await FinetuneDao.find_job("job-60")
                job.status = 4 if action == "publish" else 5
                await FinetuneDao.update_job(job)
        path = "publish/cancel" if action == "unpublish" else action
        response = await tasks.client.post(f"/api/v1/finetune/job/{path}?job_id=job-60")
    if response.json()["status_code"] == 200:
        assert response.json()["data"] == []
    service.SFTBackend.get_all_model.assert_not_awaited()
    service.SFTBackend.get_gpu_info.assert_not_awaited()
    get_status.assert_not_awaited()
    assert_no_mutations(tasks)


async def test_status_background_reloads_and_rejects_foreign_job_instance(tasks, monkeypatch):
    with tenant_execution_scope(1):
        foreign = await FinetuneDao.find_job("job-1")
    get_status = AsyncMock(return_value=(True, {"status": "RUNNING"}))
    monkeypatch.setattr(service.SFTBackend, "get_job_status", get_status)
    # Use the real implementation instead of the form fixture's status stub.
    with tenant_execution_scope(60):
        await REAL_SYNC_STATUS(foreign, foreign.sft_endpoint)
    get_status.assert_not_awaited()


REAL_SYNC_STATUS = FinetuneService.sync_job_status


async def test_training_uses_normalized_options_and_canonical_file_keys(tasks, monkeypatch):
    from bisheng.finetune.domain.models.preset_train import PresetTrainDao

    find = PresetTrainDao.find_by_url

    async def case_insensitive_lookup(key):
        return await find(key.lower())

    monkeypatch.setattr(PresetTrainDao, "find_by_url", case_insensitive_lookup)
    created = result(
        await tasks.client.post(
            "/api/v1/finetune/job",
            json=payload(
                extra_params={"gpus": "0,,1", "learning_rate": "0.001", "num_train_epochs": "2", "cpu_load": "false"},
                preset_data=[{"id": "60-0", "name": "posted label", "url": "DATASET/60/0.JSON", "num": "5"}],
            ),
        )
    )
    assert tasks.signed == ["dataset/60/0.json"]
    assert created["preset_data"][0] == {"id": "60-0", "name": "dataset-60-0", "url": "dataset/60/0.json", "num": 5}
    args = service.SFTBackend.create_job.call_args.kwargs
    assert args["params"]["gpus"] == "0,1"
    assert args["params"]["learning_rate"] == 0.001
    assert args["params"]["num_train_epochs"] == 2
    assert args["params"]["each_max_samples"] == "5"
    assert "cpu_load" not in args["params"]


async def test_foreign_log_reference_is_rejected_before_object_storage_read(tasks, monkeypatch):
    storage = AsyncMock()
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    with tenant_execution_scope(60):
        job = await FinetuneDao.find_job("job-60")
        job.log_path = "finetune/log/job-1"
        await FinetuneDao.update_job(job)
    response = await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60")
    assert response.json()["status_code"] != 200
    storage.get_object.assert_not_awaited()


async def test_own_log_is_read_with_its_canonical_task_key(tasks, monkeypatch):
    storage = AsyncMock()
    storage.get_object.return_value = b""
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=storage))
    with tenant_execution_scope(60):
        job = await FinetuneDao.find_job("job-60")
        job.log_path = "/finetune/log/job-60"
        await FinetuneDao.update_job(job)
    result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))
    storage.get_object.assert_awaited_once_with(object_name="finetune/log/job-60")


async def test_background_uses_reloaded_task_transport_instead_of_caller_endpoint(tasks, monkeypatch):
    get_status = AsyncMock(return_value=(False, "not finished"))
    monkeypatch.setattr(service.SFTBackend, "get_job_status", get_status)
    with tenant_execution_scope(60):
        job = await FinetuneDao.find_job("job-60")
        # A pending refresh may carry stale object fields and an old endpoint.
        job.sft_endpoint = "http://training-1.test"
        await REAL_SYNC_STATUS(job, "http://training-1.test")
    get_status.assert_awaited_once_with(host="http://training-60.test", job_id="job-60")


@pytest.mark.parametrize("target,super_user", [(60, False), (70, True)])
async def test_service_registration_stamps_verified_target_not_request_tenant(tasks, target, super_user, monkeypatch):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.permission import application

    # The route override already admits this caller. The service repeats the admin check.
    monkeypatch.setattr(application, "is_tenant_admin", AsyncMock(return_value=True))
    tasks.app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: tasks.user
    if super_user:
        tasks.user.is_global_super = True
        tasks.user.tenant_id = 1
        tasks.selected.tenant_id = target
        tasks.client.headers["X-Management-Tenant"] = str(target)
    created = result(
        await tasks.client.post(
            "/api/v1/server/add",
            json={
                "server": "new FT",
                "endpoint": "",
                "sft_endpoint": "http://new-ft.test",
                "tenant_id": 1,
            },
        )
    )
    assert created["tenant_id"] == target
    with tenant_execution_scope(1):
        assert await ServerDao.find_server(created["id"]) is None


@pytest.mark.parametrize(
    "address", ["http://TRAINING-60.test:80/path", "training-60.test:80", "http://training-60.test./other"]
)
async def test_equivalent_ft_addresses_cannot_bypass_ownership_check(tasks, address):
    with bypass_tenant_filter():
        async with tasks.sessions() as session:
            foreign = await ServerDao.find_server(1)
            foreign.sft_endpoint = address
            session.add(foreign)
            await session.commit()
    assert result(await tasks.client.get("/api/v1/finetune/server/options")) == []
    service.SFTBackend.get_all_model.assert_not_awaited()


async def test_same_tenant_service_aliases_do_not_block_legitimate_tasks(tasks):
    from bisheng.finetune.domain.models.server import Server

    with tenant_execution_scope(60):
        await ServerDao.insert(
            Server(server="alias", endpoint="runtime", sft_endpoint="http://training-60.test"), tenant_id=60
        )
    options = result(await tasks.client.get("/api/v1/finetune/server/options"))
    assert len(options) == 2
    result(await tasks.client.post("/api/v1/finetune/job", json=payload()))
    service.SFTBackend.create_job.assert_awaited_once()


async def test_detail_returns_the_revalidated_background_status_and_log(tasks, monkeypatch):
    from types import SimpleNamespace

    log = b'{"current_steps": 1, "loss": 0.1}'
    objects = SimpleNamespace(bucket="objects", put_object=AsyncMock(), get_object=AsyncMock(return_value=log))
    monkeypatch.setattr(service, "get_minio_storage", AsyncMock(return_value=objects))
    monkeypatch.setattr(FinetuneService, "sync_job_status", REAL_SYNC_STATUS)
    monkeypatch.setattr(service.SFTBackend, "get_job_status", AsyncMock(return_value=(True, {"status": "FINISHED"})))
    monkeypatch.setattr(service.SFTBackend, "get_job_log", AsyncMock(return_value=(True, {"log_data": log.decode()})))
    monkeypatch.setattr(service.SFTBackend, "get_job_metrics", AsyncMock(return_value=(True, {"report": {"ok": True}})))
    info = result(await tasks.client.get("/api/v1/finetune/job/info?job_id=job-60"))
    assert info["finetune"]["status"] == 4 and info["report"] == {"ok": True}
    assert info["loss_data"] == [{"step": 1, "loss": 0.1}]
    objects.get_object.assert_awaited_once_with(object_name="finetune/log/job-60")


@pytest.mark.parametrize("action", ["delete", "unpublish"])
async def test_remote_failure_retains_published_reference_so_guarded_retry_works(tasks, action):
    from bisheng.finetune.domain.models.model_deploy import ModelDeployDao

    with tenant_execution_scope(60):
        job = await FinetuneDao.find_job("job-60")
        job.status = 4
        await FinetuneDao.update_job(job)
    published = result(await tasks.client.post("/api/v1/finetune/job/publish?job_id=job-60"))
    remote = service.SFTBackend.delete_job if action == "delete" else service.SFTBackend.cancel_publish_job
    remote.side_effect = [(False, "temporary failure"), (True, {})]
    url = (
        "/api/v1/finetune/job?job_id=job-60"
        if action == "delete"
        else "/api/v1/finetune/job/publish/cancel?job_id=job-60"
    )
    request = tasks.client.delete if action == "delete" else tasks.client.post
    assert (await request(url)).json()["status_code"] != 200
    with tenant_execution_scope(60):
        assert await ModelDeployDao.find_model(published["model_id"]) is not None
        assert (await FinetuneDao.find_job("job-60")).status == 5
    result(await request(url))
    assert remote.await_count == 2


async def test_remote_global_catalog_is_not_imported_into_another_tenant(tasks, monkeypatch):
    from bisheng.finetune.domain.models.model_deploy import ModelDeployDao

    with bypass_tenant_filter():
        async with tasks.sessions() as session:
            root = await ServerDao.find_server(1)
            root.sft_endpoint = "http://training-60.test"
            session.add(root)
            await session.commit()
    catalog = AsyncMock(return_value=(True, ["root-only-trained-model"]))
    monkeypatch.setattr(service.SFTBackend, "get_all_model", catalog)
    response = await tasks.client.get("/api/v1/finetune/model/list?server_id=60")
    assert response.json()["status_code"] != 200
    catalog.assert_not_awaited()
    with tenant_execution_scope(60):
        assert await ModelDeployDao.find_model_by_name("root-only-trained-model") is None


async def test_ft_administrator_detail_still_filters_foreign_and_missing_models(tasks):
    from bisheng.common.dependencies.user_deps import UserPayload

    tasks.app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: tasks.user
    own = result(await tasks.client.get("/api/v1/server/model/60"))
    assert own["tenant_id"] == 60
    for model_id in (1, 999):
        response = await tasks.client.get(f"/api/v1/server/model/{model_id}")
        assert response.json()["status_code"] == 404 and "private config" not in response.text


async def test_https_ft_transport_preserves_scheme_after_canonicalization(tasks):
    with tenant_execution_scope(60):
        async with tasks.sessions() as session:
            server = await ServerDao.find_server(60)
            server.sft_endpoint = "https://TRAINING-60.test:443/some-path"
            session.add(server)
            await session.commit()
    result(await tasks.client.post("/api/v1/finetune/job", json=payload()))
    assert service.SFTBackend.create_job.call_args.kwargs["host"] == "https://training-60.test"
