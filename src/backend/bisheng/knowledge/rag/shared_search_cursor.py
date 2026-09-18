"""请求内搜索游标；不跨用户或跨请求复用索引快照。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


async def finish_inflight(future: asyncio.Future) -> Any:
    """取消等待不能中断同步 RPC；保留资源直到调用实际结束。"""
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if future.done() and not future.cancelled():
            future.exception()
        raise


class ElasticsearchSearchCursor:
    def __init__(
        self, client: Any, index: str, query: dict, batch_size: int, limit: int, convert: Callable, timeout: float = 30
    ) -> None:
        self.client, self.index, self.query = client, index, query
        self.batch_size, self.limit, self.convert = batch_size, limit, convert
        self.pit = None
        self.after = None
        self.count = 0
        self.closed = False
        self.timeout = timeout

    async def next_batch(self) -> list[Any]:
        if self.closed or self.count >= self.limit:
            return []
        if self.pit is None:

            async def open_pit():
                response = await self.client.open_point_in_time(
                    index=self.index, keep_alive="2m", request_timeout=self.timeout
                )
                self.pit = response["id"]

            await finish_inflight(asyncio.create_task(open_pit()))
        body = {
            "size": min(self.batch_size, self.limit - self.count),
            "pit": {"id": self.pit, "keep_alive": "2m"},
            "query": self.query,
            "sort": [{"_score": "desc"}, {"_shard_doc": "asc"}],
            "track_total_hits": False,
            "_source": [
                "metadata.canonical_document_id",
                "metadata.canonical_version_id",
                "metadata.content_generation",
                "metadata.membership_generation",
                "metadata.chunk_index",
                "text",
            ],
        }
        if self.after is not None:
            body["search_after"] = self.after

        async def search():
            response = await self.client.search(body=body, request_timeout=self.timeout)
            self.pit = response.get("pit_id", self.pit)
            return response

        response = await finish_inflight(asyncio.create_task(search()))
        rows = response.get("hits", {}).get("hits", [])
        if rows:
            after = rows[-1]["sort"]
            if after == self.after:
                raise RuntimeError("ES cursor did not advance")
            self.after = after
            self.count += len(rows)
        return self.convert(rows)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.pit is not None:
            await finish_inflight(
                asyncio.create_task(
                    self.client.close_point_in_time(body={"id": self.pit}, request_timeout=self.timeout)
                )
            )


class MilvusSearchCursor:
    def __init__(
        self,
        connection_args: dict,
        search_args: dict,
        semaphore: asyncio.Semaphore,
        timeout: float,
        client_factory: Callable | None = None,
    ) -> None:
        self.connection_args, self.search_args = dict(connection_args), dict(search_args)
        self.connection_args.pop("alias", None)
        self.connection_args["timeout"] = timeout
        self.semaphore, self.timeout = semaphore, timeout
        self.client_factory = client_factory
        self.client = self.iterator = self.executor = None
        self.closed = False
        self.acquired = False
        self.lock = asyncio.Lock()

    def _next(self) -> list[Any]:
        if self.client is None:
            from pymilvus import MilvusClient

            self.client = (self.client_factory or MilvusClient)(**self.connection_args)
        if self.iterator is None:
            self.client.load_collection(self.search_args.get("collection_name"), timeout=self.timeout)
            self.iterator = self.client.search_iterator(**self.search_args, timeout=self.timeout)
        return list(self.iterator.next())

    async def next_batch(self) -> list[Any]:
        async with self.lock:
            if self.closed:
                return []
            if not self.acquired:
                await self.semaphore.acquire()
                self.acquired = True
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qa-milvus-cursor")
            return await finish_inflight(asyncio.get_running_loop().run_in_executor(self.executor, self._next))

    def _close(self) -> None:
        try:
            if self.iterator is not None:
                self.iterator.close()
        finally:
            if self.client is not None:
                self.client.close()

    async def close(self) -> None:
        async with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                if self.executor is not None:
                    await finish_inflight(asyncio.get_running_loop().run_in_executor(self.executor, self._close))
            finally:
                if self.executor is not None:
                    self.executor.shutdown(wait=False)
                if self.acquired:
                    self.semaphore.release()
                    self.acquired = False


class MappedSearchCursor:
    def __init__(self, cursor: Any, convert: Callable, validate: Callable) -> None:
        self.cursor, self.convert, self.validate = cursor, convert, validate

    async def next_batch(self) -> list[Any]:
        await self.validate()
        return self.convert(await self.cursor.next_batch())

    async def close(self) -> None:
        await self.cursor.close()
