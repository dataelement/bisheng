import pickle
from typing import Dict, Optional

import redis
from bisheng.settings import settings
from loguru import logger
from redis import ConnectionPool, RedisCluster
from redis.backoff import ExponentialBackoff
from redis.cluster import ClusterNode
from redis.retry import Retry
from redis.sentinel import Sentinel


class RedisClient:

    def __init__(self, url, max_connections=10):
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
                return
            hosts = [eval(x) for x in redis_conf.pop('sentinel_hosts')]
            password = redis_conf.pop('sentinel_password')
            master = redis_conf.pop('sentinel_master')
            sentinel = Sentinel(sentinels=hosts, socket_timeout=0.1, password=password)
            # 获取主节点的连接
            self.connection = sentinel.master_for(master, socket_timeout=0.1, **redis_conf)

        else:
            # 单机模式
            self.pool = ConnectionPool.from_url(url, max_connections=max_connections)
            self.connection = redis.StrictRedis(connection_pool=self.pool)

    def set(self, key, value, expiration=3600):
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
        finally:
            self.close()

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
        finally:
            self.close()

    def hsetkey(self, name, key, value, expiration=3600):
        try:
            self.cluster_nodes(key)
            r = self.connection.hset(name, key, value)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        finally:
            self.close()

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
        finally:
            self.close()

    def hget(self, name, key):
        try:
            self.cluster_nodes(name)
            return self.connection.hget(name, key)
        finally:
            self.close()

    def hgetall(self, name):
        try:
            self.cluster_nodes(name)
            return self.connection.hgetall(name)
        finally:
            self.close()

    def hdel(self, name, *keys):
        try:
            self.cluster_nodes(name)
            return self.connection.hdel(name, *keys)
        finally:
            self.close()

    def get(self, key):
        try:
            self.cluster_nodes(key)
            value = self.connection.get(key)
            return pickle.loads(value) if value else None
        finally:
            self.close()

    def incr(self, key, expiration=3600) -> int:
        try:
            self.cluster_nodes(key)
            value = self.connection.incr(key)
            if expiration:
                self.connection.expire(key, expiration)
            return value
        finally:
            self.close()

    def expire_key(self, key, expiration: int):
        try:
            self.cluster_nodes(key)
            self.connection.expire(key, expiration)
        finally:
            self.close()

    def delete(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.delete(key)
        finally:
            self.close()

    def rpush(self, key, value):
        try:
            self.cluster_nodes(key)
            return self.connection.rpush(key, value)
        finally:
            self.close()

    def publish(self, key, value):
        try:
            self.cluster_nodes(key)
            return self.connection.publish(key, value)
        finally:
            self.close()

    def exists(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.exists(key)
        finally:
            self.close()

    def close(self):
        self.connection.close()

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


# 示例用法
redis_client = RedisClient(settings.redis_url)
