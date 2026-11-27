from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.finetune import FinetuneDatasetTransferError
from bisheng.finetune.domain.models.finetune import FinetuneDao
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.finetune.domain.services import transfer
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.sft_backend import SFTBackend
from bisheng.finetune.schemas import FinetuneInferenceReq

SHA = "a" * 64
SECRET = "example-private"  # placeholder source password, never a real credential


class _Object:
    def __init__(self, content: bytes):
        self.content = content
        self.closed = False

    def read(self, size):
        chunk, self.content = self.content[:size], self.content[size:]
        return chunk

    def close(self):
        self.closed = True

    def release_conn(self):
        pass


@pytest.fixture
def storage(monkeypatch):
    stored = _Object(b"dataset-bytes")
    fake = SimpleNamespace(
        get_share_link_sync=lambda name, clear_host: f"http://10.0.0.5:9000/bisheng/{name}?sig=1",
        download_object_sync=lambda bucket, name: stored,
    )
    monkeypatch.setattr(transfer, "get_minio_storage_sync", lambda: fake)
    return stored


async def _collect(chunks):
    return b"".join([chunk async for chunk in chunks])


async def test_reachable_storage_keeps_pull(storage, monkeypatch):
    monkeypatch.setattr(SFTBackend, "probe_url", AsyncMock(return_value=(True, {"reachable": True})))
    push = AsyncMock()
    monkeypatch.setattr(SFTBackend, "push_file", push)
    reference, mode = await transfer.reference_for("http://ft", "finetune/train.zip", SHA)
    assert (reference, mode) == ("http://10.0.0.5:9000/bisheng/finetune/train.zip?sig=1", "pull")
    push.assert_not_awaited()


async def test_unreachable_storage_streams_the_object_to_ft(storage, monkeypatch):
    monkeypatch.setattr(SFTBackend, "probe_url", AsyncMock(return_value=(True, {"reachable": False})))
    received = {}

    async def push(host, sha256, chunks):
        received.update(host=host, sha256=sha256, body=await _collect(chunks))
        return True, {"sha256": sha256}

    monkeypatch.setattr(SFTBackend, "push_file", push)
    assert await transfer.reference_for("http://ft", "finetune/train.zip", SHA) == ("ft-file://" + SHA, "push")
    assert received == {"host": "http://ft", "sha256": SHA, "body": b"dataset-bytes"}
    assert storage.closed


async def test_ft_without_probe_endpoint_stays_on_pull(storage, monkeypatch):
    monkeypatch.setattr(
        SFTBackend, "probe_url", AsyncMock(return_value=(False, {"http_status": 404, "detail": "Not Found"}))
    )
    assert (await transfer.reference_for("http://ft", "train.zip", SHA))[1] == "pull"


async def test_unsignable_link_or_failed_probe_falls_back_to_push(storage, monkeypatch):
    storage_without_signing = SimpleNamespace(
        get_share_link_sync=lambda name, clear_host: (_ for _ in ()).throw(OSError("sharepoint unreachable")),
        download_object_sync=lambda bucket, name: _Object(b"x"),
    )
    monkeypatch.setattr(transfer, "get_minio_storage_sync", lambda: storage_without_signing)
    monkeypatch.setattr(SFTBackend, "push_file", AsyncMock(return_value=(True, {})))
    assert (await transfer.reference_for("http://ft", "train.zip", SHA))[1] == "push"
    monkeypatch.setattr(
        transfer,
        "get_minio_storage_sync",
        lambda: SimpleNamespace(
            get_share_link_sync=lambda name, clear_host: "http://link", download_object_sync=lambda b, n: _Object(b"x")
        ),
    )
    monkeypatch.setattr(SFTBackend, "probe_url", AsyncMock(side_effect=TimeoutError("probe timeout")))
    assert (await transfer.reference_for("http://ft", "train.zip", SHA))[1] == "push"


async def test_rejected_push_is_a_transfer_error(storage, monkeypatch):
    monkeypatch.setattr(SFTBackend, "probe_url", AsyncMock(return_value=(True, {"reachable": False})))
    monkeypatch.setattr(SFTBackend, "push_file", AsyncMock(return_value=(False, "disk full")))
    with pytest.raises(FinetuneDatasetTransferError):
        await transfer.reference_for("http://ft", "train.zip", SHA)


