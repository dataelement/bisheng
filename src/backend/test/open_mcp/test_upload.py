import base64
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bisheng.open_mcp.contracts import KnowledgeFileUploadInput
from bisheng.open_mcp.upload import (
    McpUploadError,
    prepared_upload,
    validate_outbound_url,
)


@pytest.mark.asyncio
async def test_prepared_base64_upload_decodes_and_removes_temporary_file(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name="f067.txt",
        content_base64=base64.b64encode(b"hello mcp").decode(),
    )

    async with prepared_upload(source) as (path, file_name):
        temporary_path = Path(path)
        temporary_directory = temporary_path.parent
        assert file_name == "f067.txt"
        assert temporary_path.read_bytes() == b"hello mcp"
        assert temporary_directory.name.startswith("bisheng-open-mcp-")
        assert temporary_path.name == f"{hashlib.sha256(b'hello mcp').hexdigest()}_f067.txt"

    assert not temporary_path.exists()
    assert not temporary_directory.exists()


@pytest.mark.asyncio
async def test_prepared_base64_upload_rejects_invalid_and_cleans_up(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name="f067.txt",
        content_base64="not strict base64!",
    )

    with pytest.raises(McpUploadError, match="not valid strict base64"):
        async with prepared_upload(source):
            pass


@pytest.mark.asyncio
async def test_prepared_base64_upload_enforces_decoded_size(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 3)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name="f067.txt",
        content_base64=base64.b64encode(b"four").decode(),
    )

    with pytest.raises(McpUploadError, match="exceeds the configured upload limit"):
        async with prepared_upload(source):
            pass


@pytest.mark.asyncio
async def test_prepared_base64_upload_rejects_non_basename_file_name(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name="../f067.txt",
        content_base64=base64.b64encode(b"f067").decode(),
    )

    with pytest.raises(McpUploadError, match="base name"):
        async with prepared_upload(source):
            pass


@pytest.mark.asyncio
async def test_prepared_upload_bounds_multibyte_staged_file_name(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name=f"{'😀' * 60}.txt",
        content_base64=base64.b64encode(b"f067").decode(),
    )

    async with prepared_upload(source) as (path, _):
        assert len(Path(path).name.encode("utf-8")) <= 255


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://user:pass@files.example/f.txt", "userinfo"),
        ("http://files.example/f.txt", "HTTPS"),
        ("https://other.example/f.txt", "allowlisted"),
    ],
)
async def test_outbound_url_rejects_unsafe_shape(monkeypatch, url, message):
    monkeypatch.setattr("bisheng.open_mcp.upload._minio_share_origin", lambda: None)

    with pytest.raises(McpUploadError, match=message):
        await validate_outbound_url(
            url,
            allowed_hosts=["files.example"],
            allow_minio_http=False,
        )


@pytest.mark.asyncio
async def test_outbound_url_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload._minio_share_origin", lambda: None)

    async def _private_address(host, port):
        assert (host, port) == ("files.example", 443)
        return {"127.0.0.1"}

    monkeypatch.setattr("bisheng.open_mcp.upload._resolve_addresses", _private_address)

    with pytest.raises(McpUploadError, match="prohibited network address"):
        await validate_outbound_url(
            "https://files.example/f.txt",
            allowed_hosts=["files.example"],
            allow_minio_http=False,
        )


@pytest.mark.asyncio
async def test_outbound_url_accepts_allowlisted_public_https(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload._minio_share_origin", lambda: None)

    async def _public_address(host, port):
        return {"93.184.216.34"}

    monkeypatch.setattr("bisheng.open_mcp.upload._resolve_addresses", _public_address)

    url = "https://files.example/f.txt"
    assert (
        await validate_outbound_url(
            url,
            allowed_hosts=["files.example"],
            allow_minio_http=False,
        )
        == url
    )


def test_callback_url_is_not_part_of_the_mcp_upload_contract():
    with pytest.raises(ValueError):
        KnowledgeFileUploadInput(
            knowledge_id=67,
            file_name="f067.txt",
            content_base64="Zg==",
            callback_url="https://callback.example/done",
        )


@pytest.mark.asyncio
async def test_prepared_base64_rejects_data_after_padding_across_chunks(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024 * 1024)
    encoded = "A" * (65536 - 4) + "YQ==" + "YQ=="
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_name="f067.txt",
        content_base64=encoded,
    )

    with pytest.raises(McpUploadError, match="strict base64"):
        async with prepared_upload(source):
            pass


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "100.64.0.1"])
def test_non_global_addresses_are_not_public(address):
    from bisheng.open_mcp.upload import _is_public_ip

    assert _is_public_ip(address) is False


