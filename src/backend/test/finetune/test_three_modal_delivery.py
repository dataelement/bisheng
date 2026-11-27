import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.finetune import FinetuneInferenceValidationError, InvalidDatasetPackageError
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneDao
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository
from bisheng.finetune.domain.services.dataset_validation import inspect_package, validate_records
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.sft_backend import SFTBackend
from bisheng.finetune.schemas import FinetuneCreateReq, FinetuneInferenceReq
from bisheng.finetune.utils import parse_server_host


def package(records, media=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("train.json", json.dumps(records))
        for path, value in (media or {}).items():
            archive.writestr(path, value)
    return buffer.getvalue()


def test_text_zip_and_messages_work_without_media():
    records = [{"messages": [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}]}]
    assert inspect_package(package(records)) == ("text", 1, 0)


def test_video_upload_records_structural_scope():
    records = [
        {
            "messages": [{"role": "user", "content": "<video>Question"}, {"role": "assistant", "content": "Answer"}],
            "videos": ["videos/a.mp4"],
        }
    ]
    # Only the FT worker claims codec validation; this layer checks MP4 structure.
    assert inspect_package(package(records, {"videos/a.mp4": b"\0\0\0\x20ftypisom"})) == ("video_text", 1, 1)


@pytest.mark.parametrize(
    "record",
    [
        {"messages": [{"role": "user", "content": "No answer"}]},
        {"messages": [{"role": "user", "content": "<image>Missing"}, {"role": "assistant", "content": "Answer"}]},
        {"messages": ["invalid", {}]},
        {"instruction": "a", "output": "b", "audios": ["a.wav"]},
    ],
)
def test_malformed_or_audio_records_fail(record):
    with pytest.raises(ValueError):
        validate_records([record])


def test_audio_request_is_not_an_available_modality():
    with pytest.raises(ValidationError):
        FinetuneCreateReq(server=1, base_model=1, model_name="audio", method="lora", data_type="audio_text")


def test_https_is_kept_while_the_address_is_canonicalized_to_its_origin():
    # Upstream compares FT owners by canonical origin, so a path after the host is not part of the address.
    assert parse_server_host("https://Trainer.example:443/ft/") == "https://trainer.example"
    with pytest.raises(ValueError):
        parse_server_host("file:///etc/passwd")


async def test_creation_reloads_authoritative_dataset_report(monkeypatch):
    record = SimpleNamespace(
        id="version",
        name="train.zip",
        url="stored",
        purpose="training",
        report={"data_type": "video_text", "samples": 6, "sha256": "actual", "validated": True},
    )
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=record))
    monkeypatch.setattr(
        DatasetCatalogRepository,
        "find_url",
        AsyncMock(
            return_value=SimpleNamespace(id="catalog", version_id="version", data_type="video_text", name="train.zip")
        ),
    )
    task = Finetune(
        extra_params={"contract_version": 2},
        data_type="video_text",
        train_data=[{"url": "stored", "name": "fake", "num": 999}],
        dataset_report={"files": [{"sha256": "fake"}]},
    )
    await FinetuneService.validate_uploaded_datasets(task)
    assert task.dataset_report["files"][0]["sha256"] == "actual"
    assert task.train_data[0]["num"] == 6


async def test_arbitrary_or_cross_tenant_dataset_is_rejected(monkeypatch):
    monkeypatch.setattr(DatasetCatalogRepository, "find_url", AsyncMock(return_value=None))
    task = Finetune(extra_params={"contract_version": 2}, data_type="text", train_data=[{"url": "someone-elses-file"}])
    with pytest.raises(InvalidDatasetPackageError):
        await FinetuneService.validate_uploaded_datasets(task)


async def test_inference_keeps_both_real_outputs(monkeypatch):
    task = SimpleNamespace(
        status=4,
        artifact_report={"complete": True},
        data_type="text",
        sft_endpoint="http://trainer:8000",
        inference_validation={"baseline": {"answer": "base"}},
    )
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(FinetuneDao, "update_job", AsyncMock())
    monkeypatch.setattr(
        SFTBackend, "validate_inference", AsyncMock(return_value=(True, {"answer": "adapter", "completed": True}))
    )
    result = await FinetuneService.validate_inference("job", FinetuneInferenceReq(prompt="new question"))
    assert result["answer"] == "adapter"
    assert task.inference_validation["baseline"]["answer"] == "base"
    assert task.inference_validation["adapter"]["answer"] == "adapter"


async def test_inference_rejects_unregistered_media_url(monkeypatch):
    task = SimpleNamespace(status=4, artifact_report={"complete": True}, data_type="video_text")
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_url", AsyncMock(return_value=None))
    with pytest.raises(FinetuneInferenceValidationError):
        await FinetuneService.validate_inference(
            "job", FinetuneInferenceReq(prompt="question", media_url="http://internal/")
        )


