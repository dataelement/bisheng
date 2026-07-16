import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from langchain_milvus import Milvus as LangchainMilvus

from bisheng.core.vectorstore import Milvus


def test_milvus_initialization_is_serialized(monkeypatch):
    workers_ready = threading.Barrier(2)
    state_lock = threading.Lock()
    active_initializers = 0
    max_active_initializers = 0

    def fake_init(_self, *_args, **_kwargs):
        nonlocal active_initializers, max_active_initializers

        with state_lock:
            active_initializers += 1
            max_active_initializers = max(
                max_active_initializers,
                active_initializers,
            )

        time.sleep(0.05)

        with state_lock:
            active_initializers -= 1

    def initialize_milvus():
        workers_ready.wait(timeout=5)
        try:
            Milvus()
        finally:
            loop = asyncio.get_event_loop()
            loop.close()
            asyncio.set_event_loop(None)

    monkeypatch.setattr(LangchainMilvus, "__init__", fake_init)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(initialize_milvus) for _ in range(2)]
        for future in futures:
            future.result(timeout=5)

    assert max_active_initializers == 1
