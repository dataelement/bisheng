from __future__ import annotations

import asyncio
import json
import ssl
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from websockets.asyncio.server import serve

from bisheng.eplus.infrastructure.connection_client import (
    EPlusConnectionClient,
    EPlusConnectionConfig,
    EPlusConnectionExitReason,
    EPlusSubscriptionError,
)
from bisheng.eplus.infrastructure.protocol import build_stream_frame


def _ack(req_id: str, *, errcode: int = 0, errmsg: str = "ok") -> str:
    return json.dumps({"headers": {"req_id": req_id}, "errcode": errcode, "errmsg": errmsg})


async def _subscribe_ok(websocket) -> dict:
    subscribe = json.loads(await websocket.recv())
    assert subscribe["cmd"] == "aibot_subscribe"
    await websocket.send(_ack(subscribe["headers"]["req_id"]))
    return subscribe


async def test_ws_subscribes_and_dispatches_message_without_blocking_receiver() -> None:
    messages: list[dict] = []
    handler_release = asyncio.Event()

    async def on_message(frame: dict) -> None:
        messages.append(frame)
        await handler_release.wait()

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        await websocket.send(
            json.dumps(
                {
                    "cmd": "aibot_msg_callback",
                    "headers": {"req_id": "callback-1"},
                    "body": {"msgid": "message-1", "aibotid": "bot-1"},
                }
            )
        )
        ping = json.loads(await websocket.recv())
        assert ping["cmd"] == "ping"
        await websocket.send(_ack(ping["headers"]["req_id"]))
        handler_release.set()
        await websocket.close()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(
                url=f"ws://127.0.0.1:{port}/im_openws?bizid=1",
                bot_id="bot-1",
                secret="secret-1",
                heartbeat_interval_seconds=0.01,
            ),
            on_message=on_message,
        )
        reason = await client.run_connection_once()

    assert reason is EPlusConnectionExitReason.DISCONNECTED
    assert [frame["body"]["msgid"] for frame in messages] == ["message-1"]


async def test_subscription_rejection_closes_connection() -> None:
    async def fake_eplus(websocket) -> None:
        subscribe = json.loads(await websocket.recv())
        await websocket.send(_ack(subscribe["headers"]["req_id"], errcode=40013, errmsg="invalid secret"))
        await websocket.wait_closed()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(url=f"ws://127.0.0.1:{port}/socket", bot_id="bot-1", secret="bad-secret")
        )
        with pytest.raises(EPlusSubscriptionError, match="40013"):
            await client.run_connection_once()


async def test_two_consecutive_heartbeat_ack_timeouts_close_connection() -> None:
    pings: list[dict] = []

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        while len(pings) < 2:
            pings.append(json.loads(await websocket.recv()))
        await websocket.wait_closed()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(
                url=f"ws://127.0.0.1:{port}/socket",
                bot_id="bot-1",
                secret="secret-1",
                heartbeat_interval_seconds=0.01,
                ack_timeout_seconds=0.01,
            )
        )
        reason = await asyncio.wait_for(client.run_connection_once(), timeout=1)

    assert reason is EPlusConnectionExitReason.DISCONNECTED
    assert [frame["cmd"] for frame in pings] == ["ping", "ping"]


async def test_same_req_id_is_serialized_until_previous_ack() -> None:
    received: list[dict] = []
    release_first = asyncio.Event()

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        first = json.loads(await websocket.recv())
        received.append(first)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(websocket.recv(), timeout=0.03)
        release_first.set()
        await websocket.send(_ack(first["headers"]["req_id"]))
        second = json.loads(await websocket.recv())
        received.append(second)
        await websocket.send(_ack(second["headers"]["req_id"]))
        await websocket.close()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(url=f"ws://127.0.0.1:{port}/socket", bot_id="bot-1", secret="secret-1")
        )
        run_task = asyncio.create_task(client.run_connection_once())
        await client.wait_authenticated()
        first = asyncio.create_task(client.send_with_ack(build_stream_frame("same", "s1", "a", finish=False)))
        second = asyncio.create_task(client.send_with_ack(build_stream_frame("same", "s1", "ab", finish=True)))
        await release_first.wait()
        await asyncio.gather(first, second)
        await run_task

    assert [frame["body"]["stream"]["content"] for frame in received] == ["a", "ab"]


async def test_different_req_ids_wait_for_their_own_ack_independently() -> None:
    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        first = json.loads(await websocket.recv())
        second = json.loads(await websocket.recv())
        by_req = {frame["headers"]["req_id"]: frame for frame in (first, second)}
        await websocket.send(_ack("req-b", errmsg="second first"))
        await websocket.send(_ack("req-a", errmsg="first second"))
        assert set(by_req) == {"req-a", "req-b"}
        await websocket.close()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(url=f"ws://127.0.0.1:{port}/socket", bot_id="bot-1", secret="secret-1")
        )
        run_task = asyncio.create_task(client.run_connection_once())
        await client.wait_authenticated()
        result_a, result_b = await asyncio.gather(
            client.send_with_ack(build_stream_frame("req-a", "s-a", "a", finish=True)),
            client.send_with_ack(build_stream_frame("req-b", "s-b", "b", finish=True)),
        )
        await run_task

    assert result_a["errmsg"] == "first second"
    assert result_b["errmsg"] == "second first"


async def test_disconnected_event_is_classified_as_taken_over() -> None:
    events: list[dict] = []

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        await websocket.send(
            json.dumps(
                {
                    "cmd": "aibot_event_callback",
                    "headers": {"req_id": "event-1"},
                    "body": {"event": {"eventtype": "disconnected_event"}},
                }
            )
        )
        await websocket.wait_closed()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(url=f"ws://127.0.0.1:{port}/socket", bot_id="bot-1", secret="secret-1"),
            on_event=lambda frame: events.append(frame),
        )
        reason = await client.run_connection_once()

    assert reason is EPlusConnectionExitReason.TAKEN_OVER
    assert events[0]["body"]["event"]["eventtype"] == "disconnected_event"


def _self_signed_server_material() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ip_address("127.0.0.1"))]), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


async def test_wss_uses_configured_ca_bytes(tmp_path) -> None:
    cert_pem, key_pem = _self_signed_server_material()
    cert_file = tmp_path / "server.crt"
    key_file = tmp_path / "server.key"
    cert_file.write_bytes(cert_pem)
    key_file.write_bytes(key_pem)
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_file, key_file)

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        await websocket.close()

    async with serve(fake_eplus, "127.0.0.1", 0, ssl=server_ssl) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(
                url=f"wss://localhost:{port}/socket?credential=hidden",
                bot_id="bot-1",
                secret="secret-1",
                ca_pem=cert_pem,
            )
        )
        assert await client.run_connection_once() is EPlusConnectionExitReason.DISCONNECTED


async def test_observability_redacts_secret_and_url_query() -> None:
    events: list[tuple[str, dict]] = []

    async def fake_eplus(websocket) -> None:
        await _subscribe_ok(websocket)
        await websocket.close()

    async with serve(fake_eplus, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EPlusConnectionClient(
            EPlusConnectionConfig(
                url=f"ws://127.0.0.1:{port}/socket?bizid=sensitive-query",
                bot_id="bot-1",
                secret="never-log-this",
            ),
            event_sink=lambda event, fields: events.append((event, fields)),
        )
        await client.run_connection_once()

    rendered = json.dumps(events, ensure_ascii=False)
    assert "never-log-this" not in rendered
    assert "sensitive-query" not in rendered
    assert "?<redacted>" in rendered
