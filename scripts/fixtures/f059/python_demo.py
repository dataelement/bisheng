"""Minimal real SQLite/SDK/WebSocket application for the dedicated F059 suite."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from bisheng_sdk import auth, retrieve, storage

HERE = Path(__file__).resolve().parent
VERSION = (HERE / "fixture-version.txt").read_text().strip()
CAPABILITIES = json.loads((HERE / "capabilities.json").read_text())
DATABASE = Path(os.environ.get("BISHENG_APP_DB_PATH", "/data/app.db"))
BASE = os.environ.get("BISHENG_APP_BASE_PATH", "").rstrip("/")


def initialize():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE, timeout=5) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, value TEXT NOT NULL DEFAULT 'initial')"
        )
        connection.execute("INSERT OR IGNORE INTO items(id,value) VALUES(1,'initial')")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def reply(self, value, status=200):
        body = json.dumps(value, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if BASE and path.startswith(BASE + "/"):
            path = path[len(BASE) :]
        if path in {"/", "/health", "/healthz"}:
            return self.reply({"status": "ok", "application": "e2e-f059-python", "version": VERSION})
        if path == "/items":
            with sqlite3.connect(DATABASE, timeout=5) as connection:
                rows = connection.execute("SELECT id,value FROM items ORDER BY id").fetchall()
            return self.reply({"items": [{"id": row[0], "value": row[1]} for row in rows]})
        try:
            with auth.bind(self.headers.items()):
                identity = auth.current_user()
                if path == "/ws":
                    return self.websocket()
                if path == "/sdk/identity":
                    return self.reply(
                        {
                            "subject_kind": identity.subject_kind,
                            "app_id_matches": identity.app_id == os.environ.get("BISHENG_APP_ID"),
                            "obo_present": bool(self.headers.get("X-BiSheng-Access-Token")),
                        }
                    )
                if path == "/sdk/storage-roundtrip":
                    key, content = "e2e-f059/" + uuid4().hex + ".bin", os.urandom(32)
                    metadata = storage.put(key, content, content_type="application/octet-stream")
                    downloaded, details = storage.get(key), storage.stat(key)
                    listed = storage.list("e2e-f059/")
                    if (
                        downloaded != content
                        or metadata.size != len(content)
                        or details.size != len(content)
                        or key not in {item.path for item in listed}
                    ):
                        raise RuntimeError("attachment_roundtrip_mismatch")
                    storage.delete(key)
                    return self.reply(
                        {"storage_roundtrip": True, "bytes": len(content), "subject_kind": identity.subject_kind}
                    )
                if path == "/sdk/retrieve":
                    ids = CAPABILITIES.get("knowledge_base_ids", [])
                    if not ids:
                        return self.reply({"error": "knowledge_not_configured"}, 409)
                    result = retrieve.search("e2e-f059 acceptance", knowledge_base_ids=ids, top_k=3)
                    return self.reply(
                        {
                            "total": result.total,
                            "chunks": [item.content for item in result.chunks],
                            "subject_kind": identity.subject_kind,
                        }
                    )
                if path == "/sdk/model":
                    return self.model()
                return self.reply({"error": "not_found"}, 404)
        except Exception as error:
            # Safe type only: SDK/network exceptions may include private URLs.
            return self.reply({"error": type(error).__name__}, 502)

    def model(self):
        import httpx

        name = CAPABILITIES.get("model_name")
        if not name:
            return self.reply({"error": "model_not_configured"}, 409)
        visitor = self.headers.get("X-BiSheng-Access-Token")
        base, token = os.environ.get("OPENAI_BASE_URL"), os.environ.get("OPENAI_API_KEY")
        if not visitor or not base or not token:
            return self.reply({"error": "model_or_visitor_handle_missing"}, 503)
        # Models use the real OpenAI-compatible HTTP surface; the SDK's public
        # modules are auth/retrieve/storage and intentionally have no model API.
        with httpx.Client(timeout=45, trust_env=True, follow_redirects=False) as client:
            response = client.post(
                base.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + token, "X-BiSheng-Access-Token": visitor},
                json={
                    "model": name,
                    "messages": [{"role": "user", "content": "Reply with one short greeting."}],
                    "stream": False,
                },
            )
        if response.status_code != 200:
            return self.reply({"error": "platform_model_refused", "http_status": response.status_code}, 502)
        result = response.json()
        text = result["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text:
            raise RuntimeError("model_output_missing")
        return self.reply({"model": name, "content": text, "subject_kind": auth.current_user().subject_kind})

    def websocket(self):
        if self.headers.get("Upgrade", "").lower() != "websocket" or self.headers.get("Sec-WebSocket-Version") != "13":
            return self.reply({"error": "websocket_handshake_required"}, 400)
        key = self.headers.get("Sec-WebSocket-Key", "")
        if len(base64.b64decode(key, validate=True)) != 16:
            return self.reply({"error": "websocket_key_invalid"}, 400)
        accepted = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accepted)
        self.end_headers()
        self.connection.settimeout(30)
        while True:
            head = self.rfile.read(2)
            if len(head) != 2:
                return
            opcode, masked, length = head[0] & 15, bool(head[1] & 128), head[1] & 127
            if length == 126:
                length = struct.unpack("!H", self.rfile.read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.rfile.read(8))[0]
            if not masked or length > 65535 or head[0] & 112:
                return
            mask, payload = self.rfile.read(4), self.rfile.read(length)
            if len(mask) != 4 or len(payload) != length:
                return
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 8:
                self.wfile.write(bytes([136, len(payload)]) + payload)
                return
            if opcode not in {1, 9} or head[0] & 128 == 0:
                return
            opcode = 10 if opcode == 9 else 1
            size = (
                bytes([128 | opcode, len(payload)])
                if len(payload) < 126
                else bytes([128 | opcode, 126]) + struct.pack("!H", len(payload))
            )
            self.wfile.write(size + payload)
            self.wfile.flush()


if __name__ == "__main__":
    initialize()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
