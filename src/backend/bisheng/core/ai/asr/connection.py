"""Shared streaming connection state; protocol adapters own the wire format."""

import json
import uuid


class StreamConnection:
    def __init__(self, client):
        self.client = client
        self.ws = None
        self.task_id = uuid.uuid4().hex
        self.finished_input = False
        self.finals: set[str] = set()
        self.versions: dict[str, int] = {}

    async def send_json(self, payload: dict):
        await self.ws.send(json.dumps(payload))

    def transcript(self, segment: str, text: str, final: bool) -> dict | None:
        if segment in self.finals:
            return None
        if final:
            self.finals.add(segment)
        version = self.versions.get(segment, 0) + 1
        self.versions[segment] = version
        return {"type": "final" if final else "partial", "segment_id": segment, "version": version, "text": text}

    async def close(self):
        if self.ws is not None:
            ws, self.ws = self.ws, None
            await ws.close()


def required(config: dict, key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"ASR configuration requires {key}")
    return value


def app_id(config: dict) -> str:
    value = required(config, "speech_app_id")
    if not value.isascii() or not value.isdecimal():
        raise ValueError("ASR AppID must contain digits")
    return value
