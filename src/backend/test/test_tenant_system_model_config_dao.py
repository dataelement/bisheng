"""F022 T01 TenantSystemModelConfigDao tests — fallback resolution branches.

Mocks the async session context manager + ``TenantDao.aget_by_id`` so we
can assert all five branches of ``aresolve()`` without standing up a DB:

  * own row + value           → (value, False, False)        — AC-05
  * tenant_id == Root          → (None,  False, False)        — AC-02 fallback path
  * Root row missing           → (None,  False, False)        — AC-07
  * Root has value, share=on   → (root.value, True,  False)   — AC-03 / AC-26
  * Root has value, share=off  → (None,  False, True)         — AC-06

Plus aupsert insert/update branches.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.models.tenant_system_model_config import (
    TenantSystemModelConfig,
    TenantSystemModelConfigDao,
)


def _session_context(mock_session):
    """Async context manager that yields ``mock_session``."""

    @asynccontextmanager
    async def _cm():
        yield mock_session

    return _cm


def _mk_session_returning(rows_per_call):
    """Build an async-mocked session whose ``exec`` returns the given
    rows on successive calls. ``rows_per_call`` is a list of "first()
    returns" — each entry is the value to return when ``.first()`` is
    called on the result of the next ``exec``.
    """
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    results = []
    for row in rows_per_call:
        r = MagicMock()
        r.first = MagicMock(return_value=row)
        results.append(r)
    session.exec = AsyncMock(side_effect=results)
    return session


def _mk_row(tenant_id: int, key: str, value: str | None) -> TenantSystemModelConfig:
    return TenantSystemModelConfig(tenant_id=tenant_id, key=key, value=value)


def _mk_root_tenant(share: bool):
    """Mocked Root Tenant row — only the share_default_to_children flag matters."""
    t = MagicMock()
    t.share_default_to_children = 1 if share else 0
    return t


# --- aresolve branches ------------------------------------------------------


@pytest.mark.asyncio
async def test_aresolve_returns_own_row_when_present():
    own = _mk_row(5, 'knowledge_llm', '{"k": 1}')
    session = _mk_session_returning([own])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=5, key='knowledge_llm',
        )
    assert value == '{"k": 1}'
    assert inherited is False
    assert blocked is False


@pytest.mark.asyncio
async def test_aresolve_root_tenant_no_fallback_loop():
    """When tenant_id == Root, aresolve must not recurse to look up Root again."""
    session = _mk_session_returning([None])  # own absent
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=1, key='knowledge_llm',
        )
    assert value is None
    assert (inherited, blocked) == (False, False)
    # Only one exec call — own lookup, no Root re-read.
    assert session.exec.await_count == 1


@pytest.mark.asyncio
async def test_aresolve_returns_empty_when_root_also_unset():
    """AC-07: Child has no row + Root has no row → empty + not blocked."""
    session = _mk_session_returning([None, None])  # own None, root None
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=5, key='knowledge_llm',
        )
    assert value is None
    assert (inherited, blocked) == (False, False)


@pytest.mark.asyncio
async def test_aresolve_inherits_root_when_share_enabled():
    """AC-03: own absent + Root row + share=1 → inherited=True."""
    root_row = _mk_row(1, 'knowledge_llm', '{"shared": true}')
    session = _mk_session_returning([None, root_row])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ), patch(
        'bisheng.database.models.tenant.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_mk_root_tenant(share=True)),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=5, key='knowledge_llm',
        )
    assert value == '{"shared": true}'
    assert inherited is True
    assert blocked is False


@pytest.mark.asyncio
async def test_aresolve_blocks_when_root_share_disabled():
    """AC-06: own absent + Root row + share=0 → fallback_blocked=True, value None."""
    root_row = _mk_row(1, 'knowledge_llm', '{"private": true}')
    session = _mk_session_returning([None, root_row])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ), patch(
        'bisheng.database.models.tenant.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_mk_root_tenant(share=False)),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=5, key='knowledge_llm',
        )
    assert value is None
    assert inherited is False
    assert blocked is True


@pytest.mark.asyncio
async def test_aresolve_treats_empty_string_as_unset():
    """A row with value='' must not be treated as a hit — same path as no row."""
    own_empty = _mk_row(5, 'knowledge_llm', '')
    root = _mk_row(1, 'knowledge_llm', '{"r": 1}')
    session = _mk_session_returning([own_empty, root])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ), patch(
        'bisheng.database.models.tenant.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_mk_root_tenant(share=True)),
    ):
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=5, key='knowledge_llm',
        )
    assert value == '{"r": 1}'
    assert inherited is True


# --- aupsert branches -------------------------------------------------------


@pytest.mark.asyncio
async def test_aupsert_inserts_when_row_absent():
    session = _mk_session_returning([None])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ):
        result = await TenantSystemModelConfigDao.aupsert(
            tenant_id=5, key='knowledge_llm', value='{"v": 1}',
        )
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    assert result.tenant_id == 5
    assert result.key == 'knowledge_llm'
    assert result.value == '{"v": 1}'


@pytest.mark.asyncio
async def test_aupsert_updates_when_row_present():
    existing = _mk_row(5, 'knowledge_llm', '{"old": 1}')
    session = _mk_session_returning([existing])
    with patch(
        'bisheng.llm.domain.models.tenant_system_model_config.get_async_db_session',
        _session_context(session),
    ):
        result = await TenantSystemModelConfigDao.aupsert(
            tenant_id=5, key='knowledge_llm', value='{"new": 2}',
        )
    assert result is existing
    assert existing.value == '{"new": 2}'
    session.commit.assert_awaited_once()
