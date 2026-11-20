import hashlib
import io
import json
import socket
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import paramiko
import pytest
from PIL import Image

from bisheng.common.errcode.finetune import InvalidDatasetPackageError, TrainFileNotExistError
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.finetune.domain.services import datasets, remote_dataset
from bisheng.finetune.domain.services.dataset_validation import inspect_package
from bisheng.finetune.domain.services.datasets import DatasetService
from bisheng.finetune.domain.services.remote_dataset import (
    RemoteDatasetError,
    build_remote_plan,
    checked_endpoint,
    checked_remote_path,
    public_source,
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


class FakeSession:
    def __init__(self, files):
        self.files = files
        self.reads = []

    def read(self, path, remaining):
        self.reads.append(path)
        data = self.files[path]
        if len(data) > remaining:
            raise RemoteDatasetError("over budget")
        return data

    def sizes(self, paths):
        return {path: len(self.files[path]) if path in self.files else None for path in paths}


def image_rows(count):
    return [
        {
            "messages": [{"role": "user", "content": "<image>What color?"}, {"role": "assistant", "content": "red"}],
            "images": [f"images/{index}.png"],
        }
        for index in range(count)
    ]


def test_remote_manifest_records_every_file_size_but_reads_only_preview_media():
    rows = image_rows(5)
    files = {"datasets/train.json": json.dumps(rows).encode()}
    files.update({f"datasets/media/images/{index}.png": png() for index in range(5)})
    session = FakeSession(files)
    plan, kept, preview, facts = build_remote_plan(request(), session)
    assert plan["layout"] == "manifest" and plan["records"] == rows == kept
    assert plan["files"] == [{"path": f"images/{index}.png", "size": len(png())} for index in range(5)]
    assert session.reads == ["datasets/train.json"] + [f"datasets/media/images/{index}.png" for index in range(3)]
    assert facts == {
        "samples": 5,
        "media": 5,
        "total_bytes": 5 * len(png()),
        "validation_stage": "manifest_checked",
        "preview_samples": 3,
    }
    with zipfile.ZipFile(io.BytesIO(preview)) as archive:
        assert json.loads(archive.read("train.json")) == rows[:3]
        assert sorted(archive.namelist()) == ["images/0.png", "images/1.png", "images/2.png", "train.json"]


def test_local_jsonl_manifest_reads_only_remote_media():
    req = request(manifest_path=None, manifest_text=json.dumps(records()[0]), manifest_filename="samples.jsonl")
    session = FakeSession({"datasets/media/images/a.png": png()})
    plan, _, _, _ = build_remote_plan(req, session)
    assert plan["files"] == [{"path": "images/a.png", "size": len(png())}]
    assert session.reads == ["datasets/media/images/a.png"]


def test_remote_zip_is_checked_by_size_and_left_for_the_training_host():
    session = FakeSession({"datasets/train.zip": b"PK" + b"x" * 100})
    plan, kept, preview, facts = build_remote_plan(request(manifest_path="/datasets/train.zip"), session)
    assert plan == {
        "kind": "remote_plan",
        "version": 1,
        "data_type": "image_text",
        "layout": "zip",
        "zip": {"path": "datasets/train.zip", "size": 102},
    }
    assert (kept, preview, session.reads, facts["validation_stage"]) == (None, None, [], "size_checked")
    with pytest.raises(RemoteDatasetError, match="not found"):
        build_remote_plan(request(manifest_path="missing.zip"), session)


def test_ftp_absolute_paths_stay_absolute_in_the_plan():
    req = request(
        source="ftp",
        connection={"endpoint": "ftp://ftp.example"},
        manifest_path="/srv/data/train.json",
        media_root="/srv/data",
    )
    session = FakeSession({"/srv/data/train.json": json.dumps(records()).encode(), "/srv/data/images/a.png": png()})
    plan, _, _, _ = build_remote_plan(req, session)
    source = public_source(req, plan)
    assert (source["media_root"], source["probe"]) == ("/srv/data", "/srv/data/images/a.png")


def test_text_remote_json_returns_its_rows_for_normal_storage():
    rows = [{"instruction": "Classify", "input": "printer", "output": "IT"}]
    req = request(data_type="text", manifest_path="train.json")
    plan, kept, preview, facts = build_remote_plan(req, FakeSession({"train.json": json.dumps(rows).encode()}))
    assert (plan, kept, preview, facts["samples"]) == (None, rows, None, 1)


def test_public_source_keeps_connection_facts_and_never_secrets():
    session = FakeSession({"datasets/train.json": json.dumps(records()).encode(), "datasets/media/images/a.png": png()})
    req = request()
    plan, _, _, _ = build_remote_plan(req, session)
    source = public_source(req, plan)
    assert source["probe"] == "datasets/media/images/a.png" and source["bucket"] == "training"
    assert "example-private" not in json.dumps(source) and "example-access" not in json.dumps(source)
    assert not set(source) & {"password", "access_key", "secret_key", "session_token"}


@pytest.mark.parametrize(
    "path", ["../secret", "/data/../secret", "http://host/file", "a\\b", "file\r\nDELE /", "%00/../secret"]
)
def test_remote_paths_reject_traversal_and_command_injection(path):
    with pytest.raises(RemoteDatasetError):
        checked_remote_path(path)


def test_missing_media_names_the_sample_and_file():
    session = FakeSession({"datasets/train.json": json.dumps(records()).encode()})
    with pytest.raises(RemoteDatasetError) as captured:
        build_remote_plan(request(), session)
    assert "Sample 1" in str(captured.value)
    assert "images/a.png" in str(captured.value)


def test_corrupt_preview_sample_is_reported_by_file_name():
    session = FakeSession(
        {"datasets/train.json": json.dumps(records()).encode(), "datasets/media/images/a.png": b"not an image"}
    )
    with pytest.raises(RemoteDatasetError, match=r"Image cannot be decoded: images/a\.png"):
        build_remote_plan(request(), session)


def test_manifest_parse_error_does_not_drop_bad_lines():
    req = request(
        data_type="text",
        manifest_path=None,
        manifest_filename="train.jsonl",
        manifest_text='{"instruction":"a","output":"b"}\nnot-json',
    )
    with pytest.raises(RemoteDatasetError, match="Invalid manifest"):
        build_remote_plan(req, FakeSession({}))


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
        with remote_dataset.remote_reader(request()) as session:
            session.read("train.json", 100)
    assert "example-private" not in str(captured.value)


async def test_text_import_is_stored_like_a_local_json_upload(monkeypatch):
    rows = [{"instruction": "q", "output": "a"}]
    monkeypatch.setattr(datasets, "plan_remote_dataset", lambda req: (None, rows, None, {"samples": 1}))

    async def upload(files, preset, user):
        assert json.loads(await files[0].read()) == rows
        assert files[0].filename == "Customer dataset.json" and preset is False
        return [{"id": "immutable-version", "url": "stored.json", "dataset_report": {"samples": 1}}]

    monkeypatch.setattr(datasets.FinetuneFileService, "upload_file", upload)
    result = await DatasetService.import_version(request(data_type="text"), SimpleNamespace(user_id=1))
    assert result["id"] == "immutable-version"
    assert "connection" not in result


async def test_media_import_stores_a_plan_and_preview_without_secrets(monkeypatch):
    req = request()
    session = FakeSession({"datasets/train.json": json.dumps(records()).encode(), "datasets/media/images/a.png": png()})
    built = build_remote_plan(req, session)
    monkeypatch.setattr(datasets, "plan_remote_dataset", lambda _: built)
    storage = SimpleNamespace(bucket="bisheng", put_object=AsyncMock())
    monkeypatch.setattr(datasets, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(datasets.FinetuneFileService, "_personal_prefix", lambda user: "finetune/train/")
    monkeypatch.setattr(
        datasets.FinetuneFileService,
        "store_preview",
        AsyncMock(side_effect=lambda url, report, preview: {**report, "preview_url": url + ".preview.zip"}),
    )
    monkeypatch.setattr(FinetuneDatasetRepository, "save", AsyncMock(side_effect=lambda record: record))
    result = await DatasetService.import_version(req, SimpleNamespace(user_id=1))
    stored = storage.put_object.call_args.kwargs
    assert stored["object_name"] == result["url"] and result["url"].endswith(".plan.json")
    assert json.loads(stored["file"]) == built[0]
    report = result["dataset_report"]
    assert report["sha256"] == hashlib.sha256(stored["file"]).hexdigest()
    assert (report["delivery"], report["media"], report["remote"]["type"]) == ("remote", 1, "s3")
    assert report["preview_url"] == result["url"] + ".preview.zip"
    assert "example-private" not in json.dumps(result) + stored["file"].decode()


async def test_unknown_or_other_tenant_version_cannot_be_previewed(monkeypatch):
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=None))
    with pytest.raises(TrainFileNotExistError):
        await DatasetService.preview("other-tenant")


