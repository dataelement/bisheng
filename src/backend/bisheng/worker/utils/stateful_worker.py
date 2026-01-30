import asyncio
import time
from typing import List, Dict

from httpcore._synchronization import ThreadLock
from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.utils.consisten_hash import ConsistentHash
from bisheng.worker.main import WORKER_ALIVE_KEY


class StatefulWorker:
    def __init__(self,
                 queue_prefix: str = "workflow_celery",
                 bound_nodes_prefix: str = "workflow_bound_nodes:",
                 **kwargs):
        self.queue_prefix = queue_prefix
        self.bound_nodes_prefix = bound_nodes_prefix

        self.alive_times = kwargs.get("alive_time", 20)  # how much seconds to consider a worker alive
        self.consistent_hash = ConsistentHash(virtual_replicas=kwargs.get("virtual_replicas", 10))
        self.sync_timestamp = 0
        self.sync_timestamp_sleep = 5  # seconds
        self.thread_lock = ThreadLock()
        self.async_lock = asyncio.Lock()

    def _base_update_alive_nodes(self, alive_nodes: List[str]):
        consistent_nodes = self.consistent_hash.get_all_nodes()
        add_nodes = set(alive_nodes) - set(consistent_nodes)
        remove_nodes = set(consistent_nodes) - set(alive_nodes)
        for node in add_nodes:
            self.consistent_hash.add_node(node)
        for node in remove_nodes:
            self.consistent_hash.remove_node(node)
        logger.debug(f'Worker alive nodes updated: {self.consistent_hash.get_all_nodes()}')

    async def update_alive_nodes(self):
        async with self.async_lock:
            current_time = time.time()
            if current_time - self.sync_timestamp < self.alive_times:
                return
            alive_nodes = await self.get_all_alive_queues()
            self._base_update_alive_nodes(alive_nodes)

    def update_alive_nodes_sync(self):
        with self.thread_lock:
            current_time = time.time()
            if current_time - self.sync_timestamp < self.alive_times:
                return
            alive_nodes = self.get_all_alive_queues_sync()
            self._base_update_alive_nodes(alive_nodes)

    def _base_get_all_alive_queues(self, all_queues: Dict[bytes, bytes]) -> (List[str], List[str]):
        if not all_queues:
            return [], []
        current_timestamp = int(time.time())
        alive_queues = []
        need_remove_queues = []
        for queue_name, queue_timestamp in all_queues.items():
            queue_name = queue_name.decode() if isinstance(queue_name, bytes) else queue_name
            queue_timestamp = queue_timestamp.decode() if isinstance(queue_timestamp, bytes) else queue_timestamp
            if not queue_name.startswith(self.queue_prefix):
                continue
            if current_timestamp - int(queue_timestamp) < self.alive_times:
                alive_queues.append(queue_name)
            else:
                need_remove_queues.append(queue_name)
        return alive_queues, need_remove_queues

    async def get_all_alive_queues(self) -> List[str]:
        redis_client = await get_redis_client()
        all_queues = await redis_client.ahgetall(WORKER_ALIVE_KEY)
        alive_nodes, remove_nodes = self._base_get_all_alive_queues(all_queues)
        if remove_nodes:
            await redis_client.ahdel(WORKER_ALIVE_KEY, *remove_nodes)
        return alive_nodes

    def get_all_alive_queues_sync(self):
        redis_client = get_redis_client_sync()
        all_queues = redis_client.hgetall(WORKER_ALIVE_KEY)
        alive_nodes, remove_nodes = self._base_get_all_alive_queues(all_queues)
        if remove_nodes:
            redis_client.hdel(WORKER_ALIVE_KEY, *remove_nodes)
        return alive_nodes

    def is_node_alive(self, node: str) -> bool:
        all_nodes = self.consistent_hash.get_all_nodes()
        return node in all_nodes

    async def _find_bound_node(self, hash_key: str) -> str | None:
        redis_client = await get_redis_client()
        return await redis_client.aget(f"{self.bound_nodes_prefix}{hash_key}")

    async def _save_bound_node(self, hash_key: str, node: str) -> None:
        redis_client = await get_redis_client()
        return await redis_client.aset(f"{self.bound_nodes_prefix}{hash_key}", node)

    def _find_bound_node_sync(self, hash_key: str) -> str | None:
        redis_client = get_redis_client_sync()
        return redis_client.get(f"{self.bound_nodes_prefix}{hash_key}")

    def _save_bound_node_sync(self, hash_key: str, node: str) -> None:
        redis_client = get_redis_client_sync()
        return redis_client.set(f"{self.bound_nodes_prefix}{hash_key}", node)

    async def find_task_node(self, hash_key: str) -> str | None:
        await self.update_alive_nodes()

        # Get the node bound to the key
        bound_node = await self._find_bound_node(hash_key)
        if bound_node and self.is_node_alive(bound_node):
            # judge if the bound node is alive
            logger.debug(f"Assigned node {bound_node} for key {hash_key}")
            return bound_node

        # reassign the node
        assigned_node = self.consistent_hash.find_node(hash_key)
        if assigned_node:
            await self._save_bound_node(hash_key, assigned_node)
        logger.debug(f"Assigned node {assigned_node} for key {hash_key}")
        return assigned_node

    def find_task_node_sync(self, hash_key: str) -> str | None:
        self.update_alive_nodes()

        # Get the node bound to the key
        bound_node = self._find_bound_node_sync(hash_key)
        if bound_node and self.is_node_alive(bound_node):
            # judge if the bound node is alive
            logger.debug(f"Assigned node {bound_node} for key {hash_key}")
            return bound_node

        # reassign the node
        assigned_node = self.consistent_hash.find_node(hash_key)
        if assigned_node:
            self._save_bound_node_sync(hash_key, assigned_node)
        logger.debug(f"Assigned node {assigned_node} for key {hash_key}")
        return assigned_node
