import pickle
import typing
from typing import Dict, Optional, Any, Coroutine

import redis
from redis.asyncio.client import Pipeline

from bisheng.settings import settings
from loguru import logger
from redis import ConnectionPool, RedisCluster
from redis.backoff import ExponentialBackoff
from redis.cluster import ClusterNode
from redis.retry import Retry
from redis.sentinel import Sentinel
from redis.asyncio.sentinel import Sentinel as AsyncSentinel
from redis.asyncio.cluster import RedisCluster as AsyncRedisCluster
from redis.asyncio import Redis as AsyncRedis


class RedisClient:

    def __init__(self, url, max_connections=100):
        # # 哨兵模式
        if isinstance(settings.redis_url, Dict):
            redis_conf = dict(settings.redis_url)
            mode = redis_conf.pop('mode', 'sentinel')
            if mode == 'cluster':
                # 集群模式
                cluster_url = ''
                if 'startup_nodes' in redis_conf:
                    first_node = redis_conf['startup_nodes'][0]
                    cluster_url = f'redis://{first_node["host"]}:{first_node["port"]}'
                    redis_conf['startup_nodes'] = [
                        ClusterNode(node.get('host'), node.get('port'))
                        for node in redis_conf['startup_nodes']
                    ]
                self.connection = RedisCluster.from_url(cluster_url, **redis_conf,
                                                        retry=Retry(ExponentialBackoff(), 6),
                                                        cluster_error_retry_attempts=1)
                self.async_connection: typing.Union[AsyncRedisCluster, AsyncRedis] = AsyncRedisCluster.from_url(
                    cluster_url, **redis_conf, retry=Retry(ExponentialBackoff(), 6), cluster_error_retry_attempts=1)
                return
            hosts = [eval(x) for x in redis_conf.pop('sentinel_hosts')]
            password = redis_conf.pop('sentinel_password')
            master = redis_conf.pop('sentinel_master')
            sentinel = Sentinel(sentinels=hosts, socket_timeout=0.1, sentinel_kwargs={'password': password})
            async_sentinel = AsyncSentinel(sentinels=hosts, socket_timeout=0.1, sentinel_kwargs={'password': password})
            # 获取主节点的连接
            self.connection = sentinel.master_for(master, socket_timeout=0.1, **redis_conf)
            self.async_connection: AsyncRedis = async_sentinel.master_for(master, socket_timeout=0.1, **redis_conf)

        else:
            # 单机模式
            self.pool = ConnectionPool.from_url(url, max_connections=max_connections)
            self.async_pool = redis.asyncio.ConnectionPool.from_url(url, max_connections=max_connections)
            self.connection = redis.StrictRedis(connection_pool=self.pool)
            self.async_connection: AsyncRedis = redis.asyncio.Redis.from_pool(self.async_pool)

    def set(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                self.cluster_nodes(key)
                if expiration:
                    result = self.connection.setex(key, expiration, pickled)
                else:
                    result = self.connection.set(key, pickled)
                if not result:
                    raise ValueError('RedisCache could not set the value.')
            else:
                logger.error('pickle error, value={}', value)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def aset(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                # await self.acluster_nodes(key)
                if expiration:
                    result = await self.async_connection.setex(name=key, value=pickled, time=expiration)
                else:
                    result = await self.async_connection.set(key, pickled)
                if not result:
                    raise ValueError('RedisCache could not set the value.')
            else:
                logger.error('pickle error, value={}', value)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    def setNx(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                self.cluster_nodes(key)
                result = self.connection.setnx(key, pickled)
                self.connection.expire(key, expiration)
                if not result:
                    return False
            return True
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def asetNx(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                await self.acluster_nodes(key)
                result = await self.async_connection.setnx(key, pickled)
                await self.async_connection.expire(key, expiration)
                if not result:
                    return False
            return True
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    def setex(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                self.cluster_nodes(key)
                result = self.connection.setex(key, expiration, pickled)
                if not result:
                    raise ValueError('RedisCache could not set the value.')
            else:
                logger.error('pickle error, value={}', value)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def asetex(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                await self.acluster_nodes(key)
                result = await self.async_connection.setex(key, expiration, pickled)
                if not result:
                    raise ValueError('RedisCache could not set the value.')
            else:
                logger.error('pickle error, value={}', value)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    def mset(self, mapping: Dict[str, typing.Any], expiration: int = None) -> bool | None:
        """批量设置"""
        try:
            if not mapping:
                return True

            serialized_mapping = {k: pickle.dumps(v) for k, v in mapping.items() if v is not None}
            result = self.connection.mset(serialized_mapping)

            if expiration:
                # 使用pipeline批量设置过期时间
                pipe = self.connection.pipeline()
                for key in mapping.keys():
                    pipe.expire(key, expiration)
                pipe.execute()

            return bool(result)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def amset(self, mapping: Dict[str, typing.Any], expiration: int = None) -> bool | None:
        """异步批量设置"""
        try:
            if not mapping:
                return True

            serialized_mapping = {k: pickle.dumps(v) for k, v in mapping.items() if v is not None}
            result = await self.async_connection.mset(serialized_mapping)

            if expiration:
                # 使用pipeline批量设置过期时间
                pipe: Pipeline = self.async_connection.pipeline()
                for key in mapping.keys():
                    await pipe.expire(key, expiration)
                await pipe.execute()

            return bool(result)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    def mget(self, keys: typing.List[str]) -> typing.List[typing.Any] | None:
        """批量获取"""
        try:
            if not keys:
                return []
            values = self.connection.mget(keys)

            return [pickle.loads(v) for v in values if v is not None]
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def amget(self, keys: typing.List[str]) -> typing.List[typing.Any] | None:
        """异步批量获取"""
        try:
            if not keys:
                return []
            values = await self.async_connection.mget(keys)
            return [pickle.loads(v) for v in values if v is not None]
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc

    async def akeys(self, pattern: str) -> typing.List[str]:
        """异步获取匹配模式的所有键"""
        try:
            await self.acluster_nodes(pattern)
            keys = await self.async_connection.keys(pattern)
            return [key.decode('utf-8') for key in keys]
        except Exception as e:
            raise e

    def hsetkey(self, name, key, value, expiration=3600):
        try:
            self.cluster_nodes(key)
            r = self.connection.hset(name, key, value)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        except Exception as e:
            raise e

    async def ahsetkey(self, name, key, value, expiration=3600):
        try:
            await self.acluster_nodes(key)
            r = await self.async_connection.hset(name, key, value)
            if expiration:
                await self.async_connection.expire(name, expiration)
            return r
        except Exception as e:
            raise e

    def hset(self, name,
             key: Optional[str] = None,
             value: Optional[str] = None,
             mapping: Optional[dict] = None,
             items: Optional[list] = None,
             expiration: int = 3600):
        try:
            self.cluster_nodes(name)
            r = self.connection.hset(name, key, value, mapping, items)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        except Exception as e:
            raise e

    async def ahset(self, name,
                    key: Optional[str] = None,
                    value: Optional[str] = None,
                    mapping: Optional[dict] = None,
                    items: Optional[list] = None,
                    expiration: int = 3600):
        try:
            await self.acluster_nodes(name)
            r = await self.async_connection.hset(name, key, value, mapping, items)
            if expiration:
                await self.async_connection.expire(name, expiration)
            return r
        except Exception as e:
            raise e

    def hget(self, name, key):
        try:
            self.cluster_nodes(name)
            return self.connection.hget(name, key)
        except Exception as e:
            raise e

    async def ahget(self, name, key):
        try:
            await self.acluster_nodes(name)
            return await self.async_connection.hget(name, key)
        except Exception as e:
            raise e

    def hgetall(self, name):
        try:
            self.cluster_nodes(name)
            return self.connection.hgetall(name)
        except Exception as e:
            raise e

    async def ahgetall(self, name):
        try:
            await self.acluster_nodes(name)
            return await self.async_connection.hgetall(name)
        except Exception as e:
            raise e

    def hdel(self, name, *keys):
        try:
            self.cluster_nodes(name)
            return self.connection.hdel(name, *keys)
        except Exception as e:
            raise e

    async def ahdel(self, name, *keys):
        try:
            await self.acluster_nodes(name)
            return await self.async_connection.hdel(name, *keys)
        except Exception as e:
            raise e

    def get(self, key):
        try:
            self.cluster_nodes(key)
            value = self.connection.get(key)
            return pickle.loads(value) if value else None
        except Exception as e:
            raise e

    async def aget(self, key):
        try:
            await self.acluster_nodes(key)
            value = await self.async_connection.get(key)
            return pickle.loads(value) if value else None
        except Exception as e:
            # Handle the case where the value is None or not picklable
            raise e

    def incr(self, key, expiration=3600) -> int:
        try:
            self.cluster_nodes(key)
            value = self.connection.incr(key)
            if expiration:
                self.connection.expire(key, expiration)
            return value
        except Exception as e:
            raise e

    async def aincr(self, key, expiration=3600) -> int:
        try:
            await self.acluster_nodes(key)
            value = await self.async_connection.incr(key)
            if expiration:
                await self.async_connection.expire(key, expiration)
            return value
        except Exception as e:
            raise e

    def expire_key(self, key, expiration: int):
        try:
            self.cluster_nodes(key)
            self.connection.expire(key, expiration)
        except Exception as e:
            raise e

    async def aexpire_key(self, key, expiration: int):
        try:
            await self.acluster_nodes(key)
            await self.async_connection.expire(key, expiration)
        except Exception as e:
            raise e

    def delete(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.delete(key)
        except Exception as e:
            raise e

    async def adelete(self, key):
        try:
            await self.acluster_nodes(key)
            return await self.async_connection.delete(key)
        except Exception as e:
            raise e

    async def alpush(self, key, value, expiration=3600):
        try:
            await self.acluster_nodes(key)
            ret = await self.async_connection.lpush(key, value)
            if expiration:
                await self.aexpire_key(key, expiration)
            return ret
        except Exception as e:
            raise e

    async def ablpop(self, key, timeout=0):
        try:
            await self.acluster_nodes(key)
            value = await self.async_connection.blpop(key, timeout)
            return pickle.loads(value[1]) if value and value[1] else None
        except Exception as e:
            raise e

    async def alrange(self, key, start=0, end=-1):
        try:
            await self.acluster_nodes(key)
            values = await self.async_connection.lrange(key, start, end)
            return [pickle.loads(v) for v in values if v is not None]
        except Exception as e:
            raise e

    async def alrem(self, key, value):
        try:
            await self.acluster_nodes(key)
            value = pickle.dumps(value) if not isinstance(value, bytes) else value
            return await self.async_connection.lrem(key, 0, value)
        except Exception as e:
            raise e

    def rpush(self, key, value, expiration=3600):
        try:
            self.cluster_nodes(key)
            ret = self.connection.rpush(key, value)
            if expiration:
                self.expire_key(key, expiration)
            return ret
        except Exception as e:
            raise e

    async def arpush(self, key, value, expiration=3600):
        try:
            await self.acluster_nodes(key)
            value = pickle.dumps(value) if not isinstance(value, bytes) else value
            ret = await self.async_connection.rpush(key, value)
            if expiration:
                await self.aexpire_key(key, expiration)
            return ret
        except Exception as e:
            raise e

    def lpop(self, key, count: int = None):
        try:
            self.cluster_nodes(key)
            return self.connection.lpop(key, count)
        except Exception as e:
            raise e

    async def alpop(self, key, count: int = None):
        try:
            await self.acluster_nodes(key)
            return await self.async_connection.lpop(key, count)
        except Exception as e:
            raise e

    def publish(self, key, value):
        try:
            self.cluster_nodes(key)
            return self.connection.publish(key, value)
        except Exception as e:
            raise e

    async def apublish(self, key, value):
        try:
            await self.acluster_nodes(key)
            return await self.async_connection.publish(key, value)
        except Exception as e:
            raise e

    def exists(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.exists(key)
        except Exception as e:
            raise e

    async def aexists(self, key):
        try:
            await self.acluster_nodes(key)
            return await self.async_connection.exists(key)
        except Exception as e:
            raise e

    def close(self):
        self.connection.close()

    async def aclose(self):
        """Asynchronous close method for the Redis connection."""
        if hasattr(self, 'async_connection') and self.async_connection:
            await self.async_connection.close()
        else:
            logger.warning("No async connection to close.")

    # ==================== Pipeline支持 ====================

    def pipeline(self, transaction: bool = True) -> redis.client.Pipeline:
        """获取pipeline对象"""
        return self.connection.pipeline(transaction=transaction)

    def async_pipeline(self, transaction: bool = True) -> Pipeline:
        """获取异步pipeline对象"""
        return self.async_connection.pipeline(transaction=transaction)

    async def allen(self, key: str) -> int:
        """Check if the key is in the cache using the 'in' operator."""
        await self.acluster_nodes(key)
        return await self.async_connection.llen(key)

    def __contains__(self, key):
        """Check if the key is in the cache."""
        self.cluster_nodes(key)
        return False if key is None else self.connection.exists(key)

    def __getitem__(self, key):
        """Retrieve an item from the cache using the square bracket notation."""
        self.cluster_nodes(key)
        return self.connection.get(key)

    def __setitem__(self, key, value):
        """Add an item to the cache using the square bracket notation."""
        self.cluster_nodes(key)
        self.connection.set(key, value)

    def __delitem__(self, key):
        """Remove an item from the cache using the square bracket notation."""
        self.cluster_nodes(key)
        self.connection.delete(key)

    def cluster_nodes(self, key):
        if isinstance(self.connection,
                      RedisCluster) and self.connection.get_default_node() is None:
            target = self.connection.get_node_from_key(key)
            self.connection.set_default_node(target)

    async def acluster_nodes(self, key):
        if isinstance(self.async_connection,
                      AsyncRedisCluster) and self.async_connection.get_default_node() is None:
            target = self.async_connection.get_node_from_key(key)
            self.async_connection.set_default_node(target)


# 示例用法
redis_client = RedisClient(settings.redis_url)
