"""Catalog registration preserves existing system and administrator state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.register_work_knowledge_tool import register, seed_records


def session_for(tools=(), categories=(), category=None):
    return SimpleNamespace(
        exec=AsyncMock(
            side_effect=[SimpleNamespace(all=lambda: list(tools)), SimpleNamespace(all=lambda: list(categories))]
        ),
        get=AsyncMock(return_value=category),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )


def row(**kwargs):
    return SimpleNamespace(id=80, type=90, tenant_id=1, user_id=None, is_preset=1, is_delete=0, **kwargs)


def test_seed_category_and_tool_contract():
    category, tool = seed_records()
    assert tool["type"] == category["id"]
    assert tool["tool_key"] == "bisheng_knowledge_search"
    assert {p["name"] for p in tool["api_params"]} == {"query", "space_ids"}
    assert category["user_id"] is None


async def test_preview_is_read_only():
    session = session_for()
    assert await register(session, apply=False) == {
        "status": "planned",
        "create_category": True,
        "create_tool": True,
    }
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


async def test_apply_allocates_database_ids_in_one_transaction():
    session = session_for()
    added = []
    session.add.side_effect = added.append

    async def flush():
        added[-1].id = 900 + len(added)

    session.flush.side_effect = flush
    result = await register(session, apply=True)
    assert result == {"status": "registered", "tool_id": 902, "category_id": 901}
    assert added[1].type == 901
    assert all(item.tenant_id == 1 and item.user_id is None for item in added)
    session.commit.assert_awaited_once()


async def test_rerun_preserves_existing_catalog_configuration():
    session = session_for(tools=[row()], category=row(extra='{"custom":"preserved"}'))
    assert await register(session, apply=True) == {"status": "current", "tool_id": 80, "category_id": 80}
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("field,value", [("user_id", 42), ("tenant_id", 5), ("is_delete", 1), ("is_preset", 0)])
async def test_conflicting_tool_is_preserved(field, value):
    tool = row()
    setattr(tool, field, value)
    session = session_for(tools=[tool])
    with pytest.raises(ValueError, match="Catalog conflict"):
        await register(session, apply=True)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


async def test_duplicate_keys_require_operator_resolution():
    session = session_for(tools=[row(), row()])
    with pytest.raises(ValueError, match="multiple tools"):
        await register(session, apply=True)
    session.add.assert_not_called()