def package(rows, media):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("train.json", json.dumps(rows))
        for name, content in media.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.mark.parametrize("stored_preview", [False, True])
async def test_version_preview_uses_authorized_same_origin_media(monkeypatch, stored_preview):
    raw = package(records(), {"images/a.png": png()})
    digest = hashlib.sha256(raw).hexdigest()
    report = {"data_type": "image_text", "sha256": "full-package" if stored_preview else digest}
    if stored_preview:
        report.update(preview_url="stored.plan.json.preview.zip", preview_sha256=digest)
    version = SimpleNamespace(
        id="v1", purpose="training", url="stored.plan.json" if stored_preview else "stored.zip", report=report
    )
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=version))
    get_object = AsyncMock(return_value=raw)
    monkeypatch.setattr(datasets, "get_minio_storage", AsyncMock(return_value=SimpleNamespace(get_object=get_object)))
    preview = await DatasetService.preview("v1")
    assert get_object.call_args.kwargs["object_name"] == (
        "stored.plan.json.preview.zip" if stored_preview else "stored.zip"
    )
    assert preview["samples"][0]["media"][0]["url"].startswith("/api/v1/finetune/datasets/v1/media?")
    content, mime = await DatasetService.media("v1", "images/a.png")
    assert (content, mime) == (png(), "image/png")
    with pytest.raises(TrainFileNotExistError):
        await DatasetService.media("v1", "train.json")


