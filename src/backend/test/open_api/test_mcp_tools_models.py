"""F052 T210 — the model list, whose names must be the ones the protocol face accepts.

This tool exists for exactly one reason: an agent needs to know what to pass as
``model``. So the names come from F051's resolver and from nowhere else. A second
naming rule here would be a second answer to the same question, and the tool's
whole value would be gone the first time the two disagreed.

Until that resolver lands the tool is **absent** from ``tools/list`` rather than
present and answering with names nobody can call — the last test asserts that,
so a skipped file cannot pass as "the tool works".
"""

from __future__ import annotations

import pytest

from bisheng.open_api.mcp import registry
from bisheng.open_api.mcp.tools import models as model_tools

from .test_mcp_server import auth, error_payload, principal


@pytest.fixture
def bearer(monkeypatch):
    def install(value):
        async def validate(_authorization):
            return value

        monkeypatch.setattr("bisheng.open_api.api.dependencies.validate_bearer", validate)

    return install


@pytest.fixture
def resolver(monkeypatch):
    """Stand in for F051's resolver at whichever module name it landed under."""

    if not model_tools.resolver_available():
        pytest.skip("F051 model name resolution has not landed on this tree yet")

    calls: list[int] = []
    rows: list[dict] = []

    async def resolve(tenant_id):
        calls.append(tenant_id)
        return rows

    monkeypatch.setattr(model_tools, "_resolver", lambda: resolve)
    return type("Resolver", (), {"calls": calls, "rows": rows})()


async def test_the_published_name_is_the_one_the_protocol_face_will_accept(bearer, mcp_session, resolver):
    """Unique names go out bare; ambiguous ones go out provider-qualified."""

    resolver.rows.extend(
        [
            {
                "name": "qwen-max",
                "qualified_name": "dashscope/qwen-max",
                "is_ambiguous": False,
                "model_type": "llm",
                "is_chat": True,
                "server_name": "dashscope",
            },
            {
                "name": "gpt-4o",
                "qualified_name": "azure/gpt-4o",
                "is_ambiguous": True,
                "model_type": "llm",
                "is_chat": True,
                "server_name": "azure",
            },
        ]
    )
    bearer(principal(scopes=frozenset({"model:invoke"})))
    async with mcp_session(auth()) as session:
        result = await session.call_tool("bisheng_model_list", {})

    by_name = {item["name"]: item for item in result.structuredContent["models"]}
    assert by_name["qwen-max"]["callable_name"] == "qwen-max"
    assert by_name["gpt-4o"]["callable_name"] == "azure/gpt-4o"
    assert by_name["gpt-4o"]["is_chat"] is True


async def test_the_list_is_tenant_wide_not_per_key(bearer, mcp_session, resolver):
    """The range is a tenant-level configuration; two keys in one tenant agree."""

    bearer(principal(scopes=frozenset({"model:invoke"})))
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_model_list", {})
    async with mcp_session(auth()) as session:
        await session.call_tool("bisheng_model_list", {})

    assert resolver.calls == [9, 9]


async def test_without_the_scope_the_tool_is_neither_listed_nor_callable(bearer, mcp_session, resolver):
    bearer(principal(scopes=frozenset({"knowledge:read"})))
    async with mcp_session(auth()) as session:
        listed = {tool.name for tool in (await session.list_tools()).tools}
        payload = error_payload(await session.call_tool("bisheng_model_list", {}))

    assert "bisheng_model_list" not in listed
    assert payload["data"]["required"] == "model:invoke"


def test_the_tool_derives_no_name_of_its_own():
    """No separator, no provider-joining rule — that logic belongs to F051 alone."""

    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parents[2] / "bisheng" / "open_api" / "mcp" / "tools" / "models.py"
    ).read_text(encoding="utf-8")
    assert "get_all_llm" not in source
    assert 'f"{' not in source  # no name composed here


def test_the_tool_is_absent_until_the_resolver_lands():
    """Absent, not present-and-wrong: a name nobody can call is worse than no list."""

    installed = {spec.name for spec in registry.installed_tools()}
    assert ("bisheng_model_list" in installed) is model_tools.resolver_available()
