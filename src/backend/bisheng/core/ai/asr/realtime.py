"""Bailian protocols and the shared streaming/file transcription lifecycle."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from websockets.asyncio.client import connect

from bisheng.core.ai.base import ASRSegment, ASRTranscript, BaseASRClient, join_sentence_texts

from .capabilities import ALI_MODELS as ASR_PROTOCOLS
from .capabilities import realtime_protocol as realtime_protocol
from .connection import StreamConnection

FINISH_TIMEOUT = 15.0


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


class ASRConnection(StreamConnection):
    def event(self, kind: str, **kwargs) -> dict:
        return {"type": kind, "event_id": uuid.uuid4().hex, **kwargs}

    async def start(self):
        headers = {"Authorization": f"Bearer {self.client.api_key}"}
        self.ws = await connect(
            self.client.url,
            additional_headers=headers,
            # A shell SOCKS proxy (common on dev machines) makes websockets
            # require python-socks. The vendor socket is a direct connection.
            proxy=None,
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
            event = self.transcript(segment, text, final)
            if event is not None:
                yield event
        raise RuntimeError("ASR connection closed before recognition completed")


class RealtimeASRClient(BaseASRClient):
    """A streaming model also accepts normalized files through the same protocol."""

    def __init__(self, api_key: str, model: str, base_url: str = "", **kwargs):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.protocol = ASR_PROTOCOLS[model]
        self.url = websocket_url(base_url, self.protocol, model)

    def create_connection(self) -> StreamConnection:
        return ASRConnection(self)

    async def stream(
        self,
        audio: AsyncIterator[bytes],
        on_ready: Callable[[], Awaitable[None]],
        on_event: Callable[[dict], Awaitable[None]],
    ):
        connection = self.create_connection()
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

    def _for_model(self, model: str) -> RealtimeASRClient:
        return type(self)(api_key=self.api_key, model=model, base_url=self.base_url)

    async def transcribe_file(
        self, wav_path: str, language: str | None = None, model: str | None = None
    ) -> ASRTranscript:
        if model and model != self.model:
            return await self._for_model(model).transcribe_file(wav_path, language=language)
        # Streaming providers detect language and return their own sentence boundaries.
        results: dict[str, str] = {}

        async def frames():
            with wave.open(wav_path, "rb") as source:
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
        segments = [ASRSegment(text=text) for text in results.values() if text.strip()]
        return ASRTranscript(text=join_sentence_texts([segment.text for segment in segments]), segments=segments)
