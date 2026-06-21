import asyncio
from concurrent.futures import ThreadPoolExecutor

from bisheng.core.vectorstore import _ensure_current_thread_event_loop


def test_ensure_current_thread_event_loop_creates_loop_in_worker_thread():
    def run_without_loop() -> bool:
        asyncio.set_event_loop(None)

        try:
            _ensure_current_thread_event_loop()
            loop = asyncio.get_event_loop()
            return not loop.is_closed()
        finally:
            loop = asyncio.get_event_loop()
            loop.close()
            asyncio.set_event_loop(None)

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_without_loop).result(timeout=5)


def test_ensure_current_thread_event_loop_replaces_closed_loop():
    def run_with_closed_loop() -> bool:
        closed_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(closed_loop)
        closed_loop.close()

        try:
            _ensure_current_thread_event_loop()
            loop = asyncio.get_event_loop()
            return loop is not closed_loop and not loop.is_closed()
        finally:
            loop = asyncio.get_event_loop()
            loop.close()
            asyncio.set_event_loop(None)

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_with_closed_loop).result(timeout=5)