async def test_remote_zip_version_has_no_platform_preview(monkeypatch):
    version = SimpleNamespace(
        id="v1", purpose="training", url="x.plan.json", report={"delivery": "remote", "sha256": "x"}
    )
    monkeypatch.setattr(FinetuneDatasetRepository, "find_by_id", AsyncMock(return_value=version))
    assert (await DatasetService.preview("v1"))["samples"] == []


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
        with remote_dataset.remote_reader(request()) as session:
            session.read("train.json", 4)
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
    client.mlsd.return_value = [("a.png", {"type": "file", "size": "7"}), ("sub", {"type": "dir"})]
    with remote_dataset.remote_reader(req) as session:
        assert session.read("customer/train.json", 50) == b"content"
        assert session.sizes(["customer/a.png", "customer/b.png"]) == {"customer/a.png": 7, "customer/b.png": None}
        # Servers without MLSD are asked for each file's SIZE.
        client.mlsd.side_effect = remote_dataset.ftplib.error_perm("500 unknown command")
        client.size.side_effect = [9, remote_dataset.ftplib.error_perm("550 not found")]
        assert session.sizes(["other/a.png", "other/b.png"]) == {"other/a.png": 9, "other/b.png": None}
    assert client.retrbinary.call_args.args[0] == "RETR customer/train.json"
    client.close.assert_called_once()


