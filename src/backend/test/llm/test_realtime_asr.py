"""Streaming protocol, tenant-config binding, and file-model compatibility."""

import asyncio
import json
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.ai.asr import realtime
from bisheng.llm.domain.llm.asr import BishengASR
from bisheng.llm.domain.schemas import WorkbenchModelConfig, WSModel
from bisheng.llm.domain.services import asr_realtime
from bisheng.llm.domain.services.llm import LLMService


class ProviderSocket:
    def __init__(self, protocol, finish_response=True):
        self.protocol = protocol
        self.finish_response = finish_response
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False

    def put(self, value):
        self.incoming.put_nowait(json.dumps(value))

    def result(self, final, text):
        if self.protocol == "paraformer":
            return {
                "header": {"event": "result-generated"},
                "payload": {
                    "output": {
                        "sentence": {"sentence_id": 0, "sentence_end": final, "text": text},
                    }
                },
            }
        if final:
            return {"type": "conversation.item.input_audio_transcription.completed", "item_id": "a", "transcript": text}
        return {"type": "conversation.item.input_audio_transcription.text", "item_id": "a", "text": "", "stash": text}

    async def send(self, payload):
        self.sent.append(payload)
        message = json.loads(payload) if isinstance(payload, str) else {}
        action = message.get("type", message.get("header", {}).get("action"))
        if action == "run-task":
            self.put({"header": {"event": "task-started"}})
        elif action == "session.update":
            self.put({"type": "session.created"})
            self.put({"type": "session.updated"})
        elif isinstance(payload, bytes) or action == "input_audio_buffer.append":
            self.put(self.result(False, "draft"))
        elif action in ("finish-task", "session.finish") and self.finish_response:
            self.put(self.result(True, "Final."))
            self.put(self.result(True, "Duplicate."))
            self.put(self.result(False, "Stale."))
            self.put(
                {"header": {"event": "task-finished"}}
                if self.protocol == "paraformer"
                else {"type": "session.finished"}
            )

    async def recv(self):
        return await self.incoming.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()

    async def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "model,protocol", [("paraformer-realtime-v2", "paraformer"), ("qwen3-asr-flash-realtime", "qwen")]
)
async def test_both_protocols_flush_final_before_close(monkeypatch, model, protocol):
    socket = ProviderSocket(protocol)
    connect = AsyncMock(return_value=socket)
    monkeypatch.setattr(realtime, "connect", connect)
    client = realtime.RealtimeASRClient("test-key", model)
    ready, event = AsyncMock(), AsyncMock()

    async def audio():
        ready.assert_awaited_once()
        yield b"\x00\x00" * 1600

    await client.stream(audio(), ready, event)
    assert [call.args[0]["text"] for call in event.await_args_list if call.args[0]["type"] == "final"] == ["Final."]
    assert socket.closed
    connect.assert_awaited_once()
    assert connect.await_args.kwargs["additional_headers"] == {"Authorization": "Bearer test-key"}


async def test_finish_timeout_releases_provider(monkeypatch):
    socket = ProviderSocket("paraformer", finish_response=False)
    monkeypatch.setattr(realtime, "connect", AsyncMock(return_value=socket))
    monkeypatch.setattr(realtime, "FINISH_TIMEOUT", 0.01)

    async def audio():
        yield b"\x00\x00"

    with pytest.raises(TimeoutError):
        await realtime.RealtimeASRClient("test-key", "paraformer-realtime-v2").stream(audio(), AsyncMock(), AsyncMock())
    assert socket.closed


async def test_browser_disconnect_cancels_receive_and_closes_provider(monkeypatch):
    socket = ProviderSocket("qwen")
    monkeypatch.setattr(realtime, "connect", AsyncMock(return_value=socket))

    async def audio():
        yield b"\x00\x00"
        raise ConnectionError("browser disconnected")

    with pytest.raises(ConnectionError):
        await realtime.RealtimeASRClient("test-key", "qwen3-asr-flash-realtime").stream(
            audio(), AsyncMock(), AsyncMock()
        )
    assert socket.closed


async def test_file_probe_uses_streaming_adapter(monkeypatch, tmp_path):
    socket = ProviderSocket("paraformer")
    monkeypatch.setattr(realtime, "connect", AsyncMock(return_value=socket))
    path = tmp_path / "probe.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
        wav.writeframes(b"\x00\x00" * 160)
    transcript = await realtime.RealtimeASRClient("test-key", "paraformer-realtime-v2").transcribe_file(str(path))
    assert transcript.text == "Final."
    assert [segment.text for segment in transcript.segments] == ["Final."]


def test_explicit_model_registry_and_region():
    assert realtime.realtime_protocol("qwen", "paraformer-realtime-v2") == "paraformer"
    assert realtime.realtime_protocol("openai", "paraformer-realtime-v2") is None
    assert realtime.realtime_protocol("qwen", "arbitrary-realtime") is None
    assert realtime.websocket_url(
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "qwen", "qwen3-asr-flash-realtime"
    ) == ("wss://workspace.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime")
    with pytest.raises(ValueError):
        realtime.websocket_url("http://example.com", "qwen", "qwen3-asr-flash-realtime")


async def test_model_config_selects_streaming_and_preserves_file_asr():
    server = SimpleNamespace(type="qwen", config={"openai_api_key": "test-key"})
    model = SimpleNamespace(model_name="paraformer-realtime-v2", config={})
    assert isinstance(await BishengASR.init_asr_client(model, server), realtime.RealtimeASRClient)
    model.model_name = "paraformer-v2"
    assert (await BishengASR.init_asr_client(model, server)).__class__.__name__ == "AliyunASRClient"
    model.model_name = "arbitrary-realtime"
    with pytest.raises(ValueError):
        await BishengASR.init_asr_client(model, server)


