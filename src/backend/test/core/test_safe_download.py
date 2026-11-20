"""Exercise DNS/HTTP boundaries locally; no real sockets or remote requests."""

import ipaddress
import socket
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from bisheng.core.cache import utils
from bisheng.core.external import safe_download as safe
from bisheng.knowledge.domain.services.web_link_import_service import KnowledgeWebLinkImportService


def _response(url, status=200, headers=None, peer="8.8.8.8", body=b"canary"):
    stream = SimpleNamespace(get_extra_info=lambda name: (peer, 443)) if peer else None
    return httpx.Response(
        status, headers=headers, content=body, request=httpx.Request("GET", url), extensions={"network_stream": stream}
    )


@pytest.fixture
def boundary(monkeypatch):
    dns = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    calls, options, queue = [], [], []

    class Client:
        def __init__(self, **kwargs):
            options.append(kwargs)
            self.cookies = SimpleNamespace(clear=lambda: None)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @contextmanager
        def stream(self, method, url, **kwargs):
            calls.append((url, kwargs))
            response = queue.pop(0) if queue else _response(url)
            try:
                yield response
            finally:
                response.close()

    class AsyncClient(Client):
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            with super().stream(method, url, **kwargs) as response:
                yield response

    monkeypatch.setattr(safe.httpx, "Client", Client)
    monkeypatch.setattr(safe.httpx, "AsyncClient", AsyncClient)
    return SimpleNamespace(dns=dns, calls=calls, options=options, queue=queue)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_pins_numeric_ip_keeps_tls_host_no_second_dns(boundary, asynchronous):
    url = "https://public.example/document.txt"
    # A second resolver call would turn private: the transport must not make it.
    boundary.dns.side_effect = [
        boundary.dns.return_value,
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    ]
    if asynchronous:
        async with safe.public_astream(url) as response:
            assert str(response.url) == url
    else:
        with safe.public_stream(url) as response:
            assert str(response.url) == url
    assert boundary.dns.call_count == 1
    pinned, kwargs = boundary.calls[0]
    assert pinned == "https://8.8.8.8:443/document.txt"
    assert kwargs["headers"]["Host"] == "public.example"
    assert kwargs["extensions"]["sni_hostname"] == "public.example"
    assert boundary.options[0]["verify"] is True
    assert boundary.options[0]["trust_env"] is False
    assert boundary.options[0]["follow_redirects"] is False


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_redirect_private_denied_before_second_connection(boundary, asynchronous):
    boundary.queue.append(
        _response("https://public.example/a", 302, {"location": "http://169.254.169.254/latest/meta-data/"})
    )
    with pytest.raises(ValueError):
        if asynchronous:
            async with safe.public_astream("https://public.example/a"):
                pytest.fail("redirect escaped")
        else:
            with safe.public_stream("https://public.example/a"):
                pytest.fail("redirect escaped")
    assert len(boundary.calls) == 1


def test_relative_redirect_and_limit(boundary):
    boundary.queue.extend(
        [_response("https://public.example/a", 302, {"location": "/b"}), _response("https://public.example/b")]
    )
    with safe.public_stream("https://public.example/a") as response:
        assert str(response.url) == "https://public.example/b"
    assert len(boundary.calls) == 2
    boundary.queue.extend([_response("https://public.example/b", 302, {"location": "/b"}) for _ in range(6)])
    with pytest.raises(ValueError, match="too many"):
        with safe.public_stream("https://public.example/b"):
            pytest.fail("loop escaped")


@pytest.mark.parametrize("peer", [None, "127.0.0.1"])
def test_unknown_or_changed_peer_denied(boundary, peer):
    boundary.queue.append(_response("https://public.example/a", peer=peer))
    with pytest.raises(ValueError, match="peer"):
        with safe.public_stream("https://public.example/a"):
            pytest.fail("peer escaped")


def test_mixed_dns_rejected_before_connection(boundary):
    boundary.dns.return_value.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fc00::1", 443, 0, 0)))
    with pytest.raises(ValueError):
        with safe.public_stream("https://public.example/a"):
            pytest.fail("mixed DNS escaped")
    assert not boundary.calls


@pytest.mark.parametrize(
    "url",
    [
        "ftp://public.example/a",
        "https://user@public.example/a",
        "http://2130706433/a",
        "http://0x7f000001/a",
        "http://127.1/a",
        "http://[::ffff:127.0.0.1]/a",
        "http://public.example\\@127.0.0.1/a",
    ],
)
def test_ambiguous_destinations_denied(boundary, url):
    with pytest.raises(ValueError):
        with safe.public_stream(url):
            pytest.fail("invalid URL escaped")
    assert not boundary.calls


@pytest.mark.parametrize(
    "url",
    [
        "http://minio.local.evil/b/f",
        "http://minio.local:9001/b/f",
        "http://minio.local@evil/b/f",
        "https://minio.local:9000/b/f",
    ],
)
def test_minio_origin_not_prefix(url):
    assert not safe.same_origin(url, "http://minio.local:9000")


