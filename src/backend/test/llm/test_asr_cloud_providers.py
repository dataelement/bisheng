"""Offline protocol fixtures for native cloud speech services; no paid calls."""

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl, urlsplit

import pytest

from bisheng.core.ai.asr import realtime, speech_cloud, volcengine
from bisheng.core.ai.asr.capabilities import realtime_protocol
from bisheng.llm.domain.llm.asr import BishengASR
from bisheng.utils.mask_data import JsonFieldMasker

VOLC_CONFIG = {"speech_api_key": "fixture-api", "speech_resource_id": "volc.seedasr.sauc.duration"}
BAIDU_CONFIG = {"speech_app_id": "123", "speech_api_key": "fixture-api"}
TENCENT_CONFIG = {"speech_app_id": "123", "speech_secret_id": "fixture-id", "speech_secret_key": "fixture-secret"}


def volc_result(text, final=False, compression=1, sequence=True):
    body = json.dumps({"result": {"text": text}}).encode()
    if compression:
        body = gzip.compress(body)
    flags = int(sequence) | (2 if final else 0)
    header = bytes((0x11, 0x90 | flags, 0x10 | compression, 0))
    seq = struct.pack(">i", -3 if final else 2) if sequence else b""
    return header + seq + struct.pack(">I", len(body)) + body


class Socket:
    def __init__(self, provider, finish_response=True):
        self.provider = provider
        self.finish_response = finish_response
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.close_code = 1000
        if provider == "tencent":
            self.put({"code": 0, "voice_id": "fixture"})

    def put(self, value):
        self.incoming.put_nowait(json.dumps(value) if isinstance(value, dict) else value)

    def result(self, text, final=False):
        if self.provider == "volcengine":
            self.put(volc_result(text, final))
        elif self.provider == "baidu":
            self.put({"type": "FIN_TEXT" if final else "MID_TEXT", "err_no": 0, "sn": "session_ws_1", "result": text})
        else:
            self.put({"code": 0, "result": {"index": 0, "slice_type": 2 if final else 1, "voice_text_str": text}})

    async def send(self, payload):
        self.sent.append(payload)
        message = json.loads(payload) if isinstance(payload, str) else {}
        is_audio = isinstance(payload, bytes)
        if self.provider == "volcengine":
            is_audio = payload[1] >> 4 == 2
            finished = bool(payload[1] & 2)
        else:
            finished = message.get("type") in ("FINISH", "end")
        if finished and self.finish_response:
            self.result("Final.", True)
            if self.provider == "baidu":
                self.result("Duplicate.", True)
                self.result("Stale.")
                self.put(None)
            elif self.provider == "tencent":
                self.result("Duplicate.", True)
                self.result("Stale.")
                self.put({"code": 0, "final": 1})
        elif is_audio and not finished:
            self.result("Draft")

    async def recv(self):
        return await self.incoming.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.recv()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self):
        self.closed = True


def client_for(provider):
    return {
        "volcengine": lambda: volcengine.VolcengineRealtimeASRClient("bigmodel", VOLC_CONFIG),
        "baidu": lambda: speech_cloud.BaiduRealtimeASRClient("15376", BAIDU_CONFIG),
        "tencent": lambda: speech_cloud.TencentRealtimeASRClient("16k_zh", TENCENT_CONFIG),
    }[provider]()


def connect_socket(monkeypatch, provider, socket):
    connector = AsyncMock(return_value=socket)
    monkeypatch.setattr(volcengine if provider == "volcengine" else speech_cloud, "connect", connector)
    return connector


