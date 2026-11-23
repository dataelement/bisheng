"""Actual async transport must pin DNS and bound untrusted responses."""

import asyncio
import importlib
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def transport():
    try:
        return importlib.import_module("bisheng_langchain.utils.safe_http")
    except ModuleNotFoundError:
        pytest.fail("Safe HTTP transport is not implemented")


async def test_loopback_rejected_before_connect():
    module = transport()
    with pytest.raises(ValueError, match=r"[Dd]estination"):
        await module.arequest("GET", "http://127.0.0.1/private")


async def test_frozen_resolver_does_not_query_dns(monkeypatch):
    module = transport()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("Unexpected second DNS lookup"))
    resolver = module.FrozenResolver("example.com", 443, ("93.184.216.34",))
    result = await resolver.resolve("example.com", 443)
    assert [entry["host"] for entry in result] == ["93.184.216.34"]
    with pytest.raises(ValueError):
        await resolver.resolve("other.example", 443)


async def test_host_override_rejected_before_dns():
    module = transport()
    with pytest.raises(ValueError):
        await module.arequest("GET", "https://example.com/", headers={"Host": "internal.example"})


@pytest.fixture
async def upstream(monkeypatch):
    module = transport()
    received = []

    async def handle(request):
        received.append((request.path, request.host))
        if request.path == "/redirect":
            raise web.HTTPFound("/private")
        if request.path == "/large":
            return web.Response(body=b"x" * 101)
        if request.path == "/compressed":
            import gzip

            return web.Response(body=gzip.compress(b"x" * 1000000), headers={"Content-Encoding": "gzip"})
        return web.Response(text="fixture")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    # Substitute only the policy boundary: the real connector uses its frozen IP.
    monkeypatch.setattr(
        module,
        "resolve_destination",
        lambda url: SimpleNamespace(hostname="fixture.example", port=port, ips=("127.0.0.1",), url=url),
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("Connector re-resolved DNS"))
    try:
        yield module, f"http://fixture.example:{port}", received
    finally:
        await runner.cleanup()


async def test_real_connection_uses_frozen_ip_and_original_host(upstream):
    module, url, received = upstream
    response = await module.arequest("GET", url + "/ok")
    assert response.body == b"fixture"
    assert received == [("/ok", url.removeprefix("http://"))]


async def test_redirect_never_reaches_second_target(upstream):
    module, url, received = upstream
    with pytest.raises(module.RequestFailed):
        await module.arequest("GET", url + "/redirect")
    assert [path for path, _ in received] == ["/redirect"]


async def test_stream_size_is_bounded(upstream):
    module, url, _ = upstream
    with pytest.raises(module.ResponseTooLarge):
        await module.arequest("GET", url + "/large", max_bytes=100)


async def test_compressed_response_rejected_before_decompression(upstream):
    module, url, _ = upstream
    with pytest.raises(module.RequestFailed):
        await module.arequest("GET", url + "/compressed", max_bytes=100)


@pytest.fixture
async def raw_upstream(monkeypatch):
    """Raw local sockets allow partial headers as well as streamed bodies."""
    module = transport()
    servers, tasks = [], set()

    async def start(handler, *, ssl_context=None, host="127.0.0.1", ips=None):
        def connected(reader, writer):
            async def serve():
                try:
                    await handler(reader, writer)
                except (ConnectionError, ssl.SSLError):
                    # Deadline/certificate rejection deliberately closes the client.
                    return
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except (ConnectionError, ssl.SSLError):
                        # Best-effort fixture cleanup after intentional disconnect.
                        assert writer.is_closing()

            task = asyncio.create_task(serve())
            tasks.add(task)

        server = await asyncio.start_server(connected, host, 0, ssl=ssl_context)
        servers.append(server)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(
            module,
            "resolve_destination",
            lambda url: SimpleNamespace(hostname="fixture.example", port=port, ips=ips or (host,), url=url),
        )
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("Connector re-resolved DNS"))
        scheme = "https" if ssl_context else "http"
        return module, f"{scheme}://fixture.example:{port}"

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result


@pytest.fixture
def tls_contexts(tmp_path, monkeypatch):
    """Trust a private test CA, without disabling hostname or chain checks."""
    import aiohttp.connector

    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Async HTTP test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    client_context = ssl.create_default_context(cadata=ca.public_bytes(serialization.Encoding.PEM).decode())
    assert client_context.check_hostname and client_context.verify_mode == ssl.CERT_REQUIRED
    monkeypatch.setattr(aiohttp.connector, "_SSL_CONTEXT_VERIFIED", client_context)

    def server_context(hostname, *, trusted=True):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(ca_name if trusted else name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .sign(ca_key if trusted else key, hashes.SHA256())
        )
        cert_path, key_path = tmp_path / "server.pem", tmp_path / "server.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        return context

    return server_context


