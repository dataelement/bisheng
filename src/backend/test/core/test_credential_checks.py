"""Read-only probes and redacted failures: AC-09/11/14/17/20/21/23/27/40/41."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.core.config import credential_checks as checks


def settings():
    return SimpleNamespace(telemetry_elasticsearch=SimpleNamespace(elasticsearch_url=None))


def test_component_subset_does_not_touch_other_services(monkeypatch):
    calls = []
    monkeypatch.setattr(
        checks,
        "_PROBES",
        {name: lambda conf, n=name: calls.append(n) for name in ["mysql", "redis", "minio", "elasticsearch", "milvus"]},
    )
    checks.check_online(settings(), component="redis")
    assert calls == ["redis"]


def test_connection_errors_are_redacted(monkeypatch):
    def failure(conf):
        raise RuntimeError("driver error with secret-password")

    monkeypatch.setattr(checks, "_PROBES", {"mysql": failure})
    with pytest.raises(checks.CredentialConnectionError) as caught:
        checks.check_online(settings(), component="mysql")
    assert "secret-password" not in str(caught.value)
    assert "mysql" in str(caught.value)


def test_mysql_uses_read_only_query_and_disposes(monkeypatch):
    import sqlalchemy

    connection = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    create = MagicMock(return_value=engine)
    monkeypatch.setattr(sqlalchemy, "create_engine", create)
    conf = SimpleNamespace(
        database_url="mysql+pymysql://host/db", database_pool=SimpleNamespace(as_engine_kwargs=lambda: {})
    )
    checks._mysql(conf)
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    engine.dispose.assert_called_once()
    connection.commit.assert_not_called()


def test_redis_closes_new_client_after_ping_failure(monkeypatch):
    import redis

    client = MagicMock()
    client.ping.side_effect = RuntimeError("offline")
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(redis.Redis, "from_url", factory)
    with pytest.raises(RuntimeError):
        checks._redis(
            SimpleNamespace(redis_url="redis://:password@redis/1", celery_redis_url="redis://:password@redis/2")
        )
    client.close.assert_called_once()
    client.set.assert_not_called()
    client.flushdb.assert_not_called()


def test_es_reuses_verification_options_and_closes(monkeypatch):
    import elasticsearch

    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(elasticsearch, "Elasticsearch", factory)
    es = SimpleNamespace(
        elasticsearch_url="https://es:9200",
        ssl_verify={"verify_certs": True, "ca_certs": "/certs/ca.pem", "basic_auth": ("elastic", "private")},
    )
    checks._es(es)
    assert factory.call_args.kwargs["verify_certs"] is True
    assert factory.call_args.kwargs["ca_certs"] == "/certs/ca.pem"
    client.security.authenticate.assert_called_once()
    client.close.assert_called_once()
    client.indices.create.assert_not_called()


def test_unknown_component_fails_before_any_client(monkeypatch):
    probe = MagicMock()
    monkeypatch.setattr(checks, "_PROBES", {"mysql": probe})
    with pytest.raises(checks.CredentialConnectionError):
        checks.check_online(settings(), component="not-configured")
    probe.assert_not_called()


def test_redis_single_dict_keeps_tls_parameters(monkeypatch):
    import redis

    client = MagicMock()
    client.ping.return_value = True
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(redis.Redis, "from_url", factory)
    checks._redis_value(
        {"mode": "single", "url": "rediss://redis/1", "ssl_ca_certs": "/certs/ca.pem", "ssl_cert_reqs": "required"}
    )
    assert factory.call_args.kwargs["ssl_ca_certs"] == "/certs/ca.pem"
    assert factory.call_args.kwargs["ssl_cert_reqs"] == "required"
