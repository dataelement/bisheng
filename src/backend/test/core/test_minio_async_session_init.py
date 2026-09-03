"""MinIO async session must initialize outside a running event loop (Celery threads)."""

import asyncio
import threading

import pytest

from bisheng.core.storage.minio.minio_storage import _build_async_minio_session
from bisheng.utils.async_utils import set_preferred_bridge_loop


@pytest.fixture
def bridge_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="test-bridge-loop", daemon=True)
    thread.start()
    set_preferred_bridge_loop(loop)
    try:
        yield loop
    finally:
        set_preferred_bridge_loop(None)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


def test_build_async_minio_session_without_running_loop(bridge_loop):
    """Sync Celery threads have no running loop but must still build aiohttp clients."""
    err: list[BaseException] = []

    def _target() -> None:
        try:
            session = _build_async_minio_session(timeout_seconds=30, cert_check=False)
            assert session is not None
        except BaseException as exc:
            err.append(exc)

    t = threading.Thread(target=_target)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive()
    assert err == [], err