async def test_log_read_failure_preserves_completed_state(monkeypatch):
    task = SimpleNamespace(
        id="job",
        status=1,
        sft_endpoint="http://ft",
        extra_params={"contract_version": 2},
        stage="training",
        reason="",
        artifact_report=None,
        report=None,
        dataset_report=None,
    )
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(
        SFTBackend,
        "get_job_status",
        AsyncMock(
            return_value=(
                True,
                {
                    "status": "FINISHED",
                    "stage": "completed",
                    "artifacts": {"complete": True},
                    "config": {"max_steps": 12},
                },
            )
        ),
    )
    monkeypatch.setattr(SFTBackend, "get_job_log", AsyncMock(return_value=(False, "temporary read failure")))
    monkeypatch.setattr(SFTBackend, "get_job_metrics", AsyncMock(return_value=(True, {"report": {"loss": 1.0}})))
    save = AsyncMock()
    monkeypatch.setattr(FinetuneDao, "update_job", save)
    assert await FinetuneService.sync_job_status(task, "http://ft") is True
    assert task.status == 4
    assert task.report["train_config"]["max_steps"] == 12
    save.assert_awaited_once()


def test_non_json_log_lines_do_not_crash_details():
    assert FinetuneService.parse_log_data('Loading model\n{"current_steps": 3, "loss": 1.2}\n') == [
        {"step": 3, "loss": 1.2}
    ]


def test_legacy_text_command_keeps_original_contract(monkeypatch):
    from bisheng.finetune.domain.services import finetune as module

    storage = SimpleNamespace(get_share_link_sync=lambda url, clear_host: f"https://storage/{url}")
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    task = Finetune(
        model_name="legacy-v1",
        extra_params={"gpus": "0", "num_train_epochs": 3},
        method="lora",
        root_model_name="legacy-model",
        train_data=[{"name": "train.json", "url": "old-file", "num": 20}],
    )
    assert FinetuneService.validate_params(task) is None
    params = FinetuneService.parse_command_params(task, SimpleNamespace(model="legacy-model"))
    assert params["dataset"] == "https://storage/old-file"
    assert params["each_max_samples"] == "20"
    assert params["model_template"] == "legacy-model"
    assert params["num_train_epochs"] == 3


def test_v2_forwards_all_parameters_without_legacy_limits(monkeypatch):
    from bisheng.finetune.domain.services import finetune as module

    storage = SimpleNamespace(get_share_link_sync=lambda url, clear_host: "https://storage/train.zip")
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: storage)
    requested = {
        "contract_version": 2,
        "capability_id": "video",
        "max_steps": 12,
        "num_train_epochs": 2,
        "per_device_train_batch_size": 2,
        "gradient_accumulation_steps": 4,
        "cutoff_len": 1024,
        "lora_rank": 16,
        "learning_rate": 0.0002,
    }
    task = Finetune(
        extra_params=requested,
        data_type="video_text",
        method="lora",
        train_data=[{"name": "train.zip", "url": "stored", "num": 6}],
    )
    params = FinetuneService.parse_command_params(task, SimpleNamespace(model="Qwen2.5-VL-3B-Instruct"))
    assert all(params[key] == value for key, value in requested.items())
    assert params["data_type"] == "video_text"
    assert "each_max_samples" not in params
    assert "model_template" not in params


async def test_cancel_requires_remote_confirmation(monkeypatch):
    from bisheng.common.errcode.finetune import CancelJobError

    task = SimpleNamespace(status=1, sft_endpoint="http://ft", extra_params={"contract_version": 2})
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(SFTBackend, "cancel_job", AsyncMock(return_value=(True, {})))
    monkeypatch.setattr(SFTBackend, "get_job_status", AsyncMock(return_value=(True, {"status": "RUNNING"})))
    with pytest.raises(CancelJobError):
        await FinetuneService.cancel_job("job", SimpleNamespace(user_name="admin"))
    assert task.status == 1


async def test_network_outage_preserves_last_training_state(monkeypatch):
    task = SimpleNamespace(id="job", status=1, stage="training", reason="", sft_endpoint="http://ft")
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(SFTBackend, "get_job_status", AsyncMock(side_effect=TimeoutError("timeout")))
    assert await FinetuneService.sync_job_status(task, "http://ft") is False
    assert task.status == 1


def test_service_registration_cannot_override_tenant():
    from bisheng.finetune.domain.models.server import Server, ServerCreate

    request = ServerCreate(server="customer", endpoint="", sft_endpoint="https://trainer.example/", tenant_id=99)
    # The add endpoint always stamps the current tenant over whatever the body carried.
    registered = Server.model_validate(request, update={"tenant_id": 7})
    assert registered.sft_endpoint == "https://trainer.example"
    assert registered.tenant_id == 7
    with pytest.raises(ValidationError):
        ServerCreate(server="test", endpoint="", sft_endpoint="file:///etc/passwd")


