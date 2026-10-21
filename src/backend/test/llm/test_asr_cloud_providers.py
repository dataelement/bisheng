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
from fastapi import HTTPException
from websockets.exceptions import InvalidStatus

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.ai.asr import realtime, speech_cloud, volcengine
from bisheng.core.ai.asr.capabilities import realtime_protocol, should_promote_legacy_asr
from bisheng.llm.domain.llm.asr import BishengASR, is_asr_provider_supported
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


async def test_volcengine_access_check_is_only_a_handshake(monkeypatch):
    socket = Socket("volcengine")
    connector = connect_socket(monkeypatch, "volcengine", socket)
    await volcengine.VolcengineRealtimeASRClient("bigmodel", VOLC_CONFIG).verify_access()
    assert socket.closed and socket.sent == []
    headers = connector.await_args.kwargs["additional_headers"]
    assert headers["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
    assert headers["X-Api-Key"] == "fixture-api"


async def test_volcengine_forbidden_resource_fails_the_handshake(monkeypatch):
    async def reject(*_args, **_kwargs):
        raise InvalidStatus(SimpleNamespace(status_code=403))

    monkeypatch.setattr(volcengine, "connect", reject)
    with pytest.raises(volcengine.SpeechAccessRejected):
        await volcengine.VolcengineRealtimeASRClient("bigmodel", VOLC_CONFIG).verify_access()


async def test_save_rejects_a_resource_the_speech_credentials_cannot_use(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMService

    async def reject(self):
        raise volcengine.SpeechAccessRejected("rejected")

    monkeypatch.setattr(volcengine.VolcengineRealtimeASRClient, "verify_access", reject)
    speech = SimpleNamespace(model_type="asr_rt", model_name="bigmodel")
    with pytest.raises(HTTPException) as caught:
        await LLMService._ensure_volcengine_speech("volcengine", VOLC_CONFIG, [speech])
    assert caught.value.status_code == 10804

    file_typed = SimpleNamespace(model_type="asr", model_name="bigmodel")
    await LLMService._ensure_volcengine_speech("volcengine", VOLC_CONFIG, [file_typed])
    chat = SimpleNamespace(model_type="llm", model_name="doubao")
    await LLMService._ensure_volcengine_speech("volcengine", VOLC_CONFIG, [chat])


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
    assert is_asr_provider_supported(provider)
    server = SimpleNamespace(type=provider, config=config)
    instance = await BishengASR.init_asr_client(
        SimpleNamespace(model_name=model, model_type="asr_rt", config=None), server
    )
    assert isinstance(instance, cls) and isinstance(instance, realtime.RealtimeASRClient)
    unknown = SimpleNamespace(model_name="unsupported", model_type="asr_rt", config=None)
    if provider == "volcengine":
        with pytest.raises(ValueError):
            await BishengASR.init_asr_client(unknown, server)
    else:
        built = await BishengASR.init_asr_client(unknown, server)
        assert built.model == "unsupported"
    with pytest.raises(ValueError, match="no file ASR client"):
        await BishengASR.init_asr_client(SimpleNamespace(model_name=model, model_type="asr", config=None), server)
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


async def test_baidu_close_without_status_keeps_the_partial(monkeypatch):
    socket = Socket("baidu", finish_response=False)
    connect_socket(monkeypatch, "baidu", socket)
    connection = client_for("baidu").create_connection()
    await connection.start()
    connection.finished_input = True
    socket.close_code = 1005
    socket.put({"type": "MID_TEXT", "err_no": 0, "sn": "s1", "result": "你好"})
    socket.put(None)
    events = [event async for event in connection.events()]
    assert [(event["type"], event["text"]) for event in events] == [("partial", "你好"), ("final", "你好")]


async def test_baidu_abnormal_close_is_still_rejected(monkeypatch):
    socket = Socket("baidu", finish_response=False)
    connect_socket(monkeypatch, "baidu", socket)
    connection = client_for("baidu").create_connection()
    await connection.start()
    connection.finished_input = True
    socket.close_code = 1006
    socket.put(None)
    with pytest.raises(RuntimeError, match=r"closed before recognition completed \(1006\)"):
        _ = [event async for event in connection.events()]


async def test_baidu_paces_browser_backlog_before_finish(monkeypatch):
    socket = Socket("baidu")
    connect_socket(monkeypatch, "baidu", socket)
    clock = [100.0]
    sleeps = []
    monkeypatch.setattr(speech_cloud.time, "monotonic", lambda: clock[0])

    async def advance(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(speech_cloud.asyncio, "sleep", advance)
    connection = client_for("baidu").create_connection()
    await connection.start()
    await connection.send_audio(bytes(16000))
    await connection.finish()
    assert [len(packet) for packet in socket.sent if isinstance(packet, bytes)] == [6400, 6400, 3200]
    assert sleeps == pytest.approx([0, 0.2, 0.2, 0.1])
    assert socket.sent[-1] == '{"type": "FINISH"}'


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


@pytest.mark.parametrize(
    "provider,model,override,config,cls",
    [
        ("baidu", "15372", "1537", BAIDU_CONFIG, speech_cloud.BaiduRealtimeASRClient),
        ("tencent", "16k_zh", "16k_en", TENCENT_CONFIG, speech_cloud.TencentRealtimeASRClient),
    ],
)
async def test_cloud_file_model_override_preserves_credentials(
    monkeypatch, tmp_path, provider, model, override, config, cls
):
    import wave

    socket = Socket(provider)
    connect_socket(monkeypatch, provider, socket)
    client = cls(model, config)
    path = tmp_path / "probe.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
    transcript = await client.transcribe_file(str(path), model=override)
    assert transcript.text == "Final."
    assert client.model == model
    assert socket.closed


def test_legacy_promotion_follows_server_type():
    assert should_promote_legacy_asr("tencent", "16k_zh", "asr")
    assert should_promote_legacy_asr("qianfan", "1537", "asr")
    assert should_promote_legacy_asr("volcengine", "bigmodel", "asr")
    assert should_promote_legacy_asr("qwen", "paraformer-realtime-v2", "asr")
    assert not should_promote_legacy_asr("openai", "16k_zh", "asr")
    assert not should_promote_legacy_asr("tencent", "new-engine", "asr")
    assert not should_promote_legacy_asr("tencent", "16k_zh", "asr_rt")


def test_tencent_unknown_engine_is_the_url_parameter():
    client = speech_cloud.TencentRealtimeASRClient("new-engine", TENCENT_CONFIG)
    query = dict(
        parse_qsl(
            urlsplit(
                speech_cloud.tencent_url(
                    client.app_id, client.secret_id, client.secret_key, client.model, "voice", 1, 2
                )
            ).query
        )
    )
    assert query["engine_model_type"] == "new-engine"
    with pytest.raises(ValueError):
        speech_cloud.TencentRealtimeASRClient("  ", TENCENT_CONFIG)


async def test_baidu_non_numeric_engine_fails_when_the_session_starts(monkeypatch):
    monkeypatch.setattr(speech_cloud, "connect", AsyncMock())
    client = speech_cloud.BaiduRealtimeASRClient("not-a-pid", BAIDU_CONFIG)
    with pytest.raises(ValueError):
        await client.create_connection().start()
    with pytest.raises(ValueError):
        speech_cloud.BaiduRealtimeASRClient("", BAIDU_CONFIG)


async def test_get_bisheng_asr_builds_an_unlisted_tencent_engine(monkeypatch):
    model = SimpleNamespace(id=21, model_name="new-engine", model_type="asr_rt", online=True, config=None)
    server = SimpleNamespace(type="tencent", name="Tencent", config=TENCENT_CONFIG)

    async def lookup(_model_id):
        return model, server

    monkeypatch.setattr(BishengASR, "get_model_server_info", lookup)
    instance = await BishengASR.get_bisheng_asr(
        model_id=21,
        ignore_online=True,
        app_id=ApplicationTypeEnum.MODEL_TEST.value,
        app_name=ApplicationTypeEnum.MODEL_TEST.value,
        app_type=ApplicationTypeEnum.MODEL_TEST,
        user_id=1,
    )
    assert instance.asr.model == "new-engine"


async def test_probe_invokes_realtime_asr(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMService

    fake = AsyncMock()
    fake.ainvoke = AsyncMock(return_value="hello")
    getter = AsyncMock(return_value=fake)
    monkeypatch.setattr("bisheng.llm.domain.services.llm.BishengASR.get_bisheng_asr", getter)
    await LLMService._invoke_model_probe(SimpleNamespace(id=21, model_type="asr_rt", model_name="new-engine"), {})
    getter.assert_awaited()
    fake.ainvoke.assert_awaited()


async def test_empty_workbench_slot_accepts_realtime_asr(monkeypatch):
    from bisheng.llm.domain.schemas import WorkbenchModelConfig
    from bisheng.llm.domain.services.llm import LLMService

    saved = {}

    async def get_workbench():
        return WorkbenchModelConfig()

    async def update(_user, workbench, _tasks):
        saved["id"] = workbench.asr_model.id

    monkeypatch.setattr(LLMService, "get_workbench_llm", get_workbench)
    monkeypatch.setattr(LLMService, "update_workbench_llm", update)
    await LLMService.set_default_model(SimpleNamespace(id=9, model_type="asr_rt", model_name="16k_zh"))
    assert saved["id"] == "9"


async def test_file_typed_tencent_model_is_not_kept(monkeypatch):
    from bisheng.llm.domain.models.llm_server import LLMDao
    from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
    from bisheng.llm.domain.services.llm import LLMService

    deleted = {}

    async def no_server(_name):
        return None

    async def insert(server, models, **_kwargs):
        server.id = 7
        return server

    async def listed(_server_id, operator=None):
        return SimpleNamespace(
            id=7,
            tenant_id=1,
            models=[SimpleNamespace(id=21, model_name="16k_zh", model_type="asr")],
        )

    async def delete(server_id):
        deleted["id"] = server_id

    async def lookup(_model_id):
        return (
            SimpleNamespace(id=21, model_name="16k_zh", model_type="asr", online=True, config=None),
            SimpleNamespace(type="tencent", name="Tencent", config=TENCENT_CONFIG),
        )

    monkeypatch.setattr(LLMDao, "aget_server_by_name", no_server)
    monkeypatch.setattr(LLMDao, "ainsert_server_with_models", insert)
    monkeypatch.setattr(LLMDao, "adelete_server_by_id", delete)
    monkeypatch.setattr(LLMService, "get_one_llm", listed)
    monkeypatch.setattr(BishengASR, "get_model_server_info", lookup)
    server = LLMServerCreateReq(
        name="tencent-speech",
        type="tencent",
        config=TENCENT_CONFIG,
        models=[LLMModelCreateReq(name="Chinese", model_name="16k_zh", model_type="asr")],
    )
    with pytest.raises(HTTPException):
        await LLMService.add_llm_server(SimpleNamespace(), SimpleNamespace(user_id=1), server)
    assert deleted["id"] == 7


async def test_add_checks_speech_by_calling_the_provider(monkeypatch):
    from bisheng.llm.domain.models.llm_server import LLMDao
    from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
    from bisheng.llm.domain.services.llm import LLMService

    deleted = {}
    called = {}

    async def no_server(_name):
        return None

    async def insert(server, models, **_kwargs):
        server.id = 8
        return server

    async def listed(_server_id, operator=None):
        return SimpleNamespace(
            id=8,
            tenant_id=1,
            models=[SimpleNamespace(id=22, model_name="new-engine", model_type="asr_rt")],
        )

    async def delete(server_id):
        deleted["id"] = server_id

    async def lookup(_model_id):
        return (
            SimpleNamespace(id=22, model_name="new-engine", model_type="asr_rt", online=True, config=None),
            SimpleNamespace(type="tencent", name="Tencent", config=TENCENT_CONFIG),
        )

    async def reject(self, _audio, **_kwargs):
        called["provider"] = True
        raise RuntimeError("vendor rejected")

    monkeypatch.setattr(LLMDao, "aget_server_by_name", no_server)
    monkeypatch.setattr(LLMDao, "ainsert_server_with_models", insert)
    monkeypatch.setattr(LLMDao, "adelete_server_by_id", delete)
    monkeypatch.setattr(LLMService, "get_one_llm", listed)
    monkeypatch.setattr(BishengASR, "get_model_server_info", lookup)
    monkeypatch.setattr(BishengASR, "ainvoke", reject)
    server = LLMServerCreateReq(
        name="tencent-speech-rt",
        type="tencent",
        config=TENCENT_CONFIG,
        models=[LLMModelCreateReq(name="New", model_name="new-engine", model_type="asr_rt")],
    )
    with pytest.raises(HTTPException):
        await LLMService.add_llm_server(SimpleNamespace(), SimpleNamespace(user_id=1), server)
    assert called["provider"] is True
    assert deleted["id"] == 8