def test_v2_command_leaves_dataset_for_transfer(monkeypatch):
    from bisheng.finetune.domain.models.finetune import Finetune
    from bisheng.finetune.domain.services import finetune as module

    def unexpected(*args, **kwargs):
        raise AssertionError("v2 must not sign the dataset link before choosing pull or push")

    monkeypatch.setattr(module, "get_minio_storage_sync", unexpected)
    task = Finetune(
        extra_params={"contract_version": 2, "capability_id": "text"},
        data_type="text",
        method="lora",
        train_data=[{"name": "train.json", "url": "stored", "num": 6}],
    )
    assert FinetuneService.parse_command_params(task, SimpleNamespace(model="Qwen3-0.6B"))["dataset"] == ""


async def test_validation_media_is_pushed_and_recorded(monkeypatch):
    task = SimpleNamespace(
        status=4,
        artifact_report={"complete": True},
        data_type="image_text",
        sft_endpoint="http://trainer:8000",
        inference_validation=None,
    )
    media = SimpleNamespace(
        url="finetune/validation/1/job/new.png",
        purpose="inference",
        job_id="job",
        report={"data_type": "image_text", "sha256": SHA},
    )
    monkeypatch.setattr(FinetuneService, "_get_job", AsyncMock(return_value=task))
    monkeypatch.setattr(FinetuneDao, "update_job", AsyncMock())
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_url", AsyncMock(return_value=media))
    reference = AsyncMock(return_value=("ft-file://" + SHA, "push"))
    monkeypatch.setattr(transfer, "reference_for", reference)
    infer = AsyncMock(return_value=(True, {"answer": "a cat", "completed": True}))
    monkeypatch.setattr(SFTBackend, "validate_inference", infer)
    result = await FinetuneService.validate_inference(
        "job", FinetuneInferenceReq(prompt="what is shown", media_url=media.url)
    )
    reference.assert_awaited_once_with("http://trainer:8000", media.url, SHA)
    assert infer.await_args.args[2]["media_url"] == "ft-file://" + SHA
    assert result["transfer"] == "push"
    assert task.inference_validation["adapter"]["transfer"] == "push"


REMOTE = {
    "type": "sftp",
    "endpoint": "sftp://files.example",
    "username": "reader",
    "host_fingerprint": None,
    "layout": "manifest",
    "path": "datasets/train.json",
    "media_root": "datasets",
    "probe": "datasets/images/a.png",
}


def test_remote_source_adds_this_jobs_secrets_and_requires_an_sftp_password():
    from bisheng.common.errcode.finetune import FinetuneDatasetSourceError
    from bisheng.finetune.schemas import DatasetCredentials

    source = transfer.remote_source(REMOTE, DatasetCredentials(password=SECRET))
    assert source["password"] == "example-private" and source["probe"] == "datasets/images/a.png"
    assert "layout" not in source and "path" not in source
    assert "password" not in REMOTE
    with pytest.raises(FinetuneDatasetSourceError, match="SFTP password"):
        transfer.remote_source(REMOTE, None)
    assert "password" not in transfer.remote_source({**REMOTE, "type": "ftp"}, DatasetCredentials(password=""))


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ((False, {"http_status": 404, "detail": "Not Found"}), "cannot read data sources directly"),
        (
            (False, {"http_status": 422, "detail": '{"detail": "cannot connect to the SFTP data source"}'}),
            "cannot connect to the SFTP data source",
        ),
    ],
)
async def test_source_check_failures_name_the_reason(monkeypatch, answer, message):
    from bisheng.common.errcode.finetune import FinetuneDatasetSourceError

    monkeypatch.setattr(SFTBackend, "check_source", AsyncMock(return_value=answer))
    with pytest.raises(FinetuneDatasetSourceError, match=message):
        await transfer.check_source("http://ft", {**REMOTE, "password": "example-private"})


async def test_unreachable_ft_during_source_check_does_not_log_the_request(monkeypatch):
    from loguru import logger

    from bisheng.common.errcode.finetune import FinetuneDatasetSourceError

    logged = []
    sink = logger.add(lambda message: logged.append(str(message)))
    monkeypatch.setattr(SFTBackend, "check_source", AsyncMock(side_effect=OSError("example-private")))
    try:
        with pytest.raises(FinetuneDatasetSourceError) as raised:
            await transfer.check_source("http://ft", {**REMOTE, "password": "example-private"})
    finally:
        logger.remove(sink)
    assert "example-private" not in str(raised.value) + "".join(logged)


