"""原生异步知识检索运行时。

只负责复用 PyMilvus 异步客户端、collection 加载和进程级并发保护;
文档映射、权限与降级策略仍由领域服务负责。
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pymilvus import AsyncMilvusClient
from pymilvus.milvus_client._utils import create_connection

from bisheng.core.config.settings import KnowledgeRetrievalRuntimeConf, Settings
from bisheng.core.context import BaseContextManager


def _normalize_connection_args(connection_args: dict[str, Any] | None) -> dict[str, Any]:
    args = dict(connection_args or {})
    host = args.pop("host", None)
    port = args.pop("port", None)
    if host and port and not args.get("uri"):
        args["uri"] = f"http://{host}:{port}"
    if args.get("alias"):
        args["alias"] = f"{args['alias']}-async-retrieval"
    return args


def _create_async_milvus_client(
    connection_args: dict[str, Any],
    timeout: float,
) -> AsyncMilvusClient:
    """创建不会同步探测服务端类型的异步客户端。

    pymilvus 2.5 的 ``AsyncMilvusClient.__init__`` 会同步调用一次
    ``utility.get_server_type``。这里复用其连接创建逻辑, 仅跳过未被异步客户端
    后续方法使用的 ``is_self_hosted`` 探测, 同时确保 gRPC async channel 在当前
    事件循环线程中创建。
    """
    kwargs = dict(connection_args)
    uri = kwargs.pop("uri", "http://localhost:19530")
    user = kwargs.pop("user", "")
    password = kwargs.pop("password", "")
    db_name = kwargs.pop("db_name", "")
    token = kwargs.pop("token", "")
    kwargs.pop("timeout", None)

    client = AsyncMilvusClient.__new__(AsyncMilvusClient)
    client._using = create_connection(
        uri,
        token,
        db_name,
        use_async=True,
        user=user,
        password=password,
        timeout=timeout,
        **kwargs,
    )
    client.is_self_hosted = True
    return client


class AsyncRetrievalRuntime:
    """每个进程复用一个 AsyncMilvusClient。"""

    def __init__(
        self,
        *,
        config: KnowledgeRetrievalRuntimeConf,
        connection_args: dict[str, Any] | None,
        milvus_client: Any | None = None,
    ) -> None:
        self.config = config
        self.connection_args = _normalize_connection_args(connection_args)
        self.milvus_client = milvus_client
        self._client_lock = asyncio.Lock()
        self._collection_locks: dict[str, asyncio.Lock] = {}
        self._loaded_collections: set[str] = set()
        self._embedding_semaphore = asyncio.Semaphore(config.max_embedding_concurrency)
        self._milvus_semaphore = asyncio.Semaphore(config.max_milvus_concurrency)

    async def embed_query(self, embeddings: Any, text: str) -> list[float]:
        """在进程级并发与单次超时约束下生成查询向量。"""
        async with self._embedding_semaphore:
            return await asyncio.wait_for(
                embeddings.aembed_query(text),
                timeout=self.config.embedding_timeout_seconds,
            )

    async def _get_milvus_client(self) -> Any:
        if self.milvus_client is not None:
            return self.milvus_client

        async with self._client_lock:
            if self.milvus_client is not None:
                return self.milvus_client

            client = _create_async_milvus_client(
                self.connection_args,
                timeout=self.config.milvus_timeout_seconds,
            )
            self.milvus_client = client
            return client

    async def _ensure_collection_loaded(self, collection_name: str) -> None:
        if collection_name in self._loaded_collections:
            return

        lock = self._collection_locks.setdefault(collection_name, asyncio.Lock())
        async with lock:
            if collection_name in self._loaded_collections:
                return
            client = await self._get_milvus_client()
            await asyncio.wait_for(
                client.load_collection(
                    collection_name,
                    timeout=self.config.milvus_timeout_seconds,
                ),
                timeout=self.config.milvus_timeout_seconds,
            )
            self._loaded_collections.add(collection_name)

    async def search_milvus(
        self,
        *,
        collection_name: str,
        vector: list[float],
        limit: int,
        expr: str | None = None,
        search_params: dict[str, Any] | None = None,
        output_fields: list[str] | None = None,
        anns_field: str = "vector",
    ) -> list[list[dict[str, Any]]]:
        async with self._milvus_semaphore:
            await self._ensure_collection_loaded(collection_name)
            client = await self._get_milvus_client()
            params = search_params or {
                "metric_type": "L2",
                "params": {"ef": max(int(limit) + 1, 64)},
            }
            return await asyncio.wait_for(
                client.search(
                    collection_name=collection_name,
                    data=[list(vector)],
                    filter=expr or "",
                    limit=int(limit),
                    output_fields=output_fields or ["*"],
                    search_params=params,
                    anns_field=anns_field,
                    timeout=self.config.milvus_timeout_seconds,
                ),
                timeout=self.config.milvus_timeout_seconds,
            )

    async def close(self) -> None:
        if self.milvus_client is None:
            return
        try:
            await self.milvus_client.close()
        finally:
            self.milvus_client = None
            self._loaded_collections.clear()


class AsyncRetrievalRuntimeManager(BaseContextManager[AsyncRetrievalRuntime]):
    name = "async_retrieval"

    def __init__(self, config: Settings, **kwargs: Any) -> None:
        super().__init__(self.name, **kwargs)
        self.settings = config

    async def _async_initialize(self) -> AsyncRetrievalRuntime:
        from bisheng.common.services.config_service import settings

        knowledge_config = await settings.async_get_knowledge()
        return AsyncRetrievalRuntime(
            config=knowledge_config.retrieval,
            connection_args=self.settings.get_vectors_conf().milvus.connection_args,
        )

    def _sync_initialize(self) -> AsyncRetrievalRuntime:
        raise RuntimeError("AsyncRetrievalRuntime 仅支持异步初始化")

    async def _async_cleanup(self) -> None:
        if self._instance is not None:
            await self._instance.close()

    def _sync_cleanup(self) -> None:
        logger.warning("AsyncRetrievalRuntime 不支持同步关闭")


async def get_async_retrieval_runtime() -> AsyncRetrievalRuntime:
    from bisheng.core.context.manager import app_context

    try:
        return await app_context.async_get_instance(AsyncRetrievalRuntimeManager.name)
    except KeyError:
        from bisheng.common.services.config_service import settings

        app_context.register_context(AsyncRetrievalRuntimeManager(settings))
        return await app_context.async_get_instance(AsyncRetrievalRuntimeManager.name)