@pytest.mark.parametrize("provider", ["volcengine", "baidu", "tencent"])
async def test_ready_audio_final_finish_and_cleanup(monkeypatch, provider):
    socket = Socket(provider)
    connector = connect_socket(monkeypatch, provider, socket)
    ready, event = AsyncMock(), AsyncMock()

    async def audio():
        ready.assert_awaited_once()
        yield b"\x01\x00" * 1600
        await asyncio.sleep(0)

    await client_for(provider).stream(audio(), ready, event)
    events = [call.args[0] for call in event.await_args_list]
    assert [event["text"] for event in events if event["type"] == "final"] == ["Final."]
    assert events[0]["type"] == "partial"
    assert events[-1]["version"] == 2
    assert socket.closed
    if provider == "baidu":
        start = json.loads(socket.sent[0])["data"]
        assert start["dev_pid"] == 15376 and start["user"] and start["appid"] == 123
        assert start["appkey"] == "fixture-api"
        assert socket.sent[-1] == '{"type": "FINISH"}'
    elif provider == "volcengine":
        header = connector.await_args.kwargs["additional_headers"]
        assert header["X-Api-Key"] == "fixture-api"
        assert header["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
        assert socket.sent[0][:4] == b"\x11\x10\x11\x00"
        request = json.loads(gzip.decompress(socket.sent[0][8:]))
        assert request["request"]["result_type"] == "full"
        assert request["audio"] == {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1}
        assert socket.sent[-1][1] == 0x22
    else:
        assert json.loads(socket.sent[-1]) == {"type": "end"}


@pytest.mark.parametrize("provider", ["volcengine", "baidu", "tencent"])
async def test_finish_timeout_closes_all_provider_connections(monkeypatch, provider):
    socket = Socket(provider, finish_response=False)
    connect_socket(monkeypatch, provider, socket)
    monkeypatch.setattr(realtime, "FINISH_TIMEOUT", 0.01)

    async def audio():
        yield bytes(3200)

    with pytest.raises(TimeoutError):
        await client_for(provider).stream(audio(), AsyncMock(), AsyncMock())
    assert socket.closed


@pytest.mark.parametrize("provider", ["volcengine", "baidu", "tencent"])
async def test_disconnect_cancels_receiver(monkeypatch, provider):
    socket = Socket(provider)
    connect_socket(monkeypatch, provider, socket)

    async def audio():
        yield bytes(3200)
        raise ConnectionError("browser disconnected")

    with pytest.raises(ConnectionError):
        await client_for(provider).stream(audio(), AsyncMock(), AsyncMock())
    assert socket.closed


@pytest.mark.parametrize("provider", ["volcengine", "baidu", "tencent"])
async def test_early_normal_close_is_not_completion(monkeypatch, provider):
    socket = Socket(provider)
    connect_socket(monkeypatch, provider, socket)
    connection = client_for(provider).create_connection()
    await connection.start()
    socket.put(None)
    with pytest.raises(RuntimeError, match="before recognition completed"):
        _ = [event async for event in connection.events()]


@pytest.mark.parametrize(
    "compression,sequence,final", [(0, False, False), (1, True, False), (0, True, True), (1, False, True)]
)
def test_volcengine_server_frames(compression, sequence, final):
    message, last = volcengine.decode_packet(volc_result("one two", final, compression, sequence))
    assert last is final and message["result"]["text"] == "one two"


def test_volcengine_rejects_corrupt_oversized_and_error_frames():
    valid = volc_result("test")
    for raw in (b"bad", valid[:-1], valid + b"extra"):
        with pytest.raises(ValueError):
            volcengine.decode_packet(raw)
    body = gzip.compress(b"x" * (volcengine.MAX_PAYLOAD + 1))
    with pytest.raises(ValueError, match="compressed"):
        volcengine.decode_packet(b"\x11\x90\x11\x00" + struct.pack(">I", len(body)) + body)
    with pytest.raises(RuntimeError, match="45000001"):
        volcengine.decode_packet(b"\x11\xf0\x10\x00" + struct.pack(">II", 45000001, 0))


async def test_volcengine_old_console_authentication(monkeypatch):
    socket = Socket("volcengine")
    connector = connect_socket(monkeypatch, "volcengine", socket)
    config = {
        "speech_auth_mode": "app_key",
        "speech_app_id": "123",
        "speech_access_key": "fixture-token",
        "speech_resource_id": "volc.bigasr.sauc.duration",
    }
    await volcengine.VolcengineRealtimeASRClient("bigmodel", config).create_connection().start()
    headers = connector.await_args.kwargs["additional_headers"]
    assert headers["X-Api-App-Key"] == "123" and headers["X-Api-Access-Key"] == "fixture-token"
    assert "X-Api-Key" not in headers


def test_tencent_signature_uses_sorted_raw_parameters_then_urlencoding():
    url = speech_cloud.tencent_url("123", "id+/=", "secret", "16k_zh", "unique-id", 1700000000, 1234)
    expected_text = "asr.cloud.tencent.com/asr/v2/123?engine_model_type=16k_zh&expired=1700003600&needvad=1&nonce=1234&secretid=id+/=&timestamp=1700000000&voice_format=1&voice_id=unique-id"
    expected = base64.b64encode(hmac.new(b"secret", expected_text.encode(), hashlib.sha1).digest()).decode()
    query = dict(parse_qsl(urlsplit(url).query))
    assert query["signature"] == expected
    assert query["secretid"] == "id+/="
    assert "secretid=id%2B%2F%3D" in url


@pytest.mark.parametrize(
    "provider,model,config,cls",
    [
        ("volcengine", "bigmodel", VOLC_CONFIG, volcengine.VolcengineRealtimeASRClient),
        ("qianfan", "15372", BAIDU_CONFIG, speech_cloud.BaiduRealtimeASRClient),
        ("tencent", "16k_zh_en", TENCENT_CONFIG, speech_cloud.TencentRealtimeASRClient),
    ],
)
async def test_factory_and_capability_match(provider, model, config, cls):
    assert realtime_protocol(provider, model)
    server = SimpleNamespace(type=provider, config=config)
    instance = await BishengASR.init_asr_client(SimpleNamespace(model_name=model, config=None), server)
    assert isinstance(instance, cls) and isinstance(instance, realtime.RealtimeASRClient)
    with pytest.raises(ValueError):
        await BishengASR.init_asr_client(SimpleNamespace(model_name="unsupported", config=None), server)
    assert realtime_protocol(provider, "unsupported") is None


@pytest.mark.parametrize(
    "cls,model",
    [
        (volcengine.VolcengineRealtimeASRClient, "bigmodel"),
        (speech_cloud.BaiduRealtimeASRClient, "15372"),
        (speech_cloud.TencentRealtimeASRClient, "16k_zh"),
    ],
)
def test_llm_credentials_do_not_replace_speech_credentials(cls, model):
    with pytest.raises(ValueError, match="speech_"):
        cls(model, {"api_key": "llm-only"})


def test_speech_secrets_mask_and_round_trip():
    masker = JsonFieldMasker()
    original = {
        "config": {
            "speech_api_key": "original-api",
            "speech_access_key": "original-access",
            "speech_secret_key": "original-secret",
            "speech_app_id": "123",
        }
    }
    masked = masker.mask_json(original)
    assert masked["config"] == {
        "speech_api_key": "********",
        "speech_access_key": "********",
        "speech_secret_key": "********",
        "speech_app_id": "123",
    }
    assert masker.update_json_with_masked(original, masked) == original
    masked["config"]["speech_api_key"] = "replacement"
    assert masker.update_json_with_masked(original, masked)["config"]["speech_api_key"] == "replacement"


async def test_tencent_paces_browser_backlog_and_limits_packet_size(monkeypatch):
    socket = Socket("tencent")
    connect_socket(monkeypatch, "tencent", socket)
    clock = [100.0]
    sleeps = []
    monkeypatch.setattr(speech_cloud.time, "monotonic", lambda: clock[0])

    async def advance(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(speech_cloud.asyncio, "sleep", advance)
    connection = client_for("tencent").create_connection()
    await connection.start()
    await connection.send_audio(bytes(16000))
    assert [len(packet) for packet in socket.sent] == [6400, 6400, 3200]
    assert sleeps == pytest.approx([0, 0.2, 0.2])


@pytest.mark.parametrize("provider,error", [("baidu", {"err_no": -3004}), ("tencent", {"code": 4004})])
async def test_provider_error_is_propagated_without_echoing_credentials(monkeypatch, provider, error):
    socket = Socket(provider)
    connect_socket(monkeypatch, provider, socket)
    connection = client_for(provider).create_connection()
    await connection.start()
    socket.put({**error, "message": "sensitive provider diagnostics", "err_msg": "sensitive provider diagnostics"})
    with pytest.raises(RuntimeError, match="ASR error") as failure:
        _ = [event async for event in connection.events()]
    assert "sensitive" not in str(failure.value)
