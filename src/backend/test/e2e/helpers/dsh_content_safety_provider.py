"""Test-only bounded OpenAI HTTP provider; never calls an external model.

Run with DSH_E2E_PROVIDER_KEY_FILE and an explicitly selected private bind address.
Coverage AC: AC-20, AC-21, AC-22, AC-23, AC-24, AC-27, AC-28, AC-29, AC-30, AC-31.
"""

import argparse
import copy
import hmac
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 128 * 1024
MAX_SCENARIOS = 128
SCENARIO_TTL = 3600
MAX_COUNTER = 2**63 - 1
MODEL_PATHS = {"/v1/chat/completions": "chat_posts", "/v1/responses": "responses_posts"}
MARKER = re.compile(r"F111_SCENARIO:([A-Za-z0-9_-]{1,128})")
IDENTIFIER = re.compile(r"e2e-f111-live-[A-Za-z0-9_-]{8,110}")


class InvalidScenario(ValueError):
    pass


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise InvalidScenario
        result[key] = value
    return result


def load_key(path: str) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Test provider key requires a regular 0600 file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            value = handle.read(258).decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value):
            raise ValueError("Test provider key must be a bounded random test value")
        return value
    finally:
        os.close(descriptor)


def argument_key(raw: str) -> str:
    """Compare tool-object JSON independent of whitespace/order, preserving value types."""
    if not isinstance(raw, str):
        raise InvalidScenario
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(InvalidScenario()))
    if not isinstance(value, dict):
        raise InvalidScenario
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def result_text(value) -> bool:
    if isinstance(value, str):
        return bool(value) and len(value.encode("utf8")) <= 32768
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 16
        and all(
            isinstance(part, dict)
            and set(part) == {"type", "text"}
            and part["type"] == "input_text"
            and isinstance(part["text"], str)
            for part in value
        )
        and 0 < sum(len(part["text"].encode("utf8")) for part in value) <= 32768
    )


