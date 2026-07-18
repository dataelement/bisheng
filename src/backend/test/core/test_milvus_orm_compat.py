"""Unit tests for the pymilvus 2.6 ORM-connection compatibility wrapper.

Full instantiation needs a live Milvus server (MilvusClient connects in __init__), so
these tests exercise the connection logic directly on a bare instance.
"""

from bisheng.core.vectorstore.milvus import Milvus


class _FakeConnections:
    def __init__(self):
        self._aliases = {}

    def has_connection(self, alias):
        return alias in self._aliases

    def connect(self, alias=None, **kwargs):
        self._aliases[alias] = kwargs


def _bare_instance(conn_args):
    inst = object.__new__(Milvus)  # bypass __init__ (which would connect to a server)
    inst._bisheng_conn_args = conn_args
    inst._bisheng_orm_ready = False
    return inst


def test_orm_alias_is_stable_and_connects_once(monkeypatch):
    fake = _FakeConnections()
    monkeypatch.setattr("bisheng.core.vectorstore.milvus.connections", fake)

    inst = _bare_instance({"uri": "http://h:19530", "db_name": "d", "user": "u", "password": "p"})
    alias1 = inst._ensure_orm_connection()
    alias2 = inst._ensure_orm_connection()

    assert alias1 == alias2 == "bisheng_orm::http://h:19530::d"
    # Connected exactly once (reused across calls -> no per-instance leak).
    assert list(fake._aliases) == [alias1]
    # Only ORM-relevant args are forwarded to connections.connect.
    assert fake._aliases[alias1] == {"uri": "http://h:19530", "db_name": "d", "user": "u", "password": "p"}


def test_two_instances_same_endpoint_share_one_orm_connection(monkeypatch):
    fake = _FakeConnections()
    monkeypatch.setattr("bisheng.core.vectorstore.milvus.connections", fake)

    a = _bare_instance({"uri": "http://h:19530", "db_name": "d"})._ensure_orm_connection()
    b = _bare_instance({"uri": "http://h:19530", "db_name": "d"})._ensure_orm_connection()

    assert a == b
    assert len(fake._aliases) == 1  # shared, not leaked per instance


def test_unrelated_milvus_kwargs_are_not_forwarded_to_connect(monkeypatch):
    fake = _FakeConnections()
    monkeypatch.setattr("bisheng.core.vectorstore.milvus.connections", fake)

    inst = _bare_instance({"uri": "http://h:19530", "timeout": 30, "foo": "bar"})
    alias = inst._ensure_orm_connection()
    assert fake._aliases[alias] == {"uri": "http://h:19530"}  # timeout/foo dropped