@pytest.mark.asyncio
async def test_file_url_download_pins_approved_ip_and_preserves_host_and_sni(monkeypatch):
    captured = {}

    async def _addresses(host, port):
        assert (host, port) == ("files.example", 443)
        return {"93.184.216.34"}

    class _NetworkStream:
        def get_extra_info(self, name):
            assert name == "server_addr"
            return ("93.184.216.34", 443)

    class _Response:
        is_redirect = False
        headers = {"content-length": "4"}
        extensions = {"network_stream": _NetworkStream()}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, chunk_size):
            assert chunk_size == 64 * 1024
            yield b"f067"

    class _Client:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            captured.update({"method": method, "url": str(url), **kwargs})
            yield _Response()

    monkeypatch.setattr("bisheng.open_mcp.upload._minio_share_origin", lambda: None)
    monkeypatch.setattr("bisheng.open_mcp.upload._resolve_addresses", _addresses)
    monkeypatch.setattr("bisheng.open_mcp.upload.httpx.AsyncClient", _Client)
    monkeypatch.setattr("bisheng.open_mcp.upload.get_max_upload_bytes", lambda _: 1024)
    monkeypatch.setattr(
        "bisheng.open_mcp.upload.settings.open_mcp.file_url_allowed_hosts",
        ["files.example"],
    )
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_url="https://files.example/f067.txt",
    )

    async with prepared_upload(source) as (path, file_name):
        assert Path(path).read_bytes() == b"f067"
        assert file_name == "f067.txt"

    assert captured["url"] == "https://93.184.216.34/f067.txt"
    assert captured["headers"] == {"Host": "files.example"}
    assert captured["extensions"] == {"sni_hostname": "files.example"}
    assert captured["client_kwargs"]["trust_env"] is False


@pytest.mark.asyncio
async def test_file_url_decodes_path_before_choosing_safe_base_name(monkeypatch):
    async def _download(url, path, file_name):
        assert file_name == "f067.txt"
        Path(path).write_bytes(b"f067")

    monkeypatch.setattr("bisheng.open_mcp.upload._download_to_file", _download)
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_url="https://files.example/nested%2Ff067.txt",
    )

    async with prepared_upload(source) as (path, file_name):
        assert file_name == "f067.txt"
        assert Path(path).name.endswith("_f067.txt")


@pytest.mark.asyncio
async def test_file_url_rejects_nul_in_decoded_file_name():
    source = KnowledgeFileUploadInput(
        knowledge_id=67,
        file_url="https://files.example/f067%00.txt",
    )

    with pytest.raises(McpUploadError, match="base name"):
        async with prepared_upload(source):
            pass


@pytest.mark.asyncio
async def test_minio_private_http_exception_requires_exact_scheme_host_and_port(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_mcp.upload._minio_share_origin",
        lambda: ("http", "minio.internal", 9000),
    )
    monkeypatch.setattr(
        "bisheng.open_mcp.upload._resolve_addresses",
        AsyncMock(return_value={"10.0.0.8"}),
    )

    accepted = await validate_outbound_url(
        "http://minio.internal:9000/f067.txt",
        allowed_hosts=[],
        allow_minio_http=True,
    )
    assert accepted.endswith("/f067.txt")

    with pytest.raises(McpUploadError, match="allowlisted"):
        await validate_outbound_url(
            "http://minio.internal:3306/f067.txt",
            allowed_hosts=[],
            allow_minio_http=True,
        )


@pytest.mark.asyncio
async def test_mixed_public_and_private_dns_answers_are_rejected(monkeypatch):
    monkeypatch.setattr("bisheng.open_mcp.upload._minio_share_origin", lambda: None)
    monkeypatch.setattr(
        "bisheng.open_mcp.upload._resolve_addresses",
        AsyncMock(return_value={"93.184.216.34", "127.0.0.1"}),
    )

    with pytest.raises(McpUploadError, match="prohibited"):
        await validate_outbound_url(
            "https://files.example/f067.txt",
            allowed_hosts=["files.example"],
            allow_minio_http=False,
        )
