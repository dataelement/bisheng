"""Root-share fallback tests for system-default LLM model/server reads.

Covers ``bisheng.llm.domain.share_fallback`` plus the ``BishengBase``
integration path. Reproduces the v2.5.1 bug where a child tenant uploading
to a knowledge base backed by a Root system embedding would see
"embeddingModel configuration has been deleted": the in-scope SELECT was
filtered out by ``do_orm_execute``, and there was no fallback to a Root row
shared via ``Tenant.share_default_to_children``.

The helpers must:
  * skip the bypass when the in-scope read already returned a row
  * fall back to a bypassed read on miss, but only accept Root-owned rows
  * honour ``share_default_to_children`` — when share is off, return None
    so callers see a deterministic "deleted" error rather than a leaked
    cross-tenant row
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.share_fallback import (
    aget_model_by_id_with_share_fallback,
    aget_server_by_id_with_share_fallback,
    get_model_by_id_with_share_fallback,
    get_server_by_id_with_share_fallback,
)


def _root_tenant(share: bool):
    return MagicMock(share_default_to_children=1 if share else 0)


# --- sync model helper ------------------------------------------------------


def test_model_falsy_id_returns_none_without_db_calls():
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
    ) as mock_get:
        assert get_model_by_id_with_share_fallback(0) is None
        assert get_model_by_id_with_share_fallback(None) is None
    mock_get.assert_not_called()


def test_model_in_scope_hit_skips_bypass():
    own = MagicMock(id=42, server_id=7, tenant_id=5)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
        return_value=own,
    ) as mock_get, patch(
        'bisheng.llm.domain.share_fallback.TenantDao.get_by_id',
    ) as mock_tenant:
        result = get_model_by_id_with_share_fallback(42)
    assert result is own
    mock_get.assert_called_once_with(42, cache=False)
    mock_tenant.assert_not_called()


def test_model_in_scope_miss_then_root_share_on_returns_root():
    """The bug-repro path: child tenant in scope, model lives on Root,
    Root has share_default_to_children=1 → fallback returns the Root row."""
    root = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
        side_effect=[None, root],
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.get_by_id',
        return_value=_root_tenant(share=True),
    ):
        result = get_model_by_id_with_share_fallback(42)
    assert result is root


def test_model_in_scope_miss_then_root_share_off_returns_none():
    """Share disabled by Root admin → fallback must refuse, even though
    the row exists. This is the deliberate revocation path."""
    root = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
        side_effect=[None, root],
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.get_by_id',
        return_value=_root_tenant(share=False),
    ):
        result = get_model_by_id_with_share_fallback(42)
    assert result is None


def test_model_bypass_finds_non_root_row_returns_none():
    """Defense-in-depth: if the bypassed read surfaces a row owned by some
    other child tenant (shouldn't normally happen — the in-scope read would
    have caught the requester's own row), refuse it."""
    other = MagicMock(id=42, server_id=7, tenant_id=99)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
        side_effect=[None, other],
    ):
        result = get_model_by_id_with_share_fallback(42)
    assert result is None


def test_model_in_scope_miss_and_bypass_miss_returns_none():
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_model_by_id',
        side_effect=[None, None],
    ):
        assert get_model_by_id_with_share_fallback(42) is None


# --- sync server helper -----------------------------------------------------


def test_server_helper_returns_root_share():
    root_srv = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_server_by_id',
        side_effect=[None, root_srv],
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.get_by_id',
        return_value=_root_tenant(share=True),
    ):
        assert get_server_by_id_with_share_fallback(7) is root_srv


def test_server_helper_blocks_when_share_off():
    root_srv = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.get_server_by_id',
        side_effect=[None, root_srv],
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.get_by_id',
        return_value=_root_tenant(share=False),
    ):
        assert get_server_by_id_with_share_fallback(7) is None


# --- async helpers ----------------------------------------------------------


@pytest.mark.asyncio
async def test_amodel_in_scope_miss_then_root_share_on_returns_root():
    root = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_id',
        new=AsyncMock(side_effect=[None, root]),
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_root_tenant(share=True)),
    ):
        result = await aget_model_by_id_with_share_fallback(42)
    assert result is root


@pytest.mark.asyncio
async def test_amodel_in_scope_miss_then_root_share_off_returns_none():
    root = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.aget_model_by_id',
        new=AsyncMock(side_effect=[None, root]),
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_root_tenant(share=False)),
    ):
        result = await aget_model_by_id_with_share_fallback(42)
    assert result is None


