"""覆盖 AC: AC-26、AC-28、AC-29、AC-46、AC-47、AC-51. Bounded object reads."""

from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.repositories.runtime_object_store import BUCKET, RuntimeObjectStore
from test.app_runtime.test_runtime_material_transfers import (
    DATA,
    call,
    exchange,
)
from test.app_runtime.test_runtime_material_transfers import (
    control as control,
)
from test.app_runtime.test_runtime_material_transfers import (
    materials as materials,
)
from test.app_runtime.test_runtime_material_transfers import (
    repo as repo,
)
from test.app_runtime.test_runtime_material_transfers import (
    transfers as transfers,
)


@pytest.mark.parametrize("abort", [False, True])
async def test_object_store_reads_exact_range_and_releases_connection(abort):
    calls = []

    class Response:
        closed = released = False

        def read(self, length):
            calls.append(("read", length))
            return b"678" if len(calls) == 2 else b""

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True

    response = Response()

    def get_object(bucket, key, **kwargs):
        calls.append((bucket, key, kwargs))
        return response

    objects = RuntimeObjectStore()

    async def storage():
        return SimpleNamespace(minio_client_sync=SimpleNamespace(get_object=get_object))

    objects._storage = storage
    stream = objects.iter_range("large/key", offset=6, length=3)
    try:
        assert await anext(stream) == b"678"
        if not abort:
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
    finally:
        await stream.aclose()
    assert calls[0] == (BUCKET, "large/key", {"offset": 6, "length": 3})
    assert response.closed and response.released


async def test_transfer_uses_range_without_reading_preceding_bytes(transfers):
    t = transfers
    observed = []

    async def forbidden(_):
        raise AssertionError("full object read is forbidden for a range")
        yield b""

    async def ranged(key, *, offset, length):
        observed.append((key, offset, length))
        yield DATA[offset : offset + length]

    t.objects.iter_content = forbidden
    t.objects.iter_range = ranged
    grant, session = await exchange(t)
    status, headers, body = await call(t, grant, session, sub="/content", query="?length=2&offset=7")
    assert (status, body, headers["Content-Length"]) == (206, b"78", "2")
    assert len(observed) == 1 and observed[0][1:] == (7, 2)