def test_dataset_query_filters_another_tenant_and_parent_catalog():
    from sqlalchemy import create_engine
    from sqlmodel import Session, select

    from bisheng.core.context.tenant import (
        bypass_tenant_filter,
        current_tenant_id,
        strict_tenant_filter,
        visible_tenant_ids,
    )
    from bisheng.core.database.tenant_filter import register_tenant_filter_events
    from bisheng.finetune.domain.models.dataset import FinetuneDataset

    register_tenant_filter_events()
    engine = create_engine("sqlite://")
    FinetuneDataset.__table__.create(engine)
    with bypass_tenant_filter(), Session(engine) as session:
        for tid in [1, 2, 3]:
            session.add(
                FinetuneDataset(
                    id=str(tid), name="data", url=f"tenant-{tid}", user_id=tid, tenant_id=tid, report={"samples": 1}
                )
            )
        session.commit()
    token = current_tenant_id.set(2)
    visible_token = visible_tenant_ids.set(frozenset({1, 2}))
    try:
        with strict_tenant_filter(), Session(engine) as session:
            assert [item.id for item in session.exec(select(FinetuneDataset)).all()] == ["2"]
    finally:
        current_tenant_id.reset(token)
        visible_tenant_ids.reset(visible_token)
        engine.dispose()


async def test_async_cancel_acceptance_does_not_claim_process_stopped(monkeypatch):
    task = SimpleNamespace(
        status=1, stage="training", log_path="old-log", sft_endpoint="http://ft", extra_params={"contract_version": 2}
    )
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(SFTBackend, "cancel_job", AsyncMock(return_value=(True, {"status": "CANCELLING"})))
    query = AsyncMock()
    save = AsyncMock()
    monkeypatch.setattr(SFTBackend, "get_job_status", query)
    monkeypatch.setattr(FinetuneDao, "update_job", save)
    result = await FinetuneService.cancel_job("job", SimpleNamespace(user_name="admin"))
    assert result.status == 1
    assert result.stage == "cancelling"
    assert result.log_path == "old-log"
    query.assert_not_awaited()
    save.assert_awaited_once()


async def test_cancelled_sync_retries_final_log_if_fetch_failed(monkeypatch):
    task = SimpleNamespace(
        id="job",
        status=1,
        stage="cancelling",
        log_path="old-log",
        reason="",
        extra_params={"contract_version": 2},
        sft_endpoint="http://ft",
    )
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(
        SFTBackend, "get_job_status", AsyncMock(return_value=(True, {"status": "CANCELLED", "stage": "cancelling"}))
    )
    monkeypatch.setattr(SFTBackend, "get_job_log", AsyncMock(return_value=(False, "temporarily unavailable")))
    monkeypatch.setattr(SFTBackend, "get_job_metrics", AsyncMock(return_value=(False, "not ready")))
    monkeypatch.setattr(FinetuneDao, "update_job", AsyncMock())
    assert await FinetuneService.sync_job_status(task, "http://ft") is True
    assert task.status == 3
    assert task.stage == "cancelled"
    assert task.log_path == ""
    # Terminal status with an empty log pointer remains eligible for a later refresh.
    assert await FinetuneService.sync_job_status(task, "http://ft") is True
    assert SFTBackend.get_job_status.await_count == 2


@pytest.mark.parametrize("status,http_status,allowed", [(2, 404, True), (1, 404, False), (2, 500, False)])
async def test_cleanup_requires_explicit_404_and_non_running_job(monkeypatch, status, http_status, allowed):
    from bisheng.common.errcode.finetune import DeleteJobError

    task = SimpleNamespace(status=status, id="job", model_name="model", sft_endpoint="http://ft", model_dump=lambda: {})
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(FinetuneService, "delete_published_model", AsyncMock(return_value="model"))
    monkeypatch.setattr(
        SFTBackend,
        "delete_job",
        AsyncMock(return_value=(False, {"http_status": http_status, "detail": "not available"})),
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(FinetuneDao, "delete_job", cleanup)
    monkeypatch.setattr(FinetuneService, "delete_job_log", AsyncMock())
    if allowed:
        assert await FinetuneService.delete_job("job", SimpleNamespace(user_name="admin")) is task
        cleanup.assert_awaited_once_with(task)
    else:
        with pytest.raises(DeleteJobError):
            await FinetuneService.delete_job("job", SimpleNamespace(user_name="admin"))
        cleanup.assert_not_awaited()


async def test_delete_network_failure_never_means_remote_missing(monkeypatch):
    task = SimpleNamespace(status=2, id="job", model_name="model", sft_endpoint="http://ft")
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(FinetuneService, "delete_published_model", AsyncMock(return_value="model"))
    monkeypatch.setattr(SFTBackend, "delete_job", AsyncMock(side_effect=TimeoutError("connection interrupted")))
    cleanup = AsyncMock()
    monkeypatch.setattr(FinetuneDao, "delete_job", cleanup)
    with pytest.raises(TimeoutError):
        await FinetuneService.delete_job("job", SimpleNamespace(user_name="admin"))
    cleanup.assert_not_awaited()


async def test_http_adapter_preserves_transport_404_only_when_requested():
    response = SimpleNamespace(
        status=404, content=SimpleNamespace(read=AsyncMock(return_value=b'{"detail":"not found"}'))
    )
    assert await SFTBackend.handle_response(response, include_http_status=True) == (
        False,
        {"http_status": 404, "detail": '{"detail":"not found"}'},
    )
    assert await SFTBackend.handle_response(response) == (False, '{"detail":"not found"}')