@pytest.mark.asyncio
async def test_aserver_helper_returns_root_share():
    root_srv = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)
    with patch(
        'bisheng.llm.domain.share_fallback.LLMDao.aget_server_by_id',
        new=AsyncMock(side_effect=[None, root_srv]),
    ), patch(
        'bisheng.llm.domain.share_fallback.TenantDao.aget_by_id',
        new=AsyncMock(return_value=_root_tenant(share=True)),
    ):
        assert await aget_server_by_id_with_share_fallback(7) is root_srv


# --- BishengBase integration ------------------------------------------------


def test_bisheng_base_resolves_root_shared_pair():
    """BishengBase.get_model_server_info_sync transparently surfaces a
    root-shared (model, server) pair to a child caller — this is the path
    BishengEmbedding/LLM/Rerank/ASR/TTS take during instantiation, and the
    one that previously raised "embeddingModel configuration has been
    deleted" against a freshly created child tenant."""
    from bisheng.llm.domain.llm.base import BishengBase

    root_model = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    root_server = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)

    with patch(
        'bisheng.llm.domain.llm.base.get_model_by_id_with_share_fallback',
        return_value=root_model,
    ) as mock_m, patch(
        'bisheng.llm.domain.llm.base.get_server_by_id_with_share_fallback',
        return_value=root_server,
    ) as mock_s:
        m, s = BishengBase.get_model_server_info_sync(42)

    assert m is root_model
    assert s is root_server
    mock_m.assert_called_once_with(42, cache=True)
    mock_s.assert_called_once_with(7, cache=True)


def test_bisheng_base_propagates_none_when_share_blocked():
    """Share=off / row truly missing → fallback returns None and
    BishengBase short-circuits without looking up the server. The caller
    (BishengEmbedding._init_client) raises the deterministic
    "deleted, please reconfigure" error, which is correct for a revoked
    share."""
    from bisheng.llm.domain.llm.base import BishengBase

    with patch(
        'bisheng.llm.domain.llm.base.get_model_by_id_with_share_fallback',
        return_value=None,
    ), patch(
        'bisheng.llm.domain.llm.base.get_server_by_id_with_share_fallback',
    ) as mock_s:
        m, s = BishengBase.get_model_server_info_sync(42)

    assert (m, s) == (None, None)
    mock_s.assert_not_called()


@pytest.mark.asyncio
async def test_bisheng_base_async_resolves_root_shared_pair():
    from bisheng.llm.domain.llm.base import BishengBase

    root_model = MagicMock(id=42, server_id=7, tenant_id=ROOT_TENANT_ID)
    root_server = MagicMock(id=7, tenant_id=ROOT_TENANT_ID)

    with patch(
        'bisheng.llm.domain.llm.base.aget_model_by_id_with_share_fallback',
        new=AsyncMock(return_value=root_model),
    ), patch(
        'bisheng.llm.domain.llm.base.aget_server_by_id_with_share_fallback',
        new=AsyncMock(return_value=root_server),
    ):
        m, s = await BishengBase.get_model_server_info(42)

    assert m is root_model
    assert s is root_server


# --- cache key namespacing --------------------------------------------------


def test_cache_key_is_namespaced_by_tenant_scope():
    """Regression guard: prior to the fix the cache key was
    ``llm:model:<id>`` so a Root admin's read could be served back to a
    child tenant on the next call. The key must include the active
    tenant_id."""
    from bisheng.llm.domain import const as llm_const
    from bisheng.llm.domain.utils import wrapper_bisheng_llm_info

    llm_const.LLM_CACHE.clear()

    @wrapper_bisheng_llm_info(key_prefix='llm:model:')
    def _fake(cls, model_id, *, cache=False):
        return ('hit', model_id)

    with patch(
        'bisheng.core.context.tenant.get_current_tenant_id',
        return_value=1,
    ):
        _fake(None, 42, cache=True)
        # Root's value cached under t1; child's read must miss and re-resolve.
    with patch(
        'bisheng.core.context.tenant.get_current_tenant_id',
        return_value=5,
    ):
        # Different sentinel proves the child path didn't reuse Root's cache.
        @wrapper_bisheng_llm_info(key_prefix='llm:model:')
        def _fake_child(cls, model_id, *, cache=False):
            return ('child-hit', model_id)

        result = _fake_child(None, 42, cache=True)

    assert result == ('child-hit', 42)
    assert any(k.startswith('llm:model:t1:') for k in llm_const.LLM_CACHE.keys())
    assert any(k.startswith('llm:model:t5:') for k in llm_const.LLM_CACHE.keys())