@pytest.mark.parametrize("certificate", ["original-host", "wrong-host", "untrusted-chain"])
async def test_real_tls_keeps_hostname_verification_and_sni(raw_upstream, tls_contexts, certificate):
    hostname = "wrong.example" if certificate == "wrong-host" else "fixture.example"
    context = tls_contexts(hostname, trusted=certificate != "untrusted-chain")
    sni, requests = [], []
    context.set_servername_callback(lambda _sock, name, _ctx: sni.append(name))

    async def handle(reader, writer):
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nfixture")
        await writer.drain()

    module, url = await raw_upstream(handle, ssl_context=context)
    if certificate == "original-host":
        response = await module.arequest("GET", url)
        assert response.body == b"fixture"
        assert f"Host: {url.removeprefix('https://')}\r\n".encode() in requests[0]
    else:
        with pytest.raises(module.RequestFailed):
            await module.arequest("GET", url)
        assert requests == []
    assert sni == ["fixture.example"]


async def test_deadline_includes_blocking_dns_without_starting_connection(monkeypatch):
    module = transport()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def delayed_dns(_url):
        started.set()
        try:
            assert release.wait(3), "DNS fixture was not released"
            return SimpleNamespace(hostname="fixture.example", port=80, ips=("127.0.0.1",), url=_url)
        finally:
            finished.set()

    monkeypatch.setattr(module, "resolve_destination", delayed_dns)
    monkeypatch.setattr(module.aiohttp, "TCPConnector", lambda **_kw: pytest.fail("Connected after DNS deadline"))
    loop = asyncio.get_running_loop()
    before = loop.time()
    try:
        with pytest.raises(module.RequestTimeout):
            await module.arequest("GET", "http://fixture.example/", timeout=0.15)
        assert started.is_set()
        assert loop.time() - before < 0.8
        assert not finished.is_set(), "Deadline must not wait for blocking resolver completion"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)


@pytest.mark.parametrize("phase", ["headers", "body"])
async def test_slow_drip_uses_total_deadline_not_per_read_timeout(raw_upstream, phase):
    sent = []

    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        if phase == "body":
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n")
        else:
            writer.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
        await writer.drain()
        for _ in range(20):
            writer.write(b"x")
            await writer.drain()
            sent.append(1)
            await asyncio.sleep(0.04)
        if phase == "headers":
            writer.write(b"\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()

    module, url = await raw_upstream(handle)
    loop = asyncio.get_running_loop()
    before = loop.time()
    with pytest.raises(module.RequestTimeout):
        await module.arequest("GET", url, timeout=0.2)
    assert 2 <= len(sent) < 20
    assert loop.time() - before < 0.65


async def test_environment_http_proxy_is_not_used(upstream, monkeypatch):
    module, url, received = upstream
    proxy_requests = []

    async def proxy(reader, writer):
        proxy_requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(proxy, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    for variable in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(variable, f"http://127.0.0.1:{port}")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    try:
        response = await module.arequest("GET", url + "/no-proxy")
        assert response.body == b"fixture"
        assert [path for path, _ in received] == ["/no-proxy"]
        assert proxy_requests == []
    finally:
        server.close()
        await server.wait_closed()


async def test_frozen_resolver_preserves_ipv6_and_multiple_answers(monkeypatch):
    module = transport()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("Unexpected DNS lookup"))
    ips = ("::1", "127.0.0.1")
    resolver = module.FrozenResolver("fixture.example", 443, ips)
    result = await resolver.resolve("FIXTURE.EXAMPLE", 443)
    assert [entry["host"] for entry in result] == list(ips)
    assert [entry["family"] for entry in result] == [socket.AF_INET6, socket.AF_INET]
    with pytest.raises(module.DestinationDenied):
        await resolver.resolve("fixture.example", 80)


async def test_real_ipv6_connection_uses_frozen_answer(raw_upstream):
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nv6")
        await writer.drain()

    try:
        module, url = await raw_upstream(handle, host="::1")
    except OSError as exc:
        if exc.errno not in {47, 49, 97, 99}:  # IPv6 unavailable on this runner.
            raise
        pytest.skip(f"IPv6 loopback unavailable: {exc}")
    response = await module.arequest("GET", url)
    assert response.body == b"v6"
