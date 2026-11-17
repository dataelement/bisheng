from types import SimpleNamespace

import pytest

from bisheng.common.errcode.finetune import InvalidDatasetPackageError
from bisheng.finetune.domain.models.finetune import Finetune, TrainMethod
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.sft_backend import SFTBackend
from bisheng.finetune.schemas import FinetunePreflightReq

CAPABILITY = {
    "capability_id": "qwen2.5-1.5b-instruct-text-lora-20261030",
    "model_name": "Qwen2.5-1.5B-Instruct",
    "input_types": ["text"],
    "training_methods": ["lora"],
    "validation_status": "gpu_smoke_passed",
}


@pytest.mark.asyncio
async def test_capabilities_join_exact_registered_model(monkeypatch):
    server = SimpleNamespace(id=7, sft_endpoint="http://ft:8000")
    model = SimpleNamespace(id=42, model="Qwen2.5-1.5B-Instruct")
    monkeypatch.setattr(FinetuneService, "get_sft_server", classmethod(lambda cls, server_id: _async(server)))
    monkeypatch.setattr(
        SFTBackend,
        "get_capabilities",
        classmethod(lambda cls, host: _async((True, {"contract_version": 2, "models": [CAPABILITY]}))),
    )
    from bisheng.finetune.domain.models.model_deploy import ModelDeployDao

    monkeypatch.setattr(ModelDeployDao, "find_model_by_server", classmethod(lambda cls, server_id: _async([model])))

    result = await FinetuneService.get_capabilities(7)
    assert result["models"][0]["base_model_id"] == 42
    assert result["models"][0]["registered"] is True


@pytest.mark.asyncio
async def test_preflight_sends_exact_capability(monkeypatch):
    server = SimpleNamespace(id=7, sft_endpoint="http://ft:8000")
    model = SimpleNamespace(id=42, model="Qwen2.5-1.5B-Instruct", server="7")
    monkeypatch.setattr(FinetuneService, "get_sft_server", classmethod(lambda cls, server_id: _async(server)))
    monkeypatch.setattr(
        FinetuneService,
        "get_capabilities",
        classmethod(lambda cls, server_id: _async({"models": [{**CAPABILITY, "base_model_id": 42}]})),
    )
    from bisheng.finetune.domain.models.model_deploy import ModelDeployDao

    monkeypatch.setattr(ModelDeployDao, "find_model", classmethod(lambda cls, model_id: _async(model)))
    monkeypatch.setattr(
        SFTBackend, "preflight", classmethod(lambda cls, host, params: _async((True, {"passed": True, "checks": []})))
    )
    request = FinetunePreflightReq(
        server=7,
        base_model=42,
        capability_id=CAPABILITY["capability_id"],
        data_type="text",
        method=TrainMethod.LORA,
        parameters={"max_steps": 4},
    )
    assert (await FinetuneService.preflight(request))["passed"] is True


def test_legacy_task_fields_remain_nullable():
    task = Finetune(base_model_name="legacy", model_name="legacy-output", extra_params={})
    assert task.data_type is None
    assert task.capability_snapshot is None


def test_contract_v2_accepts_matching_validated_dataset():
    task = Finetune(
        train_data=[{"url": "train.json"}],
        preset_data=[],
        data_type="text",
        dataset_report={"files": [{"data_type": "text"}]},
        extra_params={"contract_version": 2},
    )
    assert FinetuneService.validate_params(task) is None


def test_contract_v2_rejects_dataset_modality_mismatch():
    task = Finetune(
        train_data=[{"url": "train.zip"}],
        preset_data=[],
        data_type="image_text",
        dataset_report={"files": [{"data_type": "text"}]},
        extra_params={"contract_version": 2},
    )
    with pytest.raises(InvalidDatasetPackageError):
        FinetuneService.validate_params(task)


async def _async(value):
    return value
