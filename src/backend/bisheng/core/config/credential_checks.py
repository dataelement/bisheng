"""Fresh, read-only SDK connections; never initialize business infrastructure."""

from __future__ import annotations

import ast

from bisheng.core.config.secret_crypto import CredentialConfigurationError


class CredentialConnectionError(CredentialConfigurationError):
    """A redacted online validation failure."""


def _mysql(settings):
    from sqlalchemy import create_engine, text

    options = settings.database_pool.as_engine_kwargs()
    if str(settings.database_url).startswith("mysql"):
        options.setdefault("connect_args", {}).setdefault("connect_timeout", 5)
    engine = create_engine(settings.database_url, **options)
    try:
        with engine.connect() as connection:
            statement = "SELECT 1 FROM DUAL" if str(settings.database_url).startswith("dm+") else "SELECT 1"
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _redis_value(value):
    from redis import Redis

    sentinel = None
    if isinstance(value, str):
        client = Redis.from_url(value, socket_timeout=5, socket_connect_timeout=5)
    elif isinstance(value, dict) and value.get("mode") == "single":
        options = dict(value)
        options.pop("mode")
        url = options.pop("url")
        options.setdefault("socket_timeout", 5)
        options.setdefault("socket_connect_timeout", 5)
        client = Redis.from_url(url, **options)
    elif isinstance(value, dict) and value.get("mode", "sentinel") == "sentinel":
        from redis.sentinel import Sentinel

        if value.get("sentinel_username"):
            raise CredentialConnectionError("redis: Sentinel username adapter requires separate validation")
        options = dict(value)
        options.pop("mode", None)
        hosts = [ast.literal_eval(x) if isinstance(x, str) else x for x in options.pop("sentinel_hosts")]
        master = options.pop("sentinel_master")
        sentinel_password = options.pop("sentinel_password", None)
        options.setdefault("socket_timeout", 5)
        options.setdefault("socket_connect_timeout", 5)
        sentinel = Sentinel(hosts, socket_timeout=5, sentinel_kwargs={"password": sentinel_password})
        client = sentinel.master_for(master, **options)
    else:
        raise CredentialConnectionError("redis: unsupported inspection mode")
    try:
        if client.ping() is not True:
            raise CredentialConnectionError("redis: authenticated PING failed")
    finally:
        client.close()
        if sentinel is not None:
            for peer in sentinel.sentinels:
                peer.close()


def _redis(settings):
    _redis_value(settings.redis_url)
    if settings.celery_redis_url:
        _redis_value(settings.celery_redis_url)


def _minio(settings):
    import urllib3
    from minio import Minio

    conf = settings.object_storage.minio
    pool = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=5, read=5),
        cert_reqs="CERT_REQUIRED" if conf.cert_check else "CERT_NONE",
        retries=False,
    )
    try:
        client = Minio(
            conf.endpoint,
            access_key=conf.access_key,
            secret_key=conf.secret_key,
            secure=conf.secure,
            cert_check=conf.cert_check,
            http_client=pool,
        )
        client.list_buckets()
    finally:
        pool.clear()


def _es(conf):
    from elasticsearch import Elasticsearch

    options = dict(conf.ssl_verify)
    options.setdefault("request_timeout", 5)
    options.setdefault("max_retries", 0)
    client = Elasticsearch(hosts=conf.elasticsearch_url, **options)
    try:
        client.security.authenticate()
    finally:
        client.close()


def _milvus(settings):
    from pymilvus import MilvusClient

    args = dict(settings.vector_stores.milvus.connection_args or {})
    host = args.pop("host", "milvus")
    port = args.pop("port", "19530")
    args.setdefault("uri", f"{'https' if args.get('secure') else 'http'}://{host}:{port}")
    args.setdefault("timeout", 5)
    client = MilvusClient(**args)
    try:
        client.list_collections(timeout=5)
    finally:
        client.close()


_PROBES = {
    "mysql": _mysql,
    "redis": _redis,
    "minio": _minio,
    "elasticsearch": lambda settings: _es(settings.vector_stores.elasticsearch),
    "milvus": _milvus,
    "telemetry_elasticsearch": lambda settings: _es(settings.telemetry_elasticsearch),
}


def check_online(settings, component=None):
    selected = [component] if component else ["mysql", "redis", "minio", "elasticsearch", "milvus"]
    if not component and settings.telemetry_elasticsearch.elasticsearch_url:
        selected.append("telemetry_elasticsearch")
    for name in selected:
        if name not in _PROBES:
            raise CredentialConnectionError("check: unknown component")
        try:
            _PROBES[name](settings)
        except Exception:
            # Driver errors can include full URLs or parameters. Never forward
            # their text/traceback into an operator report containing secrets.
            raise CredentialConnectionError(f"{name}: online authentication check failed") from None
