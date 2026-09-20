"""Bailian ASR protocols with independent input finish and resource close."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from websockets.asyncio.client import connect

from bisheng.core.ai.base import BaseASRClient

ASR_PROTOCOLS = {
    "paraformer-realtime-v2": "paraformer",
    "paraformer-realtime-v1": "paraformer",
    "qwen3-asr-flash-realtime": "qwen",
}
FINISH_TIMEOUT = 15.0


def realtime_protocol(provider: str, model: str | None) -> str | None:
    return ASR_PROTOCOLS.get(model or "") if provider == "qwen" else None


def websocket_url(base_url: str, protocol: str, model: str) -> str:
    """Preserve configured region/workspace; accept an explicit WS endpoint."""
    parsed = urlsplit(base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1")
    if parsed.scheme not in ("https", "wss") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("ASR Base URL must use HTTPS or WSS")
    path = (
        parsed.path
        if parsed.scheme == "wss"
        else ("/api-ws/v1/inference" if protocol == "paraformer" else "/api-ws/v1/realtime")
    )
    query = dict(parse_qsl(parsed.query))
    if protocol == "qwen":
        query["model"] = model
    return urlunsplit(("wss", parsed.netloc, path, urlencode(query), ""))


class ASRConnection:
    def __init__(self, client: RealtimeASRClient):
        self.client = client
        self.ws = None
        self.task_id = uuid.uuid4().hex
        self.finished_input = False
        self.finals: set[str] = set()
        self.versions: dict[str, int] = {}

    async def send_json(self, payload: dict):
        await self.ws.send(json.dumps(payload))

    def event(self, kind: str, **kwargs) -> dict:
        return {"type": kind, "event_id": uuid.uuid4().hex, **kwargs}

    async def start(self):
        headers = {"Authorization": f"Bearer {self.client.api_key}"}
        self.ws = await connect(
            self.client.url,
            additional_headers=headers,
            open_timeout=10,
            close_timeout=3,
            max_size=1024 * 1024,
            max_queue=16,
        )
        try:
            if self.client.protocol == "paraformer":
                await self.send_json(
                    {
                        "header": {"action": "run-task", "task_id": self.task_id, "streaming": "duplex"},
                        "payload": {
                            "task_group": "audio",
                            "task": "asr",
                            "function": "recognition",
                            "model": self.client.model,
                            "parameters": {"format": "pcm", "sample_rate": 16000},
                            "input": {},
                        },
                    }
                )
                expected = "task-started"
            else:
                await self.send_json(
                    self.event(
                        "session.update",
                        session={
                            "input_audio_format": "pcm",
                            "sample_rate": 16000,
                            "turn_detection": {"type": "server_vad", "threshold": 0.0, "silence_duration_ms": 400},
                        },
                    )
                )
                expected = "session.updated"
            async with asyncio.timeout(10):
                while True:
                    message = json.loads(await self.ws.recv())
                    self.check_error(message)
                    if message.get("type", message.get("header", {}).get("event")) == expected:
                        break
        except BaseException:
            await self.close()
            raise

    @staticmethod
    def check_error(message: dict):
        header = message.get("header", {})
        if header.get("event") == "task-failed":
            raise RuntimeError(f"ASR {header.get('error_code', 'failed')}: {header.get('error_message', '')}")
        if message.get("type") in ("error", "conversation.item.input_audio_transcription.failed"):
            error = message.get("error", {})
            raise RuntimeError(f"ASR {error.get('code', 'failed')}: {error.get('message', '')}")

    async def send_audio(self, pcm: bytes):
        if self.client.protocol == "paraformer":
            await self.ws.send(pcm)
        else:
            await self.send_json(self.event("input_audio_buffer.append", audio=base64.b64encode(pcm).decode("ascii")))

    async def finish(self):
        if self.finished_input:
            return
        self.finished_input = True
        if self.client.protocol == "paraformer":
            await self.send_json(
                {
                    "header": {"action": "finish-task", "task_id": self.task_id, "streaming": "duplex"},
                    "payload": {"input": {}},
                }
            )
        else:
            await self.send_json(self.event("session.finish"))

    async def events(self) -> AsyncIterator[dict]:
        async for raw in self.ws:
            message = json.loads(raw)
            self.check_error(message)
            kind = message.get("type", message.get("header", {}).get("event"))
            if kind in ("task-finished", "session.finished"):
                return
            if kind == "result-generated":
                sentence = message.get("payload", {}).get("output", {}).get("sentence", {})
                segment = str(sentence.get("sentence_id", sentence.get("begin_time", 0)))
                text = sentence.get("text", "")
                final = bool(sentence.get("sentence_end"))
            elif kind in (
                "conversation.item.input_audio_transcription.text",
                "conversation.item.input_audio_transcription.completed",
            ):
                segment = message["item_id"]
                final = kind.endswith(".completed")
                text = message.get("transcript", "") if final else message.get("text", "") + message.get("stash", "")
            else:
                continue
            if segment in self.finals:
                continue
            if final:
                self.finals.add(segment)
            version = self.versions.get(segment, 0) + 1
            self.versions[segment] = version
            yield {"type": "final" if final else "partial", "segment_id": segment, "version": version, "text": text}
        raise RuntimeError("ASR connection closed before recognition completed")

    async def close(self):
        if self.ws is not None:
            ws, self.ws = self.ws, None
            await ws.close()


class RealtimeASRClient(BaseASRClient):
    """A streaming model also accepts normalized files through the same protocol."""

    def __init__(self, api_key: str, model: str, base_url: str = "", **kwargs):
        self.api_key = api_key
        self.model = model
        self.protocol = ASR_PROTOCOLS[model]
        self.url = websocket_url(base_url, self.protocol, model)

    async def stream(
        self,
        audio: AsyncIterator[bytes],
        on_ready: Callable[[], Awaitable[None]],
        on_event: Callable[[dict], Awaitable[None]],
    ):
        connection = ASRConnection(self)
        tasks: list[asyncio.Task] = []
        try:
            await connection.start()
            await on_ready()

            async def send():
                async for pcm in audio:
                    await connection.send_audio(pcm)
                await connection.finish()

            async def receive():
                async for event in connection.events():
                    await on_event(event)

            sender = asyncio.create_task(send())
            receiver = asyncio.create_task(receive())
            tasks = [sender, receiver]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                await receiver
                if not sender.done():
                    raise RuntimeError("ASR provider completed before input ended")
            await sender
            await asyncio.wait_for(receiver, FINISH_TIMEOUT)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                # Each failure above is propagated; cancellation only reclaims the sibling.
                await asyncio.gather(*tasks, return_exceptions=True)
            await connection.close()

    async def _transcribe(self, audio: str, language=None, model=None, **kwargs) -> str:
        results: dict[str, str] = {}

        async def frames():
            with wave.open(audio, "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
                    raise ValueError("ASR requires mono 16-bit 16kHz WAV")
                while pcm := source.readframes(1600):
                    yield pcm
                    await asyncio.sleep(len(pcm) / 32000)

        async def ready():
            return None

        async def collect(event):
            if event["type"] == "final":
                results[event["segment_id"]] = event["text"]

        await self.stream(frames(), ready, collect)
        return "".join(results.values())
