"""SQL agent URLs keep special characters inside the password field."""

from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from sqlalchemy.engine.url import URL

from bisheng.workflow.nodes.agent.agent import AgentNode, SqlAgentParams, build_sql_agent_url
from bisheng_langchain.gpts.tools.sql_agent.tool import SqlAgentAPIWrapper

_HOST = "10.0.0.1"


def _address_url(engine: str, password: str = "p@ss", address: str = "10.0.0.1:3306", database: str = "app") -> URL:
    node = AgentNode.__new__(AgentNode)
    node._sql_agent = SqlAgentParams(
        database_engine=engine,
        db_username="user",
        db_password=password,
        db_address=address,
        db_name=database,
        open=True,
    )
    return node._init_sql_address()


@pytest.mark.parametrize(
    "engine,driver",
    [
        ("mysql", "mysql+pymysql"),
        ("db2", "db2+ibm_db"),
        ("postgres", "postgresql+psycopg2"),
        ("postgresql", "postgresql+psycopg2"),
        ("gaussdb", "opengauss+psycopg2"),
        ("oracle", "oracle+oracledb"),
    ],
)
@pytest.mark.parametrize("password", ["p@ss", "a#b", "a/b", "a?b", "100%", "a b", "secret"])
def test_sql_agent_url_keeps_password_and_host(engine, driver, password):
    url = _address_url(engine, password=password)
    assert isinstance(url, URL)
    assert url.drivername == driver
    assert url.username == "user"
    assert url.password == password
    assert url.password != "***"
    assert url.host == _HOST
    assert url.port == 3306


def test_username_at_sign_stays_in_username():
    url = build_sql_agent_url("mysql", "user@corp", "secret", "10.0.0.1:3306", "app")
    assert url.username == "user@corp"
    assert url.password == "secret"
    assert url.host == _HOST


def test_address_without_port_leaves_port_empty():
    url = _address_url("mysql", address="db.example.com")
    assert url.host == "db.example.com"
    assert url.port is None


def test_ipv6_host_has_no_brackets():
    url = _address_url("mysql", address="[::1]:3306")
    assert url.host == "::1"
    assert url.port == 3306


def test_mysql_charset_and_oracle_service_name():
    mysql = _address_url("mysql", database="app")
    assert mysql.database == "app"
    assert mysql.query["charset"] == "utf8mb4"

    oracle = _address_url("oracle", database="ORCLPDB")
    assert oracle.database is None
    assert oracle.query["service_name"] == "ORCLPDB"


def test_from_uri_receives_the_url_object(monkeypatch):
    captured = {}

    def fake_from_uri(database_uri, engine_args=None, **kwargs):
        captured["uri"] = database_uri
        return SimpleNamespace(dialect="mysql")

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.sql_agent.tool.SQLDatabase.from_uri",
        fake_from_uri,
    )

    class _Toolkit:
        def __init__(self, *args, **kwargs):
            pass

        def get_tools(self):
            return []

    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.sql_agent.tool.SQLDatabaseToolkit",
        _Toolkit,
    )
    monkeypatch.setattr(
        "bisheng_langchain.gpts.tools.sql_agent.tool.create_react_agent",
        lambda *args, **kwargs: object(),
    )

    url = _address_url("mysql", password="p@ss")
    SqlAgentAPIWrapper(llm=GenericFakeChatModel(messages=iter(())), sql_address=url)
    assert captured["uri"] is url
    assert captured["uri"].password == "p@ss"