def validate(value: dict) -> dict:
    allowed = {
        "id",
        "text",
        "parts",
        "kind",
        "arguments",
        "citation_title",
        "reasoning_channel",
        "usage",
        "finish",
        "status",
        "fragment_bytes",
        "delay_ms",
        "emit_deltas",
        "done_parts",
        "final_parts",
        "tool_name",
        "after_tool_text",
    }
    if (
        not isinstance(value, dict)
        or not set(value) <= allowed
        or not isinstance(value.get("id"), str)
        or not IDENTIFIER.fullmatch(value["id"])
    ):
        raise InvalidScenario
    result = {
        "kind": "text",
        "text": "safe synthetic reply",
        "arguments": '{"value":"safe"}',
        "citation_title": "safe title",
        "reasoning_channel": "summary",
        "usage": True,
        "finish": "normal",
        "status": 200,
        "fragment_bytes": 4096,
        "delay_ms": 0,
        "emit_deltas": True,
        "tool_name": "lookup",
    } | copy.deepcopy(value)
    if any(not isinstance(result[key], str) for key in ("kind", "finish", "reasoning_channel")):
        raise InvalidScenario
    if (
        result["kind"] not in {"text", "tool", "reasoning", "citation"}
        or result["finish"] not in {"normal", "eof", "malformed", "failed"}
        or result["reasoning_channel"] not in {"summary", "content"}
    ):
        raise InvalidScenario
    for key in ("text", "arguments", "citation_title"):
        if not isinstance(result[key], str) or len(result[key].encode("utf-8")) > 32768:
            raise InvalidScenario
    result["parts"] = result.get("parts", [result["text"]])
    result["done_parts"] = result.get("done_parts", result["parts"])
    result["final_parts"] = result.get("final_parts", result["done_parts"])
    unique = {}
    for name in ("parts", "done_parts", "final_parts"):
        parts = result[name]
        if not isinstance(parts, list) or not 1 <= len(parts) <= 16 or any(not isinstance(part, str) for part in parts):
            raise InvalidScenario
        unique[id(parts)] = parts
    if sum(len(part.encode("utf-8")) for parts in unique.values() for part in parts) > 32768:
        raise InvalidScenario
    if type(result["emit_deltas"]) is not bool:
        raise InvalidScenario
    result["versioned"] = bool({"emit_deltas", "done_parts", "final_parts"} & value.keys())
    if result["versioned"] and (result["kind"] == "tool" or result["status"] != 200):
        raise InvalidScenario
    if not result["emit_deltas"]:
        if "done_parts" in value or result["finish"] != "normal":
            raise InvalidScenario
    elif len({len(result[key]) for key in ("parts", "done_parts", "final_parts")}) != 1:
        raise InvalidScenario
    for key, low, high in (("status", 200, 599), ("fragment_bytes", 1, 4096), ("delay_ms", 0, 500)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise InvalidScenario
    if result["status"] not in {200, 400, 401, 429, 503} or type(result["usage"]) is not bool:
        raise InvalidScenario
    if (
        not isinstance(result["tool_name"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", result["tool_name"])
        or ("tool_name" in value and result["kind"] != "tool")
    ):
        raise InvalidScenario
    if "after_tool_text" in value:
        after = value["after_tool_text"]
        if (
            result["kind"] != "tool"
            or result["status"] != 200
            or result["finish"] != "normal"
            or not isinstance(after, str)
            or not after
        ):
            raise InvalidScenario
        argument_key(result["arguments"])
        total = sum(len(part.encode("utf8")) for parts in unique.values() for part in parts)
        if total + len(result["arguments"].encode("utf8")) + len(after.encode("utf8")) > 32768:
            raise InvalidScenario
    return result


@dataclass
class Scenario:
    spec: dict
    created: float = field(default_factory=time.monotonic)
    issued_calls: set[tuple[str, str]] = field(default_factory=set, repr=False)
    counts: dict = field(
        default_factory=lambda: {
            "requests": 0,
            "completed": 0,
            "finished": 0,
            "cancelled": 0,
            "usage_emitted": 0,
            "active": 0,
        }
    )


class Registry:
    def __init__(self):
        self.lock = threading.Lock()
        self.scenarios: dict[str, Scenario] = {}
        self.totals = dict.fromkeys(
            (
                "model_posts",
                "chat_posts",
                "responses_posts",
                "active",
                "finished",
                "auth_rejected",
                "invalid_requests",
                "unknown_scenarios",
                "unmarked_requests",
                "registered_requests",
            ),
            0,
        )
        self.saturated = False

    def increment_locked(self, name: str):
        if self.totals[name] == MAX_COUNTER:
            self.saturated = True
        else:
            self.totals[name] += 1

    def model_arrived(self, path: str) -> bool:
        if path not in MODEL_PATHS:
            return False
        with self.lock:
            for key in ("model_posts", MODEL_PATHS[path], "active"):
                self.increment_locked(key)
        return True

    def model_finished(self):
        with self.lock:
            self.totals["active"] -= 1
            self.increment_locked("finished")

    def record_bucket(self, name: str):
        with self.lock:
            self.increment_locked(name)

    def global_counters(self) -> dict:
        with self.lock:
            return dict(self.totals) | {"saturated": self.saturated}

    def expire(self):
        now = time.monotonic()
        for key in list(self.scenarios):
            if not self.scenarios[key].counts["active"] and now - self.scenarios[key].created >= SCENARIO_TTL:
                del self.scenarios[key]

    def register(self, value: dict) -> dict:
        spec = validate(value)
        with self.lock:
            self.expire()
            if spec["id"] in self.scenarios or len(self.scenarios) >= MAX_SCENARIOS:
                raise InvalidScenario
            scenario = Scenario(spec)
            self.scenarios[spec["id"]] = scenario
            return {"id": spec["id"], **scenario.counts}

    def counters(self, identifier: str, *, delete=False) -> dict:
        with self.lock:
            self.expire()
            scenario = self.scenarios.get(identifier)
            if scenario is None or (delete and scenario.counts["active"]):
                raise InvalidScenario
            result = {"id": identifier, **scenario.counts}
            if delete:
                del self.scenarios[identifier]
            return result

    def begin(self, request: dict) -> Scenario:
        markers = set()
        stack = [(request, 0)]
        while stack:
            value, depth = stack.pop()
            if depth > 64:
                raise InvalidScenario
            if isinstance(value, str):
                markers.update(MARKER.findall(value))
            elif isinstance(value, dict):
                stack.extend((part, depth + 1) for part in value.values())
            elif isinstance(value, list):
                stack.extend((part, depth + 1) for part in value)
        if len(markers) > 1:
            raise InvalidScenario
        with self.lock:
            self.expire()
            # The real model-management probe sends "hello" without a test marker.
            scenario = (
                self.scenarios.get(next(iter(markers)))
                if markers
                else Scenario(validate({"id": "e2e-f111-live-management-probe"}))
            )
            if scenario is None:
                self.increment_locked("unknown_scenarios")
                raise InvalidScenario
            self.increment_locked("registered_requests" if markers else "unmarked_requests")
            scenario.counts["requests"] += 1
            scenario.counts["active"] += 1
            return scenario

    def tool_turn(self, scenario: Scenario, request: dict, protocol: str, identifier: str) -> dict:
        """Only a correlated protocol result may finish this bounded synthetic tool loop."""
        spec = scenario.spec
        if "after_tool_text" not in spec:
            return spec
        history = request.get("input" if protocol == "responses" else "messages")
        if not isinstance(history, list):
            raise InvalidScenario
        expected_args = argument_key(spec["arguments"])
        with self.lock:
            calls, results = {}, set()
            for item in history:
                if not isinstance(item, dict):
                    raise InvalidScenario
                candidates = (
                    ([item] if item.get("type") == "function_call" else [])
                    if protocol == "responses"
                    else (item.get("tool_calls", []) if item.get("role") == "assistant" else [])
                )
                if not isinstance(candidates, list):
                    raise InvalidScenario
                for call in candidates:
                    if not isinstance(call, dict):
                        raise InvalidScenario
                    function = call if protocol == "responses" else call.get("function")
                    call_id = call.get("call_id" if protocol == "responses" else "id")
                    if (
                        not isinstance(function, dict)
                        or not isinstance(call_id, str)
                        or call_id in calls
                        or function.get("name") != spec["tool_name"]
                        or argument_key(function.get("arguments")) != expected_args
                    ):
                        raise InvalidScenario
                    calls[call_id] = True
                is_result = (
                    item.get("type") == "function_call_output"
                    if protocol == "responses"
                    else item.get("role") == "tool"
                )
                if is_result:
                    call_id = item.get("call_id" if protocol == "responses" else "tool_call_id")
                    value = item.get("output" if protocol == "responses" else "content")
                    if (
                        not isinstance(call_id, str)
                        or call_id not in calls
                        or call_id in results
                        or (protocol, call_id) not in scenario.issued_calls
                        or not result_text(value)
                    ):
                        raise InvalidScenario
                    results.add(call_id)
            if results:
                if set(calls) != results:
                    raise InvalidScenario
                parts = [spec["after_tool_text"]]
                return spec | {
                    "kind": "text",
                    "text": parts[0],
                    "parts": parts,
                    "done_parts": parts,
                    "final_parts": parts,
                }
            if calls:
                raise InvalidScenario
            tools = request.get("tools")
            names = []
            if isinstance(tools, list):
                for tool in tools:
                    if isinstance(tool, dict) and tool.get("type") == "function":
                        function = tool if protocol == "responses" else tool.get("function")
                        if isinstance(function, dict) and isinstance(function.get("name"), str):
                            names.append(function["name"])
            if spec["tool_name"] not in names:
                raise InvalidScenario
            issued = (protocol, "call_" + identifier)
            if len(scenario.issued_calls) >= 16 or issued in scenario.issued_calls:
                raise InvalidScenario
            scenario.issued_calls.add(issued)
            return spec

    def finish(self, scenario: Scenario, *, cancelled: bool, terminal: bool, usage: bool):
        with self.lock:
            scenario.counts["active"] -= 1
            scenario.counts["cancelled" if cancelled else "finished"] += 1
            scenario.counts["completed"] += int(terminal and not cancelled)
            scenario.counts["usage_emitted"] += int(usage)


def response_item(spec: dict, identifier: str, *, parts_key="final_parts") -> dict:
    if spec["kind"] == "tool":
        return {
            "id": "fc_" + identifier,
            "type": "function_call",
            "status": "completed",
            "call_id": "call_" + identifier,
            "name": spec.get("tool_name", "lookup"),
            "arguments": spec["arguments"],
        }
    if spec["kind"] == "reasoning":
        result = {"id": "rs_" + identifier, "type": "reasoning", "status": "completed", "summary": []}
        channel = spec["reasoning_channel"]
        result[channel] = [
            {"type": "summary_text" if channel == "summary" else "reasoning_text", "text": part}
            for part in spec[parts_key]
        ]
        return result
    annotation = (
        [
            {
                "type": "url_citation",
                "url": "https://example.invalid/synthetic",
                "title": spec["citation_title"],
                "start_index": 0,
                "end_index": 0,
            }
        ]
        if spec["kind"] == "citation"
        else []
    )
    return {
        "id": "msg_" + identifier,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": part, "annotations": annotation} for part in spec[parts_key]],
    }


def full_response(spec: dict, identifier: str, model: str, *, status="completed", output=None) -> dict:
    result = {
        "id": "resp_" + identifier,
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": model,
        "output": [response_item(spec, identifier)] if output is None else output,
        "error": None,
        "incomplete_details": None,
    }
    if spec["usage"] and status == "completed":
        result["usage"] = {
            "input_tokens": 30,
            "output_tokens": 50,
            "total_tokens": 80,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    return result


def response_events(spec: dict, identifier: str, model: str):
    yield "response.created", {"response": full_response(spec, identifier, model, status="in_progress", output=[])}
    if not spec["emit_deltas"]:
        yield "response.completed", {"response": full_response(spec, identifier, model)}
        return
    item = response_item(spec, identifier, parts_key="done_parts")
    initial = dict(item) | {"status": "in_progress"}
    if spec["kind"] == "tool":
        initial["arguments"] = ""
    elif spec["kind"] == "reasoning":
        initial["summary"] = []
        initial.pop("content", None)
    else:
        initial["content"] = []
    yield "response.output_item.added", {"output_index": 0, "item": initial}
    common = {"output_index": 0, "item_id": item["id"]}
    if spec["kind"] == "tool":
        args = spec["arguments"]
        for start in range(0, len(args), 3):
            yield "response.function_call_arguments.delta", common | {"delta": args[start : start + 3]}
        yield "response.function_call_arguments.done", common | {"arguments": args}
    else:
        reasoning = spec["kind"] == "reasoning"
        summary = reasoning and spec["reasoning_channel"] == "summary"
        for index, value in enumerate(spec["parts"]):
            position = common | {"summary_index" if summary else "content_index": index}
            part = (
                {"type": "summary_text" if summary else "reasoning_text", "text": ""}
                if reasoning
                else {"type": "output_text", "text": "", "annotations": []}
            )
            if not reasoning or summary:
                yield (
                    "response.reasoning_summary_part.added" if summary else "response.content_part.added",
                    position | {"part": part},
                )
            channel = "reasoning_summary_text" if summary else "reasoning_text" if reasoning else "output_text"
            for start in range(0, len(value), 3):
                yield f"response.{channel}.delta", position | {"delta": value[start : start + 3]}
            completed = spec["done_parts"][index]
            yield f"response.{channel}.done", position | {"text": completed}
            if not reasoning or summary:
                final_part = {"type": "summary_text", "text": completed} if summary else item["content"][index]
                yield (
                    "response.reasoning_summary_part.done" if summary else "response.content_part.done",
                    position | {"part": final_part},
                )
    if spec["finish"] == "eof":
        return
    if spec["finish"] == "malformed":
        yield "malformed", {}
        return
    yield "response.output_item.done", {"output_index": 0, "item": item}
    status = "failed" if spec["finish"] == "failed" else "completed"
    yield "response." + status, {"response": full_response(spec, identifier, model, status=status)}


class ProviderServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, key: str):
        self.key = key
        self.registry = Registry()
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, ProviderHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Unexpected request failures need a signal without body, headers or traceback.
        sys.stderr.write("Test provider request failed\n")


class ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "F111Synthetic/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)
        self.sent_usage = False
        self.sent_terminal = False
        self.stream_deadline = None
        self.response_started = False

    def log_message(self, *_):
        return

    def answer(self, status: int, body: dict | bytes):
        raw = body if isinstance(body, bytes) else encoded(body)
        self.response_started = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(raw)
        self.wfile.flush()

    def authenticated(self) -> bool:
        values = self.headers.get_all("Authorization", [])
        if len(values) != 1:
            return False
        try:
            return hmac.compare_digest(values[0].encode("ascii"), ("Bearer " + self.server.key).encode("ascii"))
        except UnicodeError:
            return False

    def path_only(self) -> str:
        path = urlsplit(self.path)
        if path.query or path.fragment or path.scheme or path.netloc:
            raise InvalidScenario
        return path.path

    def body(self) -> dict:
        lengths = self.headers.get_all("Content-Length", [])
        if (
            len(lengths) != 1
            or not lengths[0].isascii()
            or not lengths[0].isdecimal()
            or self.headers.get("Transfer-Encoding")
        ):
            raise InvalidScenario
        size = int(lengths[0])
        if not 0 < size <= MAX_BODY:
            raise InvalidScenario
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise InvalidScenario
        value = json.loads(
            raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(InvalidScenario())
        )
        if not isinstance(value, dict):
            raise InvalidScenario
        return value

    def do_GET(self):
        try:
            path = self.path_only()
            if path == "/healthz":
                self.answer(200, {"ready": True, "synthetic": True})
            elif not self.authenticated():
                self.answer(
                    401, {"error": {"code": "test_auth_required", "message": "Test provider authentication required"}}
                )
            elif path == "/v1/models":
                self.answer(
                    200,
                    {
                        "object": "list",
                        "data": [{"id": "f111-synthetic", "object": "model", "created": 1, "owned_by": "f111-test"}],
                    },
                )
            elif path == "/__control/counters":
                self.answer(200, self.server.registry.global_counters())
            elif path.startswith("/__control/scenarios/"):
                self.answer(200, self.server.registry.counters(path.removeprefix("/__control/scenarios/")))
            else:
                self.answer(404, {"error": {"code": "test_not_found", "message": "Unknown test endpoint"}})
        except (ValueError, RecursionError):
            self.answer(400, {"error": {"code": "test_invalid", "message": "Invalid test request"}})

    def do_DELETE(self):
        try:
            path = self.path_only()
            if not self.authenticated():
                self.answer(
                    401, {"error": {"code": "test_auth_required", "message": "Test provider authentication required"}}
                )
            elif path.startswith("/__control/scenarios/"):
                self.answer(200, self.server.registry.counters(path.removeprefix("/__control/scenarios/"), delete=True))
            else:
                self.answer(404, {"error": {"code": "test_not_found", "message": "Unknown test endpoint"}})
        except (ValueError, RecursionError):
            self.answer(400, {"error": {"code": "test_invalid", "message": "Invalid test request"}})

    def do_POST(self):
        scenario = None
        terminal = usage = cancelled = False
        # Count every parsed model-path POST before auth, body or marker validation.
        arrived = self.server.registry.model_arrived(urlsplit(self.path).path)
        try:
            if not self.authenticated():
                if arrived:
                    self.server.registry.record_bucket("auth_rejected")
                self.answer(
                    401, {"error": {"code": "test_auth_required", "message": "Test provider authentication required"}}
                )
                return
            path = self.path_only()
            body = self.body()
            if path == "/__control/scenarios":
                self.answer(200, self.server.registry.register(body))
                return
            if path not in MODEL_PATHS:
                self.answer(404, {"error": {"code": "test_not_found", "message": "Unknown test endpoint"}})
                return
            if "stream" in body and type(body["stream"]) is not bool:
                raise InvalidScenario
            scenario = self.server.registry.begin(body)
            spec = scenario.spec
            if path.endswith("/chat/completions") and spec["versioned"]:
                raise InvalidScenario
            if spec["status"] != 200:
                self.answer(
                    spec["status"],
                    {
                        "error": {
                            "code": "synthetic_upstream",
                            "type": "synthetic_upstream",
                            "message": "Synthetic upstream failure",
                        }
                    },
                )
                return
            identifier = secrets.token_hex(8)
            model = body.get("model", "f111-synthetic")
            if not isinstance(model, str) or len(model) > 256:
                raise InvalidScenario
            spec = self.server.registry.tool_turn(
                scenario, body, "responses" if path.endswith("/responses") else "chat", identifier
            )
            if body.get("stream", False):
                terminal, usage = self.stream(spec, identifier, model, path.endswith("/responses"))
            elif spec["finish"] == "eof":
                self.close_connection = True
            elif spec["finish"] == "malformed":
                self.answer(200, b"{invalid")
            elif spec["finish"] == "failed":
                if path.endswith("/responses"):
                    self.answer(200, full_response(spec, identifier, model, status="failed"))
                else:
                    self.answer(503, {"error": {"code": "synthetic_upstream", "message": "Synthetic upstream failure"}})
            else:
                result = (
                    full_response(spec, identifier, model)
                    if path.endswith("/responses")
                    else self.chat(spec, identifier, model)
                )
                self.answer(200, result)
                terminal = True
                usage = spec["usage"]
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            cancelled = True
            self.close_connection = True
        except (ValueError, UnicodeError, RecursionError):
            if arrived:
                self.server.registry.record_bucket("invalid_requests")
            if not self.response_started:
                self.answer(400, {"error": {"code": "test_invalid", "message": "Invalid test request"}})
            else:
                self.close_connection = True
        finally:
            if scenario is not None:
                self.server.registry.finish(
                    scenario,
                    cancelled=cancelled,
                    terminal=terminal or self.sent_terminal,
                    usage=usage or self.sent_usage,
                )
            if arrived:
                self.server.registry.model_finished()

    @staticmethod
    def chat(spec: dict, identifier: str, model: str) -> dict:
        message = {"role": "assistant", "content": "".join(spec["parts"])}
        if spec["kind"] == "tool":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_" + identifier,
                        "type": "function",
                        "function": {"name": spec.get("tool_name", "lookup"), "arguments": spec["arguments"]},
                    }
                ],
            }
        if spec["kind"] == "reasoning":
            message["reasoning_content"] = "".join(spec["parts"])
            message["content"] = "safe synthetic reply"
        result = {
            "id": "chatcmpl_" + identifier,
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [
                {"index": 0, "message": message, "finish_reason": "tool_calls" if spec["kind"] == "tool" else "stop"}
            ],
        }
        if spec["usage"]:
            result["usage"] = {"prompt_tokens": 30, "completion_tokens": 50, "total_tokens": 80}
        return result

    def fragment(self, raw: bytes, spec: dict):
        for start in range(0, len(raw), spec["fragment_bytes"]):
            if self.stream_deadline is not None and time.monotonic() >= self.stream_deadline:
                raise TimeoutError
            chunk = raw[start : start + spec["fragment_bytes"]]
            self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.flush()

    def stream(self, spec: dict, identifier: str, model: str, responses: bool) -> tuple[bool, bool]:
        self.stream_deadline = time.monotonic() + 30
        self.response_started = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        usage = False
        if responses:
            for sequence, (kind, data) in enumerate(response_events(spec, identifier, model)):
                raw = (
                    b"data: {invalid\n\n"
                    if kind == "malformed"
                    else b"event: "
                    + kind.encode()
                    + b"\ndata: "
                    + encoded({"type": kind, "sequence_number": sequence, **data})
                    + b"\n\n"
                )
                self.fragment(raw, spec)
                usage = usage or (kind == "response.completed" and spec["usage"])
                self.sent_usage = usage
                self.sent_terminal = kind == "response.completed"
                if spec["delay_ms"]:
                    time.sleep(spec["delay_ms"] / 1000)
        else:
            base = {"id": "chatcmpl_" + identifier, "object": "chat.completion.chunk", "created": 1, "model": model}
            chunks = []
            if spec["kind"] == "tool":
                arguments = spec["arguments"]
                for index, start in enumerate(range(0, len(arguments), 3)):
                    tool = {"index": 0, "function": {"arguments": arguments[start : start + 3]}}
                    if index == 0:
                        tool |= {"id": "call_" + identifier, "type": "function"}
                        tool["function"]["name"] = spec.get("tool_name", "lookup")
                    chunks.append({"tool_calls": [tool]})
            else:
                value = "".join(spec["parts"])
                for start in range(0, len(value), 3):
                    chunks.append(
                        {"reasoning_content" if spec["kind"] == "reasoning" else "content": value[start : start + 3]}
                    )
            for delta in chunks:
                self.fragment(
                    b"data: "
                    + encoded(base | {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
                    + b"\n\n",
                    spec,
                )
                if spec["delay_ms"]:
                    time.sleep(spec["delay_ms"] / 1000)
            if spec["finish"] == "malformed":
                self.fragment(b"data: {invalid\n\n", spec)
            elif spec["finish"] == "failed":
                self.fragment(
                    b"data: "
                    + encoded({"error": {"code": "synthetic_upstream", "message": "Synthetic upstream failure"}})
                    + b"\n\n",
                    spec,
                )
            elif spec["finish"] != "eof":
                self.fragment(
                    b"data: "
                    + encoded(
                        base
                        | {
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": "tool_calls" if spec["kind"] == "tool" else "stop",
                                }
                            ]
                        }
                    )
                    + b"\n\n",
                    spec,
                )
                if spec["usage"]:
                    self.fragment(
                        b"data: "
                        + encoded(
                            base
                            | {
                                "choices": [],
                                "usage": {"prompt_tokens": 30, "completion_tokens": 50, "total_tokens": 80},
                            }
                        )
                        + b"\n\n",
                        spec,
                    )
                    usage = True
                    self.sent_usage = True
                self.fragment(b"data: [DONE]\n\n", spec)
                self.sent_terminal = True
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        return spec["finish"] == "normal", usage


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded test-only OpenAI provider; no external models")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError
        key = load_key(os.environ["DSH_E2E_PROVIDER_KEY_FILE"])
        with ProviderServer((args.host, args.port), key) as server:
            server.serve_forever(poll_interval=0.25)
    except (OSError, ValueError, KeyError):
        parser.exit(2, "Test provider could not start; check private bind/key file\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
