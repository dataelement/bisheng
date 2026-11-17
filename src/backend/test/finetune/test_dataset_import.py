import hashlib
import io
import json
import socket
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TrainFileNotExistError
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.finetune.domain.services import datasets, remote_dataset
from bisheng.finetune.domain.services.dataset_validation import inspect_package
from bisheng.finetune.domain.services.datasets import DatasetService
from bisheng.finetune.domain.services.remote_dataset import (
    RemoteDatasetError,
    assemble_remote_dataset,
    checked_endpoint,
    checked_remote_path,
)
from bisheng.finetune.schemas import DatasetImportReq


def request(**changes):
    values = {
        "name": "Customer dataset",
        "source": "s3",
        "data_type": "image_text",
        "connection": {
            "endpoint": "https://store.example",
            "bucket": "training",
            "access_key": "example-access",
            "secret_key": "example-private",
        },
        "manifest_path": "datasets/train.json",
        "media_root": "datasets/media",
    }
    values.update(changes)
    return DatasetImportReq(**values)


def records():
    return [
        {
            "messages": [{"role": "user", "content": "<image>What color?"}, {"role": "assistant", "content": "red"}],
            "images": ["images/a.png"],
        }
    ]


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


def content_reader(files):
    def read(path, remaining):
        data = files[path]
        if len(data) > remaining:
            raise RemoteDatasetError("over budget")
        return data

    return read


def test_remote_manifest_uses_one_media_root_and_preserves_every_sample():
    rows = records() * 3
    read = MagicMock(
        side_effect=content_reader(
            {"datasets/train.json": json.dumps(rows).encode(), "datasets/media/images/a.png": png()}
        )
    )
    result = assemble_remote_dataset(request(), read)
    assert inspect_package(result) == ("image_text", 3, 1)
    assert read.call_count == 2
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert json.loads(archive.read("train.json")) == rows


def test_local_jsonl_manifest_fetches_only_remote_media():
    req = request(manifest_path=None, manifest_text=json.dumps(records()[0]), manifest_filename="samples.jsonl")
    read = MagicMock(side_effect=content_reader({"datasets/media/images/a.png": png()}))
    assert inspect_package(assemble_remote_dataset(req, read)) == ("image_text", 1, 1)
    assert read.call_args.args[0] == "datasets/media/images/a.png"


def test_self_contained_remote_zip_does_not_fetch_extra_media():
    initial = assemble_remote_dataset(
        request(),
        content_reader({"datasets/train.json": json.dumps(records()).encode(), "datasets/media/images/a.png": png()}),
    )
    read = MagicMock(return_value=initial)
    assert assemble_remote_dataset(request(manifest_path="train.zip"), read) == initial
    read.assert_called_once()


def test_text_remote_json_becomes_reusable_zip():
    rows = [{"instruction": "Classify", "input": "printer", "output": "IT"}]
    result = assemble_remote_dataset(
        request(data_type="text", manifest_path="train.json"), content_reader({"train.json": json.dumps(rows).encode()})
    )
    assert inspect_package(result) == ("text", 1, 0)


@pytest.mark.parametrize(
    "path", ["../secret", "/data/../secret", "http://host/file", "a\\b", "file\r\nDELE /", "%00/../secret"]
)
def test_remote_paths_reject_traversal_and_command_injection(path):
    with pytest.raises(RemoteDatasetError):
        checked_remote_path(path)


def test_missing_media_names_sample_and_does_not_return_partial_version():
    def read(path, remaining):
        if path.endswith("train.json"):
            return json.dumps(records()).encode()
        raise RuntimeError("connector message with example-private")

    with pytest.raises(RemoteDatasetError) as captured:
        assemble_remote_dataset(request(), read)
    assert "Sample 1" in str(captured.value)
    assert "images/a.png" in str(captured.value)
    assert "example-private" not in str(captured.value)


def test_manifest_parse_error_does_not_drop_bad_lines():
    req = request(
        data_type="text",
        manifest_path=None,
        manifest_filename="train.jsonl",
        manifest_text='{"instruction":"a","output":"b"}\nnot-json',
    )
    with pytest.raises(RemoteDatasetError, match="Invalid manifest"):
        assemble_remote_dataset(req, MagicMock())


def test_credentials_are_excluded_from_representation_and_serialization():
    req = request()
    assert "example-private" not in repr(req)
    assert "example-private" not in req.model_dump_json()
    assert "secret_key" not in req.connection.model_dump()


async def test_malformed_import_does_not_send_credentials_to_legacy_422_handler():
    from starlette.requests import Request

    from bisheng.finetune.api.finetune import parse_dataset_import

    payload = request().model_dump()
    payload["connection"] = {"password": "example-private"}  # Missing endpoint: input contains a secret.
    receive = AsyncMock(return_value={"type": "http.request", "body": json.dumps(payload).encode()})
    incoming = Request({"type": "http", "method": "POST", "path": "/datasets/import"}, receive)
    with pytest.raises(InvalidDatasetPackageError) as captured:
        await parse_dataset_import(incoming)
    assert "connection.endpoint" in str(captured.value)
    assert "example-private" not in str(captured.value)


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "::1", "::ffff:169.254.169.254"])
def test_block_metadata_and_loopback_endpoints(monkeypatch, address):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    )
    with pytest.raises(RemoteDatasetError):
        checked_endpoint("https://store.example", "s3")


def test_enterprise_private_network_endpoint_is_allowed(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 9000))]
    )
    parsed, port, address = checked_endpoint("http://store.example:9000", "s3")
    assert (parsed.hostname, port, address) == ("store.example", 9000, "192.168.1.10")


