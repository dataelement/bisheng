"""Run production assistant dispatch, streaming, persistence and terminal bodies.

AST loading isolates LLM providers and service startup. The task pool, ChatClient,
stream callback, event loop and SQLite history are real; model generation and
external service/schema collaborators are controlled fixtures.

Run with: python -m unittest discover -s test/chat -p 'test_assistant_stop*.py'
"""

import ast
import asyncio
import concurrent.futures
import contextvars
import json
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

BACKEND = Path(__file__).resolve().parents[2]


def load_classes(path, names, namespace):
    tree = ast.parse((BACKEND / path).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(BACKEND / path), "exec"), namespace)


class Response(SimpleNamespace):
    def dict(self):
        return {"category": "processing", "is_bot": True, "files": [], "extra": "{}", **vars(self)}


class AssistantError(Exception):
    def __init__(self, exception):
        super().__init__(str(exception))

    async def websocket_close_message(self, websocket, close_ws=False):
        await websocket.send_json({"category": "error", "type": "error", "message": {"status_code": 10400}})


class AssistantStopLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.frames = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, category TEXT, message TEXT, remark TEXT)")
        trace = contextvars.ContextVar("trace", default="same-websocket-trace")
        namespace = {
            "asyncio": asyncio,
            "concurrent": concurrent,
            "contextvars": contextvars,
            "threading": threading,
            "time": time,
            "json": json,
            "Queue": Queue,
            "logger": Mock(),
            "trace_id_var": trace,
            "settings": SimpleNamespace(get_from_db=lambda key: {}),
            "WorkType": SimpleNamespace(GPTS="assistant"),
            "ChatResponse": Response,
            "ChatMessageModel": Response,
            "BaseErrorCode": type("DomainError", (Exception,), {}),
            "AssistantOtherError": AssistantError,
            "ApplicationTypeEnum": SimpleNamespace(ASSISTANT="assistant"),
            "BaseTelemetryTypeEnum": SimpleNamespace(APPLICATION_PROCESS="process"),
            "ApplicationProcessEventData": Response,
            "telemetry_service": SimpleNamespace(log_event=AsyncMock()),
            "select_registry_items_for_persistence": lambda *args: [],
            "strip_unregistered_citation_markers": lambda answer, items: answer,
            "save_message_citations": AsyncMock(),
            "AsyncCallbackHandler": object,
            "extract_reasoning_content": lambda chunk: chunk or "",
        }
        load_classes("bisheng/utils/threadpool.py", {"ThreadPoolManager"}, namespace)
        self.pool = namespace["ThreadPoolManager"](1)
        namespace["thread_pool"] = self.pool
        load_classes(
            "bisheng/api/v1/callback.py",
            {
                "AsyncStreamingLLMCallbackHandler",
                "AsyncGptsLLMCallbackHandler",
                "AsyncGptsDebugCallbackHandler",
            },
            namespace,
        )
        load_classes("bisheng/common/chat/client.py", {"ChatClient"}, namespace)
        self.client_class = namespace["ChatClient"]

        def insert(row):
            cursor = self.db.execute(
                "INSERT INTO history(category,message,remark) VALUES(?,?,?)",
                (row.category, row.message, row.remark),
            )
            self.db.commit()
            row.id = cursor.lastrowid
            return row

        namespace["ChatMessageDao"] = SimpleNamespace(insert_one=insert)
        self.client = self.client_class(None, "client", "app", "chat", 7, None, "assistant", None)
        self.client.chat_history = [{"category": "question"}, {"category": "answer"}]
        self.client.new_session = SimpleNamespace(name="existing")

        async def send_json(frame):
            # Real websocket sends can suspend, including while cancellation is pending.
            await asyncio.sleep(0)
            self.frames.append(frame)

        self.client.websocket = SimpleNamespace(send_json=send_json)
        self.client.init_gpts_agent = AsyncMock()
        self.client.get_latest_history = AsyncMock(return_value=[])
        self.client.generate_session_title = AsyncMock()
        self.callback = namespace["AsyncGptsDebugCallbackHandler"](
            self.client.websocket,
            "app",
            "chat",
            stream_queue=self.client.stream_queue,
        )
        self.agent = SimpleNamespace(
            llm=SimpleNamespace(streaming=True),
            reset_citation_registry_items=Mock(),
            collect_citation_registry_items=lambda: [],
            run=self.generate,
        )
        self.client.gpts_agent = self.agent
        self.tokens = ["APP_STREAM_1030R\n"] * 234 + ["APP_STREAM_"]
        self.reasoning = ""
        self.suppress_cancel = False

    async def generate(self, prompt, *args):
        await self.callback.on_chat_model_start({}, [])
        if prompt == "NEXT":
            await self.callback.on_llm_new_token("APP_NEXT_OK")
            return [SimpleNamespace(content="APP_NEXT_OK")]
        for token in self.tokens:
            await self.callback.on_llm_new_token(token)
        if self.reasoning:
            await self.callback.on_llm_new_token("", chunk=self.reasoning)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if self.suppress_cancel:
                return [SimpleNamespace(content="APP_STREAM_1030R\n" * 2000)]
            raise
        return [SimpleNamespace(content="APP_STREAM_1030R\n" * 2000)]

    def history(self):
        # Read committed history independently of the client cache, as a reload does.
        return self.db.execute("SELECT category,message,remark FROM history ORDER BY id").fetchall()

    def tasks(self):
        return [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    async def drain(self):
        for _ in range(1000):
            if not self.tasks():
                return
            await asyncio.sleep(0)
        self.assertEqual(self.tasks(), [], "assistant work must settle before another round")

    async def start_and_stop(self):
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await asyncio.wait_for(self.started.wait(), timeout=1)
        await self.client.handle_message({"action": "stop"})
        await self.drain()

    async def asyncTearDown(self):
        for task in self.tasks():
            task.cancel()
        if self.tasks():
            await asyncio.gather(*self.tasks(), return_exceptions=True)
        self.pool.tear_down()
        self.db.close()

    async def test_stop_commits_partial_history_before_one_close_then_next_round(self):
        await self.start_and_stop()
        answers = [row for row in self.history() if row[0] == "answer"]
        self.assertEqual(answers, [("answer", "".join(self.tokens), "break_answer")])
        terminal = [(f.get("category"), f.get("type")) for f in self.frames]
        self.assertEqual(terminal.count(("processing", "close")), 1)
        self.assertLess(terminal.index(("answer", "end")), terminal.index(("processing", "close")))
        self.assertIsInstance(next(f["message_id"] for f in self.frames if f.get("category") == "answer"), int)
        self.release.set()
        await asyncio.sleep(0)
        self.assertEqual([row for row in self.history() if row[0] == "answer"], answers)
        await self.client.handle_message({"inputs": {"input": "NEXT"}})
        await self.drain()
        self.assertEqual(
            [row for row in self.history() if row[0] == "answer"], [*answers, ("answer", "APP_NEXT_OK", "")]
        )
        self.assertEqual(self.frames[-1]["type"], "close")

    async def test_reasoning_uses_its_own_content(self):
        self.reasoning = "partial reasoning"
        await self.start_and_stop()
        self.assertIn(("reasoning_answer", self.reasoning, "break_answer"), self.history())

    async def test_stop_before_tokens_persists_empty_stopped_answer(self):
        self.tokens = []
        await self.start_and_stop()
        self.assertIn(("answer", "", "break_answer"), self.history())

    async def test_repeated_stop_keeps_single_history_record(self):
        await self.start_and_stop()
        before = self.history()
        await self.client.handle_message({"action": "stop"})
        await self.drain()
        self.assertEqual(self.history(), before)

    async def test_model_cancellation_suppression_preserves_stopped_history(self):
        self.suppress_cancel = True
        await self.start_and_stop()
        self.assertEqual(
            [row for row in self.history() if row[0] == "answer"],
            [
                ("answer", "".join(self.tokens), "break_answer"),
            ],
        )

    async def test_normal_completion_preserves_full_answer(self):
        self.release.set()
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await self.drain()
        self.assertIn(("answer", "APP_STREAM_1030R\n" * 2000, ""), self.history())
        self.assertEqual(self.frames[-1]["type"], "close")

    async def test_stop_during_terminal_send_allows_completion_to_settle(self):
        self.release.set()
        terminal_started = asyncio.Event()
        terminal_release = asyncio.Event()
        original_send = self.client.websocket.send_json

        async def delayed_terminal(frame):
            if frame.get("category") == "processing" and frame.get("type") == "close":
                terminal_started.set()
                await terminal_release.wait()
            await original_send(frame)

        self.client.websocket.send_json = delayed_terminal
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await asyncio.wait_for(terminal_started.wait(), 1)
        stop = asyncio.create_task(self.client.handle_message({"action": "stop"}))
        await asyncio.sleep(0)
        terminal_release.set()
        await stop
        await self.drain()
        self.assertEqual(self.frames[-1]["type"], "close")
        self.assertEqual([row[2] for row in self.history() if row[0] == "answer"], [""])

    async def test_immediate_stop_clears_previous_round_buffer(self):
        self.client.stream_queue.put({"type": "answer", "content": "previous round"})
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await self.client.handle_message({"action": "stop"})
        await self.drain()
        self.assertEqual([row for row in self.history() if row[0] == "answer"], [("answer", "", "break_answer")])
        self.assertEqual(self.frames[-1]["type"], "close")

    async def test_stop_during_initialization_settles_before_question_acceptance(self):
        init_started = asyncio.Event()

        async def initialize():
            init_started.set()
            await asyncio.Event().wait()

        self.client.init_gpts_agent = initialize
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await init_started.wait()
        await self.client.handle_message({"action": "stop"})
        await self.drain()
        self.assertEqual(self.history(), [])
        self.assertEqual(self.frames[-1]["type"], "close")

    async def test_stop_storage_error_is_visible_before_input_reopens(self):
        original_add = self.client.add_message

        async def fail_stopped_answer(msg_type, message, category, remark=""):
            if remark == "break_answer":
                raise RuntimeError("history write failed")
            return await original_add(msg_type, message, category, remark)

        self.client.add_message = fail_stopped_answer
        await self.start_and_stop()
        terminal = [(frame.get("category"), frame.get("type")) for frame in self.frames]
        self.assertLess(terminal.index(("error", "error")), terminal.index(("processing", "close")))
        self.assertEqual([row for row in self.history() if row[0] == "answer"], [])

    async def test_stop_leaves_other_connection_with_same_trace_running(self):
        peer = self.client_class(None, "peer", "app", "other-chat", 7, None, "assistant", None)
        peer_started = asyncio.Event()
        peer_release = asyncio.Event()
        peer_completed = asyncio.Event()

        async def generate_peer(message):
            peer_started.set()
            await peer_release.wait()
            peer_completed.set()

        peer.handle_gpts_message = generate_peer
        await peer.handle_message({"inputs": {"input": "LONG"}})
        await peer_started.wait()
        await self.client.handle_message({"inputs": {"input": "LONG"}})
        await asyncio.wait_for(self.started.wait(), 1)
        await self.client.handle_message({"action": "stop"})
        peer_release.set()
        await self.drain()
        self.assertTrue(peer_completed.is_set())


async def export_trace():
    """Provide real production terminal frames to the frontend contract regression."""
    case = AssistantStopLifecycle()
    await case.asyncSetUp()
    try:
        await case.client.handle_message({"inputs": {"input": "LONG"}})
        await asyncio.wait_for(case.started.wait(), 1)
        before = list(case.frames)
        await case.client.handle_message({"action": "stop"})
        await case.drain()
        stopped = case.frames[len(before) :]
        offset = len(case.frames)
        await case.client.handle_message({"inputs": {"input": "NEXT"}})
        await case.drain()
        history = [
            {"id": row[0], "category": row[1], "message": row[2], "remark": row[3]}
            for row in case.db.execute("SELECT id,category,message,remark FROM history ORDER BY id")
        ]
        print(json.dumps({"before": before, "stopped": stopped, "next": case.frames[offset:], "history": history}))
    finally:
        await case.asyncTearDown()


if __name__ == "__main__":
    if "--trace" in sys.argv:
        asyncio.run(export_trace())
    else:
        unittest.main()
