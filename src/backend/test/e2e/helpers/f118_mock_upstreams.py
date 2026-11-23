"""F118 test-only model/ETL upstreams; run in the private E2E network.

Run this file with --host and --port, using the existing backend environment.
Only upstream responses are simulated; no business config or storage is loaded.
Counters and the single pending failure are in-memory and require one worker.
"""

import argparse
import base64
import binascii
import hashlib
import json
import math
import struct
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODELS = {"f118-embed-8": 8, "f118-embed-16": 16}
CHAT_TEXT = "F118 mock response."


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "param": None, "code": "f118_mock_error"}},
        status_code=status,
    )


async def _body(request: Request) -> dict | None:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.totals = {"embedding": 0, "chat_nonstream": 0, "chat_stream": 0, "etl": 0}
            self.embedding = {}
            self.etl = {}
            self.pending_failure = None

    def stats(self):
        with self.lock:
            return {
                "totals": dict(self.totals),
                "embedding": [dict(self.embedding[key]) for key in sorted(self.embedding)],
                "etl": [dict(self.etl[key]) for key in sorted(self.etl)],
                "pending_failure": dict(self.pending_failure) if self.pending_failure else None,
            }

    def arm(self, rule: dict) -> bool:
        with self.lock:
            if self.pending_failure is not None:
                return False
            self.pending_failure = dict(rule)
            return True

    def _consume(self, kind: str, values: list[str], model: str | None = None) -> bool:
        # Called only while holding the same lock as counters/reset/control.
        rule = self.pending_failure
        if (
            rule
            and rule["kind"] == kind
            and ("model" not in rule or rule["model"] == model)
            and any(rule["marker"] in value for value in values)
        ):
            self.pending_failure = None
            return True
        return False

    def record_embedding(self, model: str, texts: list[str]) -> bool:
        with self.lock:
            self.totals["embedding"] += 1
            failed = self._consume("embedding", texts, model)
            for text in texts:
                ident = _sha256(text.encode())
                row = self.embedding.setdefault(
                    (model, ident), {"model": model, "input_sha256": ident, "attempts": 0, "failed": 0}
                )
                row["attempts"] += 1
                row["failed"] += int(failed)
            return failed

    def record_etl(self, filename: str, content: bytes) -> bool:
        with self.lock:
            self.totals["etl"] += 1
            failed = self._consume("etl", [filename])
            ident = _sha256(content)
            row = self.etl.setdefault(
                (filename, ident), {"filename": filename, "content_sha256": ident, "attempts": 0, "failed": 0}
            )
            row["attempts"] += 1
            row["failed"] += int(failed)
            return failed

    def record_chat(self, stream: bool) -> int:
        with self.lock:
            key = "chat_stream" if stream else "chat_nonstream"
            self.totals[key] += 1
            return self.totals[key]


