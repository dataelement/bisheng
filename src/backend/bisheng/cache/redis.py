import redis
from bisheng.settings import settings
from redis import ConnectionPool
from redis.sentinel import Sentinel

# Sentinel节点列表，每个节点是(host, port)的元组
sentinel_hosts = [
    ('sentinel1.example.com', 26379),
    ('sentinel2.example.com', 26379),
    ('sentinel3.example.com', 26379)
]

# 创建Sentinel实例
sentinel = Sentinel(sentinel_hosts, socket_timeout=0.1)


class RedisClient:

    def __init__(self, url, max_connections=10):

        # sentinel = Sentinel(sentinel_hosts=settings.redis_url, socket_timeout=0.1, password=)
        # # 获取主节点的连接
        # master = sentinel.master_for(settings, socket_timeout=0.1, db=1)

        # # 获取从节点的连接（其中一个）
        # slave = sentinel.slave_for('mymaster', socket_timeout=0.1, db=1)
        self.pool = ConnectionPool.from_url(url, max_connections=max_connections)
        self.connection = redis.StrictRedis(connection_pool=self.pool)

    def set(self, key, value, expiration=None):
        try:
            return self.connection.set(key, value, ex=expiration)
        finally:
            self.close()

    def hsetkey(self, name, key, value, expiration=None):
        try:
            r = self.connection.hset(name, key, value)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        finally:
            self.close()

    def hset(self, name, map: dict, expiration=None):
        try:
            r = self.connection.hset(name, mapping=map)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        finally:
            self.close()

    def hget(self, name, key):
        try:
            return self.connection.hget(name, key)
        finally:
            self.close()

    def get(self, key):
        try:
            return self.connection.get(key)
        finally:
            self.close()

    def delete(self, key):
        try:
            return self.connection.delete(key)
        finally:
            self.close()

    def exists(self, key):
        try:
            return self.connection.exists(key)
        finally:
            self.close()

    def close(self):
        self.connection.close()


# 示例用法
redis_client = RedisClient(settings.redis_url)
