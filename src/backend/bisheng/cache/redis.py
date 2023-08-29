import redis
from bisheng.settings import settings
from redis import ConnectionPool


class RedisClient:
    def __init__(self, host='localhost', port=6379, db=0, max_connections=10):
        self.pool = ConnectionPool(host=host, port=port, db=db, max_connections=max_connections)
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

    def hset(self, name, map:dict, expiration=None):
        try:
            r=self.connection.hset(name, mapping=map)
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
host, port = settings.redis_url.split(':')
redis_client = RedisClient(host, port)
