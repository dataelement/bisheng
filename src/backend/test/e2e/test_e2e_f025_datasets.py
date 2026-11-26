"""In-process HTTP E2E: real services/SQLite, isolated objects/cache, mocked admission and FT.

This verifies platform protocol and tenant/menu rules, not live login, MinIO or GPU training.
"""

import json
from unittest.mock import AsyncMock

from sqlalchemy import func
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.finetune.domain.models.dataset import FinetuneDataset
from bisheng.finetune.domain.models.preset_train import PresetTrain
from bisheng.finetune.domain.services import finetune as service
from bisheng.finetune.domain.services import task_uploads, transfer
from test.e2e.helpers.api import assert_resp_200
from test.finetune.test_dataset_admin_visibility import datasets as datasets
from test.finetune.test_dataset_menu_api import web as web
from test.finetune.test_finetune_menu_api import tasks as tasks
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter

PREFIX = "e2e-f025-dataset-"
TEXT = [{"messages": [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}]}]


async def test_catalog_conversion_preserves_original_and_deleted_data_stays_deleted(web):
    """AC-40, AC-41, AC-42, AC-43, AC-44: save, convert, filter, soft-delete, preserve versions."""
    raw = json.dumps(
        [{"instruction": "question", "input": "context", "output": "answer", "history": [["q0", "a0"]]}]
    ).encode()
    rejected = await web.client.post(
        "/api/v1/finetune/dataset-catalog/files",
        data={"name": PREFIX + "mismatch", "data_type": "image_text"},
        files={"files": ("old.json", raw)},
    )
    assert rejected.json()["status_code"] == 10129
    assert not web.objects.data
    task_denied = await web.client.post(
        "/api/v1/finetune/job/file", files={"files": ("text.json", json.dumps(TEXT).encode())}
    )
    assert task_denied.status_code == 403
    saved = assert_resp_200(
        await web.client.post(
            "/api/v1/finetune/dataset-catalog/files",
            data={"name": PREFIX + "legacy", "data_type": "legacy"},
            files={"files": ("old.json", raw)},
        )
    )
    assert saved["data_type"] == "legacy" and saved["version_id"] is None
    original = web.objects.data[web.objects.bucket, saved["url"]]
    converted = assert_resp_200(await web.client.post(f"/api/v1/finetune/dataset-catalog/{saved['id']}/convert"))
    assert converted["data_type"] == "text" and converted["source_dataset_id"] == saved["id"]
    assert web.objects.data[web.objects.bucket, saved["url"]] == original
    preview = assert_resp_200(await web.client.get(f"/api/v1/finetune/dataset-catalog/{converted['id']}/preview"))
    assert preview["samples"][0]["messages"][-2]["content"] == "question\n\ncontext"
    listing = assert_resp_200(
        await web.client.get("/api/v1/finetune/dataset-catalog", params={"data_type": "text", "keyword": PREFIX})
    )
    assert listing["total"] == 1 and listing["data"][0]["id"] == converted["id"]
    assert_resp_200(await web.client.delete(f"/api/v1/finetune/dataset-catalog/{converted['id']}"))
    assert (
        assert_resp_200(
            await web.client.get("/api/v1/finetune/dataset-catalog", params={"keyword": PREFIX, "data_type": "text"})
        )["total"]
        == 0
    )
    assert_resp_200(await web.client.delete(f"/api/v1/finetune/dataset-catalog/{saved['id']}"))


async def test_temporary_upload_creates_one_task_and_never_a_catalog_version(tasks, monkeypatch):
    """AC-45, AC-46, AC-47, AC-48, AC-51, AC-52: transient HTTP creation/retry and permissions."""

    async def counts():
        with tenant_execution_scope(60):
            async with tasks.sessions() as session:
                return (
                    await session.scalar(select(func.count(PresetTrain.id))),
                    await session.scalar(select(func.count(FinetuneDataset.id))),
                )

    before = await counts()
    capabilities = {
        "models": [
            {
                "capability_id": "test-text",
                "model_name": "base",
                "input_types": ["text"],
                "training_methods": ["lora"],
                "validation_status": "gpu_smoke_passed",
            }
        ]
    }
    monkeypatch.setattr(service.SFTBackend, "get_capabilities", AsyncMock(return_value=(True, capabilities)))
    monkeypatch.setattr(service.SFTBackend, "preflight", AsyncMock(return_value=(True, {"passed": True, "checks": []})))
    monkeypatch.setattr(transfer, "reference_for", AsyncMock(return_value=("ft-file://" + "a" * 64, "push")))
    upload = assert_resp_200(
        await tasks.client.post(
            "/api/v1/finetune/job/file", files={"files": (PREFIX + "temporary.json", json.dumps(TEXT).encode())}
        )
    )[0]
    assert upload["temporary"] and await counts() == before
    assert (
        assert_resp_200(await tasks.client.get(f"/api/v1/finetune/task-uploads/{upload['id']}/preview"))["samples"][0][
            "messages"
        ]
        == TEXT[0]["messages"]
    )
    body = {
        "contract_version": 2,
        "server": 60,
        "base_model": 60,
        "capability_id": "test-text",
        "model_name": "",
        "data_type": "text",
        "method": "lora",
        "extra_params": {},
        "train_data": [upload],
        "preset_data": [],
    }
    failed = await tasks.client.post("/api/v1/finetune/job", json=body)
    assert failed.json()["status_code"] == 10109
    body["model_name"] = "e2e-f025-dataset-quwe3-0.6b-001"
    first = assert_resp_200(await tasks.client.post("/api/v1/finetune/job", json=body))
    second = assert_resp_200(await tasks.client.post("/api/v1/finetune/job", json=body))
    assert first["id"] == second["id"] and await counts() == before
    service.SFTBackend.create_job.assert_awaited_once()
    assert first["transient_upload_id"] == upload["upload_id"]
    body["model_name"] += "-changed"
    assert (await tasks.client.post("/api/v1/finetune/job", json=body)).json()["status_code"] == 10135
    denied = await tasks.client.post(
        "/api/v1/finetune/dataset-catalog/files",
        data={"name": PREFIX + "denied", "data_type": "text"},
        files={"files": ("text.json", json.dumps(TEXT).encode())},
    )
    assert denied.status_code == 403
    cache = await task_uploads.get_redis_client()
    cache.store.clear()
    assert (await tasks.client.get(f"/api/v1/finetune/task-uploads/{upload['id']}/preview")).json()[
        "status_code"
    ] == 10134
    jobs = assert_resp_200(await tasks.client.get("/api/v1/finetune/job", params={"model_name": first["model_name"]}))
    assert jobs["data"][0]["train_data"] == first["train_data"]
    assert jobs["data"][0]["dataset_report"] == first["dataset_report"]
    body["model_name"] = first["model_name"]
    assert assert_resp_200(await tasks.client.post("/api/v1/finetune/job", json=body))["id"] == first["id"]
    service.SFTBackend.create_job.assert_awaited_once()
    tasks.user.user_id = 900
    assert (await tasks.client.get(f"/api/v1/finetune/task-uploads/{upload['id']}/preview")).json()[
        "status_code"
    ] == 10134