def _vector(model: str, text: str, dimension: int) -> bytes:
    digest = hashlib.sha256((model + "\0" + text).encode()).digest()
    values = [(value + 1) / 256 for value in digest[:dimension]]
    norm = math.sqrt(sum(value * value for value in values))
    return struct.pack("<" + "f" * dimension, *(value / norm for value in values))


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    state = _State()

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/__control/stats")
    async def stats():
        return state.stats()

    @app.post("/__control/reset")
    async def reset():
        state.reset()
        return {"status": "ok"}

    @app.post("/__control/fail-next")
    async def fail_next(request: Request):
        body = await _body(request)
        if (
            body is None
            or set(body) - {"kind", "marker", "model"}
            or not isinstance(body.get("kind"), str)
            or body.get("kind") not in {"embedding", "etl"}
            or not isinstance(body.get("marker"), str)
            or not body["marker"].strip()
            or (
                "model" in body
                and (body["kind"] != "embedding" or not isinstance(body["model"], str) or body["model"] not in MODELS)
            )
        ):
            return _error("Expected embedding/etl, nonempty marker, and optional supported embedding model")
        if not state.arm(body):
            return _error("A failure is already pending; consume it or reset first", 409)
        return {"status": "ok"}

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        body = await _body(request)
        if body is None or not isinstance(body.get("model"), str) or body["model"] not in MODELS:
            return _error("Supported embedding models are f118-embed-8 and f118-embed-16")
        model = body["model"]
        dimension = MODELS[model]
        if "dimensions" in body and (type(body["dimensions"]) is not int or body["dimensions"] != dimension):
            return _error("dimensions must equal the selected model's fixed dimension")
        texts = body.get("input")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or not all(isinstance(text, str) for text in texts):
            return _error("input must be a string or a nonempty list of strings")
        encoding = body.get("encoding_format", "base64")
        if not isinstance(encoding, str) or encoding not in {"float", "base64"}:
            return _error("encoding_format must be float or base64")
        if state.record_embedding(model, texts):
            # HTTP 400 is deliberately nonretryable by the real OpenAI SDK.
            return _error("F118 controlled once-only embedding failure")
        data = []
        for index, text in enumerate(texts):
            raw = _vector(model, text, dimension)
            value = (
                base64.b64encode(raw).decode()
                if encoding == "base64"
                else list(struct.unpack("<" + "f" * dimension, raw))
            )
            data.append({"object": "embedding", "index": index, "embedding": value})
        tokens = sum(max(1, len(text.encode()) // 4) for text in texts)
        return {
            "object": "list",
            "model": model,
            "data": data,
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await _body(request)
        if body is None or body.get("model") != "f118-chat":
            return _error("Supported chat model is f118-chat")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages or body.get("tools"):
            return _error("Expected text chat messages; tools are outside this fixture")
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                return _error("Expected text chat messages")
            content = message.get("content")
            if isinstance(content, list):
                if not all(
                    isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
                    for part in content
                ):
                    return _error("Only text content is supported")
            elif not isinstance(content, str):
                return _error("Only text content is supported")
        stream = body.get("stream", False)
        options = body.get("stream_options")
        if options is None:
            options = {}
        if type(stream) is not bool or not isinstance(options, dict):
            return _error("stream must be boolean and stream_options an object")
        if "include_usage" in options and type(options["include_usage"]) is not bool:
            return _error("include_usage must be boolean")
        number = state.record_chat(stream)
        common = {"id": f"chatcmpl-f118-{number}", "created": int(time.time()), "model": "f118-chat"}
        usage = {"prompt_tokens": 1, "completion_tokens": 4, "total_tokens": 5}
        if not stream:
            return {
                **common,
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": CHAT_TEXT}, "finish_reason": "stop"}
                ],
                "usage": usage,
            }

        def events():
            for delta, finish in [
                ({"role": "assistant", "content": ""}, None),
                ({"content": CHAT_TEXT}, None),
                ({}, "stop"),
            ]:
                chunk = {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                yield "data: " + json.dumps(chunk) + "\n\n"
            if options.get("include_usage"):
                yield (
                    "data: "
                    + json.dumps({**common, "object": "chat.completion.chunk", "choices": [], "usage": usage})
                    + "\n\n"
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1/etl4llm/predict")
    async def etl(request: Request):
        body = await _body(request)
        if (
            body is None
            or not isinstance(body.get("filename"), str)
            or not body["filename"]
            or body.get("mode") != "partition"
        ):
            return JSONResponse(
                {"status_code": 400, "message": "Expected filename and partition mode"}, status_code=400
            )
        data = body.get("b64_data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], str):
            return JSONResponse({"status_code": 400, "message": "Expected one base64 file"}, status_code=400)
        try:
            content = base64.b64decode(data[0], validate=True)
        except (ValueError, binascii.Error):
            return JSONResponse({"status_code": 400, "message": "Invalid base64 file"}, status_code=400)
        if state.record_etl(body["filename"], content):
            return JSONResponse(
                {"status_code": 503, "message": "F118 controlled once-only ETL failure"}, status_code=503
            )
        return {
            "status_code": 200,
            "partitions": [],
            "text": f"F118_ETL_FIXTURE {body['filename']}\nDeterministic test document for the real indexing pipeline.",
        }

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Explicit private E2E bind address")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
