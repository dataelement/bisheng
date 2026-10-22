"""Baidu Speech and Tencent Cloud native WebSocket adapters (16 kHz PCM)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from .connection import StreamConnection, app_id, required
from .realtime import RealtimeASRClient

# websockets treats 1000, 1001, and a close frame without a status (1005) as a
# normal end. Baidu uses the last of those after FINISH.
_BAIDU_OK_CLOSE = {1000, 1001, 1005}


class BaiduConnection(StreamConnection):
    async def start(self):
        self.ws = await connect(
            f"wss://vop.baidu.com/realtime_asr?sn={self.task_id}",
            proxy=None,
            open_timeout=10,
            close_timeout=3,
            max_size=1024 * 1024,
            max_queue=16,
        )
        await self.send_json(
            {
                "type": "START",
                "data": {
                    "appid": int(self.client.app_id),
                    "appkey": self.client.api_key,
                    "dev_pid": int(self.client.model),
                    "cuid": self.task_id,
                    "user": self.task_id,
                    "format": "pcm",
                    "sample": 16000,
                },
            }
        )
        # Clock starts after START so the first audio frame is not charged for the handshake.
        self.next_audio_at = time.monotonic()

    async def send_audio(self, pcm: bytes):
        # Baidu returns -3005 when audio arrives faster than realtime, including the
        # buffered tail flushed when the browser stops. 6400 bytes is 200 ms at 16 kHz.
        for offset in range(0, len(pcm), 6400):
            frame = pcm[offset : offset + 6400]
            await asyncio.sleep(max(0, self.next_audio_at - time.monotonic()))
            await self.ws.send(frame)
            self.next_audio_at = time.monotonic() + len(frame) / 32000

    async def finish(self):
        if self.finished_input:
            return
        # The official client waits out the last frame before FINISH. Sending the
        # end marker in the same instant makes Baidu fail that sentence with -3005.
        await asyncio.sleep(max(0, self.next_audio_at - time.monotonic()))
        await self.send_json({"type": "FINISH"})
        self.finished_input = True

    async def events(self):
        partials: dict[str, str] = {}
        async for raw in self.ws:
            message = json.loads(raw)
            if message.get("err_no", 0) != 0:
                raise RuntimeError(f"Baidu ASR error ({message['err_no']})")
            if message.get("type") not in ("MID_TEXT", "FIN_TEXT"):
                continue
            segment = message.get("sn")
            if not isinstance(segment, str) or not segment:
                raise ValueError("Baidu ASR response requires a sentence identifier")
            final = message["type"] == "FIN_TEXT"
            event = self.transcript(segment, message.get("result", ""), final)
            if event is not None:
                if final:
                    partials.pop(segment, None)
                else:
                    partials[segment] = message.get("result", "")
                yield event
        # The iterator returns only after a normal close. Anything else raises
        # ConnectionClosedError before this point.
        if not self.finished_input or self.ws.close_code not in _BAIDU_OK_CLOSE:
            raise RuntimeError(f"Baidu ASR connection closed before recognition completed ({self.ws.close_code})")
        # Baidu may close after FINISH without a trailing FIN_TEXT. The partial
        # already shown to the user is the completed sentence.
        for segment, text in partials.items():
            event = self.transcript(segment, text, True)
            if event is not None:
                yield event


class BaiduRealtimeASRClient(RealtimeASRClient):
    def __init__(self, model: str, config: dict):
        if not str(model or "").strip():
            raise ValueError("ASR model name is required")
        self.model = model
        self.config = dict(config)
        self.app_id = app_id(config)
        self.api_key = required(config, "speech_api_key")

    def _for_model(self, model: str):
        return type(self)(model=model, config=self.config)

    def create_connection(self):
        return BaiduConnection(self)


def tencent_url(
    app: str, secret_id: str, secret_key: str, model: str, voice_id: str, timestamp: int, nonce: int
) -> str:
    params = {
        "engine_model_type": model,
        "expired": timestamp + 3600,
        "needvad": 1,
        "nonce": nonce,
        "secretid": secret_id,
        "timestamp": timestamp,
        "voice_format": 1,
        "voice_id": voice_id,
    }
    path = f"asr.cloud.tencent.com/asr/v2/{app}"
    ordered = sorted(params.items())
    signing_text = path + "?" + "&".join(f"{key}={value}" for key, value in ordered)
    signature = base64.b64encode(hmac.new(secret_key.encode(), signing_text.encode(), hashlib.sha1).digest()).decode()
    return "wss://" + path + "?" + urlencode([*ordered, ("signature", signature)])


class TencentConnection(StreamConnection):
    async def start(self):
        url = tencent_url(
            self.client.app_id,
            self.client.secret_id,
            self.client.secret_key,
            self.client.model,
            self.task_id,
            int(time.time()),
            secrets.randbelow(9999999999) + 1,
        )
        self.ws = await connect(url, proxy=None, open_timeout=10, close_timeout=3, max_size=1024 * 1024, max_queue=16)
        async with asyncio.timeout(10):
            message = json.loads(await self.ws.recv())
            self.check_error(message)
            if message.get("code") != 0 or message.get("final") or message.get("result"):
                raise RuntimeError("Tencent ASR returned an invalid handshake")
        self.next_audio_at = time.monotonic()

    @staticmethod
    def check_error(message):
        if message.get("code", 0) != 0:
            raise RuntimeError(f"Tencent ASR error ({message['code']})")

    async def send_audio(self, pcm: bytes):
        # Pace buffered browser audio too: Tencent enforces a realtime send rate.
        for offset in range(0, len(pcm), 6400):
            frame = pcm[offset : offset + 6400]
            await asyncio.sleep(max(0, self.next_audio_at - time.monotonic()))
            await self.ws.send(frame)
            self.next_audio_at = time.monotonic() + len(frame) / 32000

    async def finish(self):
        if not self.finished_input:
            self.finished_input = True
            await self.send_json({"type": "end"})

    async def events(self):
        async for raw in self.ws:
            message = json.loads(raw)
            self.check_error(message)
            result = message.get("result")
            if result:
                event = self.transcript(
                    str(result["index"]), result.get("voice_text_str", ""), result["slice_type"] == 2
                )
                if event is not None:
                    yield event
            if message.get("final") == 1:
                if set(self.versions) - self.finals:
                    raise RuntimeError("Tencent ASR completed with unfinished sentences")
                return
        raise RuntimeError("Tencent ASR connection closed before recognition completed")


class TencentRealtimeASRClient(RealtimeASRClient):
    def __init__(self, model: str, config: dict):
        if not str(model or "").strip():
            raise ValueError("ASR model name is required")
        self.model = model
        self.config = dict(config)
        self.app_id = app_id(config)
        self.secret_id = required(config, "speech_secret_id")
        self.secret_key = required(config, "speech_secret_key")

    def _for_model(self, model: str):
        return type(self)(model=model, config=self.config)

    def create_connection(self):
        return TencentConnection(self)