async def test_minio_uses_sdk_not_network(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta
    from io import BytesIO

    from minio import Minio

    config = SimpleNamespace(access_key="fixture-access", secret_key="fixture-secret")
    signer = Minio(
        "minio.local:9000", access_key=config.access_key, secret_key=config.secret_key, secure=False, region="us-east-1"
    )
    minio = SimpleNamespace(
        bucket="bucket",
        tmp_bucket="tmp",
        minio_config=config,
        get_minio_share_host=lambda: "http://minio.local:9000",
        minio_client_sync=SimpleNamespace(get_object=Mock(side_effect=lambda *args, **kwargs: BytesIO(b"object"))),
    )
    url = signer.get_presigned_url(
        "GET", "bucket", "a.txt", expires=timedelta(minutes=5), request_date=datetime.now(UTC)
    )
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: minio)
    monkeypatch.setattr(utils, "save_download_file", lambda body, *args: str(tmp_path / "saved"))
    for method in [utils.file_download, utils.async_file_download]:
        result = method(url)
        if hasattr(result, "__await__"):
            result = await result
        assert result[1] == "a.txt"
    minio.minio_client_sync.get_object.assert_called_with("bucket", "a.txt", version_id=None)


@pytest.mark.parametrize("url", ["http://minio.local:9000/other/a", "/other/a?X-Amz-Algorithm=AWS4"])
async def test_minio_rejects_unconfigured_bucket(monkeypatch, url):
    minio = SimpleNamespace(
        bucket="bucket",
        tmp_bucket="tmp",
        get_minio_share_host=lambda: "http://minio.local:9000",
        download_object_sync=Mock(side_effect=AssertionError("unconfigured bucket read")),
    )
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: minio)
    with pytest.raises(ValueError):
        utils.file_download(url)
    with pytest.raises(ValueError):
        await utils.async_file_download(url)
    minio.download_object_sync.assert_not_called()


async def test_generic_public_download_preserves_bytes_and_filename(boundary, monkeypatch, tmp_path):
    from pathlib import Path

    minio = SimpleNamespace(get_minio_share_host=lambda: "https://storage.example")
    monkeypatch.setattr(utils, "get_minio_storage_sync", lambda: minio)
    monkeypatch.setattr(utils, "CACHE_DIR", str(tmp_path))
    for method in [utils.file_download, utils.async_file_download]:
        boundary.queue.append(
            _response(
                "https://public.example/doc",
                headers={"Content-Disposition": "attachment; filename=report.txt"},
                body=b"document content",
            )
        )
        result = method("https://public.example/doc")
        if hasattr(result, "__await__"):
            result = await result
        path, name = result
        assert name == "report.txt"
        assert Path(path).read_bytes() == b"document content"


def test_bounded_stream():
    response = SimpleNamespace(iter_bytes=lambda size: iter([b"ab", b"cd"]))
    with pytest.raises(ValueError, match="limit"):
        list(safe.BoundedDownload(response, max_bytes=3).iter_content(2))


async def test_web_link_browser_fallback_never_launches():
    assert await KnowledgeWebLinkImportService._fetch_rendered_content("http://127.0.0.1/") is None


async def test_web_link_public_plain_text(boundary):
    boundary.queue.append(_response("https://public.example/doc", headers={"content-type": "text/plain"}))
    result = await KnowledgeWebLinkImportService.fetch("https://public.example/doc")
    assert result.final_url == "https://public.example/doc"
    assert result.markdown == "canary\n"
    assert not KnowledgeWebLinkImportService._is_blocked_ip(ipaddress.ip_address("8.8.8.8"))


def test_real_httpcore_tls_uses_original_hostname(monkeypatch, tmp_path):
    """A loopback-only fixture proves real HTTPX SNI/cert checks, not mock options.

    Patch only the policy resolution to this owned listener; production policy
    still rejects loopback. The certificate has DNS SAN but no IP SAN.
    """
    import datetime
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from bisheng_langchain.utils.egress_policy import ResolvedDestination

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "download.test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("download.test")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    context.set_servername_callback(lambda sock, hostname, ctx: seen.append(hostname))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    url = f"https://download.test:{port}/canary"
    target = ResolvedDestination(url, "https", "download.test", port, f"https://download.test:{port}", ("127.0.0.1",))
    monkeypatch.setattr(safe, "resolve_destination", lambda value: target)
    # Trust this throwaway fixture certificate while retaining hostname checking.
    real_client = httpx.Client

    def client(**kwargs):
        kwargs["verify"] = ssl.create_default_context(cafile=str(cert_path))
        return real_client(**kwargs)

    monkeypatch.setattr(safe.httpx, "Client", client)
    try:
        with safe.public_stream(url) as response:
            assert response.read() == b"ok"
        assert seen == ["download.test", f"download.test:{port}"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
