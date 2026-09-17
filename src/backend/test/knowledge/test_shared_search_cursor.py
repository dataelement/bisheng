import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_es_cursor_uses_latest_pit_and_last_raw_sort_and_closes():
    from bisheng.knowledge.rag.shared_search_cursor import ElasticsearchSearchCursor

    client = SimpleNamespace(
        open_point_in_time=AsyncMock(return_value={"id": "pit-1"}),
        search=AsyncMock(
            side_effect=[
                {"pit_id": "pit-2", "hits": {"hits": [{"sort": [5, 17], "_source": {}}]}},
                {"hits": {"hits": []}},
            ]
        ),
        close_point_in_time=AsyncMock(),
    )
    cursor = ElasticsearchSearchCursor(client, "index", {"match_all": {}}, 2, 8, lambda rows: rows)
    assert len(await cursor.next_batch()) == 1
    assert await cursor.next_batch() == []
    body = client.search.await_args_list[1].kwargs["body"]
    assert body["search_after"] == [5, 17]
    assert body["pit"]["id"] == "pit-2"
    await cursor.close()
    client.close_point_in_time.assert_awaited_once_with(body={"id": "pit-2"}, request_timeout=30)


async def test_sync_iterator_cancel_waits_for_rpc_before_closing():
    from bisheng.knowledge.rag.shared_search_cursor import MilvusSearchCursor
    import threading

    entered, release = threading.Event(), threading.Event()
    events = []

    class Iterator:
        def next(self):
            entered.set()
            release.wait(2)
            events.append("rpc_done")
            return []

        def close(self):
            events.append("iterator_close")

    class Client:
        def load_collection(self, *a, **kw):
            pass

        def search_iterator(self, **kw):
            return Iterator()

        def close(self):
            events.append("client_close")

    semaphore = asyncio.Semaphore(1)
    cursor = MilvusSearchCursor({}, {}, semaphore, 1, client_factory=lambda **kw: Client())
    task = asyncio.create_task(cursor.next_batch())
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    assert semaphore.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await cursor.close()
    assert events == ["rpc_done", "iterator_close", "client_close"]
    assert not semaphore.locked()