def _sftp(monkeypatch, files, host_key=b"server-key"):
    monkeypatch.setattr(
        remote_dataset,
        "checked_endpoint",
        lambda *a: (SimpleNamespace(netloc="sftp.example", hostname="sftp.example", scheme="sftp"), 22, "192.168.1.10"),
    )
    monkeypatch.setattr(socket, "create_connection", MagicMock(return_value=MagicMock()))
    transport = MagicMock()
    transport.get_remote_server_key.return_value = SimpleNamespace(asbytes=lambda: host_key)
    monkeypatch.setattr(paramiko, "Transport", MagicMock(return_value=transport))
    client = MagicMock()
    client.open.side_effect = lambda path, mode: io.BytesIO(files[path])
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", MagicMock(return_value=client))
    return transport, client


def _fingerprint(key: bytes) -> str:
    import base64

    return "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")


def test_sftp_reads_relative_paths_within_budget_and_closes(monkeypatch):
    transport, client = _sftp(monkeypatch, {"customer/train.json": b"content"})
    req = request(
        source="sftp",
        connection={
            "endpoint": "sftp://sftp.example",
            "username": "reader",
            "password": "example-private",
            "host_fingerprint": _fingerprint(b"server-key"),
        },
    )
    client.listdir_attr.return_value = [SimpleNamespace(filename="train.json", st_size=7)]
    with remote_dataset.remote_reader(req) as session:
        assert session.read("customer/train.json", 50) == b"content"
        with pytest.raises(RemoteDatasetError, match="budget"):
            session.read("customer/train.json", 3)
        assert session.sizes(["customer/train.json", "customer/x.png"]) == {
            "customer/train.json": 7,
            "customer/x.png": None,
        }
    client.listdir_attr.assert_called_once_with("customer")
    transport.auth_password.assert_called_once_with("reader", "example-private")
    client.open.assert_called_with("customer/train.json", "rb")
    transport.close.assert_called_once()


def test_sftp_rejects_a_mismatched_host_key_before_sending_the_password(monkeypatch):
    transport, _ = _sftp(monkeypatch, {})
    req = request(
        source="sftp",
        connection={
            "endpoint": "sftp://sftp.example",
            "username": "reader",
            "password": "example-private",
            "host_fingerprint": _fingerprint(b"another-key"),
        },
    )
    with pytest.raises(RemoteDatasetError, match="fingerprint"):
        with remote_dataset.remote_reader(req):
            pass
    transport.auth_password.assert_not_called()
    transport.close.assert_called_once()


def test_sftp_connector_errors_are_sanitized_and_username_is_required(monkeypatch):
    transport, _ = _sftp(monkeypatch, {})
    transport.auth_password.side_effect = paramiko.AuthenticationException("example-private rejected")
    req = request(
        source="sftp",
        connection={"endpoint": "sftp://sftp.example", "username": "reader", "password": "example-private"},
    )
    with pytest.raises(RemoteDatasetError) as raised:
        with remote_dataset.remote_reader(req):
            pass
    assert "example-private" not in str(raised.value)
    no_user = request(source="sftp", connection={"endpoint": "sftp://sftp.example", "password": "x"})
    with pytest.raises(RemoteDatasetError, match="username"):
        with remote_dataset.remote_reader(no_user):
            pass


def test_sftp_endpoint_scheme_and_default_port(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port))],
    )
    assert checked_endpoint("sftp://files.example", "sftp")[1] == 22
    with pytest.raises(RemoteDatasetError):
        checked_endpoint("ftp://files.example", "sftp")


def test_corrupt_image_is_reported_by_file_name():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("train.json", json.dumps(records()))
        archive.writestr("images/a.png", b"not an image")
    with pytest.raises(ValueError, match=r"Image cannot be decoded: images/a\.png"):
        inspect_package(buffer.getvalue())
