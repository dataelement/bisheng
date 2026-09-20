"""Volcengine bidirectional streaming ASR binary protocol."""

from __future__ import annotations

import gzip
import json
import struct
import zlib

from websockets.asyncio.client import connect

from .capabilities import VOLC_RESOURCES
from .connection import StreamConnection, required
from .realtime import RealtimeASRClient

MAX_PAYLOAD = 1024 * 1024


def encode_packet(payload: bytes, *, audio: bool, final: bool = False) -> bytes:
    body = gzip.compress(payload)
    header = bytes((0x11, (0x20 if audio else 0x10) | (2 if final else 0), 0x01 if audio else 0x11, 0))
    return header + struct.pack(">I", len(body)) + body


def decode_packet(raw: bytes) -> tuple[dict, bool]:
    if not isinstance(raw, bytes) or len(raw) < 8 or raw[0] >> 4 != 1:
        raise ValueError("Invalid Volcengine ASR packet")
    offset = (raw[0] & 15) * 4
    kind, flags = raw[1] >> 4, raw[1] & 15
    serialization, compression = raw[2] >> 4, raw[2] & 15
    if offset < 4 or kind not in (9, 15) or compression not in (0, 1) or flags > 3:
        raise ValueError("Unsupported Volcengine ASR packet header")
    error = None
    if kind == 15 or flags & 1:
        if len(raw) < offset + 4:
            raise ValueError("Truncated Volcengine ASR packet")
        if kind == 15:
            error = struct.unpack_from(">I", raw, offset)[0]
        offset += 4
    if len(raw) < offset + 4:
        raise ValueError("Truncated Volcengine ASR payload length")
    size = struct.unpack_from(">I", raw, offset)[0]
    body = raw[offset + 4 :]
    if size != len(body) or size > MAX_PAYLOAD:
        raise ValueError("Invalid Volcengine ASR payload size")
    if compression == 1:
        decoder = zlib.decompressobj(31)
        body = decoder.decompress(body, MAX_PAYLOAD + 1)
        if len(body) > MAX_PAYLOAD or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid Volcengine ASR compressed payload")
    if error is not None:
        raise RuntimeError(f"Volcengine ASR error ({error})")
    if serialization != 1:
        raise ValueError("Volcengine ASR response must contain JSON")
    message = json.loads(body)
    if not isinstance(message, dict):
        raise ValueError("Invalid Volcengine ASR response")
    if message.get("code", 20000000) not in (0, 20000000):
        raise RuntimeError(f"Volcengine ASR error ({message['code']})")
    return message, bool(flags & 2)


class VolcengineConnection(StreamConnection):
    async def start(self):
        headers = {"X-Api-Resource-Id": self.client.resource_id, "X-Api-Connect-Id": self.task_id}
        if self.client.auth_mode == "api_key":
            headers["X-Api-Key"] = self.client.api_key
        else:
            headers["X-Api-App-Key"] = self.client.app_id
            headers["X-Api-Access-Key"] = self.client.access_key
        self.ws = await connect(
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
            additional_headers=headers,
            open_timeout=10,
            close_timeout=3,
            max_size=MAX_PAYLOAD,
            max_queue=16,
        )
        request = {
            "user": {"uid": self.task_id},
            "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "result_type": "full",
                "show_utterances": True,
            },
        }
        await self.ws.send(encode_packet(json.dumps(request).encode(), audio=False))

    async def send_audio(self, pcm: bytes):
        for offset in range(0, len(pcm), 6400):
            await self.ws.send(encode_packet(pcm[offset : offset + 6400], audio=True))

    async def finish(self):
        if not self.finished_input:
            self.finished_input = True
            await self.ws.send(encode_packet(b"", audio=True, final=True))

    async def events(self):
        text = ""
        async for raw in self.ws:
            message, final = decode_packet(raw)
            result = message.get("result", {})
            if "text" in result:
                text = result["text"]
            if "text" in result or final:
                # Full-result responses can revise previous utterances; use one cumulative segment.
                event = self.transcript("transcript", text, final)
                if event is not None:
                    yield event
            if final:
                return
        raise RuntimeError("Volcengine ASR connection closed before recognition completed")


class VolcengineRealtimeASRClient(RealtimeASRClient):
    def __init__(self, model: str, config: dict):
        if model != "bigmodel":
            raise ValueError("Unsupported Volcengine streaming ASR model")
        self.model = model
        self.auth_mode = config.get("speech_auth_mode") or "api_key"
        self.resource_id = required(config, "speech_resource_id")
        if self.resource_id not in VOLC_RESOURCES:
            raise ValueError("Unsupported Volcengine ASR resource ID")
        if self.auth_mode == "api_key":
            self.api_key = required(config, "speech_api_key")
        elif self.auth_mode == "app_key":
            self.app_id = required(config, "speech_app_id")
            self.access_key = required(config, "speech_access_key")
        else:
            raise ValueError("Unsupported Volcengine ASR authentication mode")

    def create_connection(self):
        return VolcengineConnection(self)