class BrowserSocket:
    def __init__(self, model_id="1", messages=None, origin="https://example.com"):
        self.headers = {"host": "example.com", "origin": origin}
        self.start = {"type": "start", "model_id": model_id}
        self.messages = iter(messages or [{"type": "websocket.receive", "text": '{"type":"stop"}'}])
        self.sent = []
        self.accept = AsyncMock()
        self.close = AsyncMock()

    async def receive_json(self):
        return self.start

    async def receive(self):
        return next(self.messages)

    async def send_json(self, message):
        self.sent.append(message)


def setup_service(monkeypatch):
    model = realtime.RealtimeASRClient("test-key", "paraformer-realtime-v2")

    async def stream(audio, ready, forward):
        await ready()
        async for _ in audio:
            pass
        await forward({"type": "final", "segment_id": "a", "version": 1, "text": "Final."})

    resolve = AsyncMock(return_value=SimpleNamespace(asr=model, astream=stream))
    monkeypatch.setattr(
        LLMService, "get_workbench_llm", AsyncMock(return_value=SimpleNamespace(asr_model=SimpleNamespace(id="1")))
    )
    monkeypatch.setattr(LLMService, "get_bisheng_asr", resolve)
    return resolve


async def test_session_binds_configured_model_and_preserves_final(monkeypatch):
    resolve = setup_service(monkeypatch)
    browser = BrowserSocket()
    await asr_realtime.run_realtime_asr(browser, SimpleNamespace(user_id=7))
    assert [event["type"] for event in browser.sent] == ["ready", "final", "completed"]
    assert resolve.await_args.kwargs["model_id"] == 1
    assert resolve.await_args.kwargs["user_id"] == 7
    browser.close.assert_awaited_once()


async def test_other_model_id_is_rejected_before_provider_access(monkeypatch):
    resolve = setup_service(monkeypatch)
    browser = BrowserSocket(model_id="2")
    await asr_realtime.run_realtime_asr(browser, SimpleNamespace(user_id=7))
    resolve.assert_not_awaited()
    assert [event["type"] for event in browser.sent] == ["error"]


async def test_cross_origin_is_rejected_before_accept(monkeypatch):
    resolve = setup_service(monkeypatch)
    browser = BrowserSocket(origin="https://other.example")
    await asr_realtime.run_realtime_asr(browser, SimpleNamespace(user_id=7))
    resolve.assert_not_awaited()
    browser.accept.assert_not_awaited()
    browser.close.assert_awaited_once_with(code=1008)


async def test_dev_proxy_forwarded_host_is_accepted(monkeypatch):
    setup_service(monkeypatch)
    browser = BrowserSocket(origin="http://localhost:4001")
    browser.headers = {
        "host": "127.0.0.1:7860",
        "origin": "http://localhost:4001",
        "x-forwarded-host": "localhost:4001",
    }
    await asr_realtime.run_realtime_asr(browser, SimpleNamespace(user_id=7))
    browser.accept.assert_awaited()
    browser.close.assert_awaited_once()


async def test_oversized_audio_is_rejected(monkeypatch):
    setup_service(monkeypatch)
    browser = BrowserSocket(messages=[{"type": "websocket.receive", "bytes": bytes(32002)}])
    await asr_realtime.run_realtime_asr(browser, SimpleNamespace(user_id=7))
    assert [event["type"] for event in browser.sent] == ["ready", "error"]


@pytest.mark.parametrize("name,expected", [("paraformer-realtime-v2", True), ("paraformer-v2", False)])
async def test_effective_config_derives_capability_from_model(monkeypatch, name, expected):
    config = WorkbenchModelConfig(asr_model=WSModel(id="12", realtime=not expected))
    typed = AsyncMock(return_value=(config, True, False))
    monkeypatch.setattr(LLMService, "_aget_typed_with_meta", typed)
    monkeypatch.setattr(LLMService, "_sanitize_workbench_config_refs", AsyncMock(return_value=config))
    monkeypatch.setattr(
        BishengASR,
        "get_model_server_info",
        AsyncMock(
            return_value=(
                SimpleNamespace(model_name=name),
                SimpleNamespace(type="qwen"),
            )
        ),
    )
    result, inherited, blocked = await LLMService.aget_workbench_llm_with_meta(tenant_id=7)
    assert result.asr_model.realtime is expected
    assert (inherited, blocked) == (True, False)
    assert typed.await_args.args[-1] == 7


async def test_file_transcription_preserves_segments_and_english_word_boundaries(monkeypatch, tmp_path):
    client = realtime.RealtimeASRClient("test-key", "paraformer-realtime-v2")

    async def stream(audio, on_ready, on_event):
        async for _ in audio:
            pass
        for segment_id, text in [("1", "hello"), ("2", "world")]:
            await on_event({"type": "final", "segment_id": segment_id, "text": text})

    monkeypatch.setattr(client, "stream", stream)
    path = tmp_path / "probe.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
    transcript = await client.transcribe_file(str(path))
    assert transcript.text == "hello world"
    assert [segment.text for segment in transcript.segments] == ["hello", "world"]


async def test_file_model_override_keeps_original_client_and_region(monkeypatch, tmp_path):
    socket = ProviderSocket("qwen")
    connector = AsyncMock(return_value=socket)
    monkeypatch.setattr(realtime, "connect", connector)
    client = realtime.RealtimeASRClient(
        "test-key", "paraformer-realtime-v2", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    path = tmp_path / "probe.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "NONE"))
    result = await client.transcribe_file(str(path), model="qwen3-asr-flash-realtime")
    assert result.text == "Final."
    assert client.model == "paraformer-realtime-v2"
    assert connector.await_args.args[0] == (
        "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime"
    )
