"""F017 LLMUsageCallbackHandler must not poison the shared async DB pool.

Regression for the production incident where the workflow invokes the LLM
synchronously, LangChain runs the async ``on_llm_end`` callback on a throwaway
``asyncio.Runner`` loop, and its ``llm_call_log`` / ``llm_token_log`` writes —
going through the process-global async DB engine — left pooled connections bound
to that dead loop, later surfacing as "Future attached to a different loop" /
"Event loop is closed" for the next async DB caller.

The fix hops the writes onto the persistent worker bridge loop.
"""

import asyncio
import threading
from unittest.mock import patch

import bisheng.workflow.callback.llm_usage_callback as cb_mod
from bisheng.utils.async_utils import set_preferred_bridge_loop
from bisheng.workflow.callback.llm_usage_callback import LLMUsageCallbackHandler


def _start_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def _handler() -> LLMUsageCallbackHandler:
    return LLMUsageCallbackHandler(user_id=1, model_id=2, server_id=3, endpoint="http://llm")


def test_on_llm_end_writes_run_on_bridge_loop():
    """Fired on a transient loop, the DB writes must execute on the bridge loop."""
    pref = _start_loop()
    transient = _start_loop()
    set_preferred_bridge_loop(pref)
    recorded: dict = {}

    async def _fake_log_success(**kwargs):
        recorded["loop_id"] = id(asyncio.get_running_loop())

    try:
        with (
            patch.object(cb_mod, "_extract_token_usage", return_value=None),
            patch.object(cb_mod.ModelCallLogger, "log_success", side_effect=_fake_log_success),
        ):
            handler = _handler()
            asyncio.run_coroutine_threadsafe(handler.on_llm_end(response=object()), transient).result(timeout=3)
        # Ran on the bridge loop, NOT the throwaway transient loop.
        assert recorded["loop_id"] == id(pref)
        assert recorded["loop_id"] != id(transient)
    finally:
        set_preferred_bridge_loop(None)
        pref.call_soon_threadsafe(pref.stop)
        transient.call_soon_threadsafe(transient.stop)


def test_on_llm_end_runs_inline_without_bridge_loop():
    """No bridge loop registered (FastAPI async run): writes run on the current loop."""
    set_preferred_bridge_loop(None)
    current = _start_loop()
    recorded: dict = {}

    async def _fake_log_success(**kwargs):
        recorded["loop_id"] = id(asyncio.get_running_loop())

    try:
        with (
            patch.object(cb_mod, "_extract_token_usage", return_value=None),
            patch.object(cb_mod.ModelCallLogger, "log_success", side_effect=_fake_log_success),
        ):
            handler = _handler()
            asyncio.run_coroutine_threadsafe(handler.on_llm_end(response=object()), current).result(timeout=3)
        assert recorded["loop_id"] == id(current)
    finally:
        current.call_soon_threadsafe(current.stop)