def test_job_request_never_serializes_dataset_credentials():
    from bisheng.finetune.schemas import FinetuneCreateReq

    request = FinetuneCreateReq(
        server=1, base_model=2, model_name="m", method="lora", dataset_credentials={"password": "example-private"}
    )
    assert request.dataset_credentials.password.get_secret_value() == "example-private"
    assert "dataset_credentials" not in request.model_dump()
    assert "example-private" not in repr(request) + request.model_dump_json()


async def test_malformed_job_request_does_not_echo_credentials():
    import json

    from starlette.requests import Request

    from bisheng.common.errcode.finetune import InvalidExtraParamsError
    from bisheng.finetune.api.finetune import parse_create_job

    body = json.dumps({"model_name": "m", "dataset_credentials": {"password": "example-private"}}).encode()
    receive = AsyncMock(return_value={"type": "http.request", "body": body})
    incoming = Request({"type": "http", "method": "POST", "path": "/finetune/job"}, receive)
    with pytest.raises(InvalidExtraParamsError) as raised:
        await parse_create_job(incoming)
    assert "server" in str(raised.value) and "example-private" not in str(raised.value)


async def test_remote_version_job_sends_the_source_to_ft_and_stores_no_secret(monkeypatch):
    from bisheng.finetune.domain.models.finetune import Finetune
    from bisheng.finetune.domain.services import finetune as module
    from bisheng.finetune.schemas import DatasetCredentials

    task = Finetune(
        server=1,
        base_model=2,
        model_name="m",
        method="lora",
        data_type="image_text",
        extra_params={"contract_version": 2, "capability_id": "vl"},
        train_data=[{"url": "x.plan.json"}],
    )
    report = {"data_type": "image_text", "sha256": SHA, "delivery": "remote", "remote": REMOTE, "samples": 1}

    async def validate(finetune, user=None):
        finetune.dataset_report = {"files": [report]}

    monkeypatch.setattr(FinetuneService, "validate_uploaded_datasets", validate)
    monkeypatch.setattr(FinetuneService, "validate_params", lambda finetune: None)
    monkeypatch.setattr(
        FinetuneService,
        "get_sft_server",
        AsyncMock(
            return_value=SimpleNamespace(id=1, server="gpu", endpoint="http://rt", sft_endpoint="http://ft:8000")
        ),
    )
    monkeypatch.setattr(FinetuneService, "verify_job_model_name", AsyncMock())
    monkeypatch.setattr(
        module.ModelDeployDao, "find_model", AsyncMock(return_value=SimpleNamespace(model="VL", server="1"))
    )
    monkeypatch.setattr(FinetuneDao, "find_job_by_model_name", AsyncMock(return_value=None))
    monkeypatch.setattr(
        FinetuneService, "preflight", AsyncMock(return_value={"passed": True, "capability": {"id": "vl"}})
    )
    monkeypatch.setattr(FinetuneService, "parse_command_params", lambda finetune, model: {"dataset": ""})
    checked = AsyncMock()
    monkeypatch.setattr(transfer, "check_source", checked)
    monkeypatch.setattr(transfer, "reference_for", AsyncMock(return_value=("ft-file://" + SHA, "push")))
    saved = []
    monkeypatch.setattr(
        FinetuneDao, "insert_one", AsyncMock(side_effect=lambda job: saved.append(job.model_dump_json()) or job)
    )
    submitted = AsyncMock(return_value=(True, {}))
    monkeypatch.setattr(SFTBackend, "create_job", submitted)
    result = await FinetuneService.create_job(task, SimpleNamespace(user_id=1), DatasetCredentials(password=SECRET))
    params = submitted.await_args.kwargs["params"]
    assert params["dataset"] == "ft-file://" + SHA
    assert params["dataset_source"]["password"] == "example-private"
    assert checked.await_args.args[1]["password"] == "example-private"
    assert result.dataset_report["transfer"] == "source"
    assert saved and "example-private" not in saved[0]