@pytest.mark.parametrize(
    "endpoint",
    ["file:///tmp/model", "https://key:password@store.example", "https://store.example/path", "sftp://store.example"],
)
def test_protocol_and_endpoint_scope_are_explicit(endpoint):
    with pytest.raises(RemoteDatasetError):
        checked_endpoint(endpoint, "s3")


def test_s3_error_never_exposes_connector_credentials(monkeypatch):
    monkeypatch.setattr(
        remote_dataset,
        "checked_endpoint",
        lambda *a: (
            SimpleNamespace(netloc="store.example", hostname="store.example", scheme="https"),
            443,
            "192.168.1.10",
        ),
    )
    client = MagicMock()
    client.get_object.side_effect = RuntimeError("example-private")
    monkeypatch.setattr(remote_dataset, "Minio", MagicMock(return_value=client))
    with pytest.raises(RemoteDatasetError) as captured:
        with remote_dataset.remote_reader(request()) as read:
            read("train.json", 100)
    assert "example-private" not in str(captured.value)


async def test_import_uses_existing_upload_validation_and_persistence(monkeypatch):
    monkeypatch.setattr(datasets, "import_remote_bytes", lambda req: b"package")

    async def upload(files, preset, user):
        assert await files[0].read() == b"package"
        assert preset is False
        return [{"id": "immutable-version", "url": "stored.zip", "dataset_report": {"samples": 3}}]

    monkeypatch.setattr(datasets.FinetuneFileService, "upload_file", upload)
    result = await DatasetService.import_version(request(), SimpleNamespace(user_id=1))
    assert result["id"] == "immutable-version"
    assert "connection" not in result


async def test_unknown_or_other_tenant_version_cannot_be_previewed(monkeypatch):
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=None))
    with pytest.raises(TrainFileNotExistError):
        await DatasetService.preview("other-tenant")


async def test_existing_version_preview_uses_authorized_same_origin_media(monkeypatch):
    raw = assemble_remote_dataset(
        request(),
        content_reader({"datasets/train.json": json.dumps(records()).encode(), "datasets/media/images/a.png": png()}),
    )
    version = SimpleNamespace(
        id="v1",
        purpose="training",
        url="stored.zip",
        report={"data_type": "image_text", "sha256": hashlib.sha256(raw).hexdigest()},
    )
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=version))
    monkeypatch.setattr(
        datasets, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(get_object=AsyncMock(return_value=raw)))
    )
    preview = await DatasetService.preview("v1")
    assert preview["samples"][0]["media"][0]["url"].startswith("/api/v1/finetune/datasets/v1/media?")
    content, mime = await DatasetService.media("v1", "images/a.png")
    assert (content, mime) == (png(), "image/png")
    with pytest.raises(TrainFileNotExistError):
        await DatasetService.media("v1", "train.json")


async def test_changed_stored_bytes_are_not_previewed_as_original_version(monkeypatch):
    version = SimpleNamespace(id="v1", purpose="training", url="stored.zip", report={"sha256": "different"})
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=version))
    monkeypatch.setattr(
        datasets,
        "get_minio_storage",
        AsyncMock(return_value=SimpleNamespace(get_object=AsyncMock(return_value=b"changed"))),
    )
    with pytest.raises(InvalidDatasetPackageError):
        await DatasetService.preview("v1")


def test_s3_reads_are_bounded_and_connections_are_closed(monkeypatch):
    monkeypatch.setattr(
        remote_dataset,
        "checked_endpoint",
        lambda *a: (
            SimpleNamespace(netloc="store.example", hostname="store.example", scheme="https"),
            443,
            "192.168.1.10",
        ),
    )
    body = MagicMock()
    body.read.side_effect = [b"large"]
    client = MagicMock()
    client.get_object.return_value = body
    monkeypatch.setattr(remote_dataset, "Minio", MagicMock(return_value=client))
    with pytest.raises(RemoteDatasetError, match="budget"):
        with remote_dataset.remote_reader(request()) as read:
            read("train.json", 4)
    body.close.assert_called_once()
    body.release_conn.assert_called_once()


def test_s3_dns_pin_preserves_host_and_blocks_redirects(monkeypatch):
    connect = MagicMock(return_value=object())
    monkeypatch.setattr("urllib3.util.connection.create_connection", connect)
    manager = remote_dataset.pinned_http_pool("store.example", "192.168.1.10", 9000)
    pool = manager.connection_from_url("http://store.example:9000")
    connection = pool._new_conn()
    connection._new_conn()
    assert connection.host == "store.example"
    assert connect.call_args.args[0] == ("192.168.1.10", 9000)
    other_pool = manager.connection_from_url("http://169.254.169.254:9000")
    with pytest.raises(RemoteDatasetError):
        other_pool._new_conn()._new_conn()
    manager.clear()


def test_ftp_uses_one_connection_and_bounded_relative_retrieval(monkeypatch):
    monkeypatch.setattr(
        remote_dataset,
        "checked_endpoint",
        lambda *a: (SimpleNamespace(netloc="ftp.example", hostname="ftp.example", scheme="ftp"), 21, "192.168.1.10"),
    )
    client = MagicMock()
    # Keep isinstance(..., FTP_TLS) meaningful while replacing only the plain FTP constructor.
    monkeypatch.setattr(remote_dataset.ftplib, "FTP", MagicMock(return_value=client))
    monkeypatch.setattr(socket, "create_connection", MagicMock(return_value=MagicMock()))
    client.retrbinary.side_effect = lambda command, callback, blocksize: callback(b"content")
    req = request(
        source="ftp", connection={"endpoint": "ftp://ftp.example", "username": "reader", "password": "example-private"}
    )
    with remote_dataset.remote_reader(req) as read:
        assert read("customer/train.json", 50) == b"content"
    assert client.retrbinary.call_args.args[0] == "RETR customer/train.json"
    client.close.assert_called_once()
