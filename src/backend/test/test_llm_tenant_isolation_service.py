"""F020 T07 LLMService behavioural tests.

Focuses on the two new Service-layer surfaces that carry the Tenant
visibility logic:

- ``LLMService.get_all_llm`` merging leaf-tenant rows with Root-shared
  rows under different caller profiles (AC-03 / AC-13 / AC-14 / AC-15).
- ``LLMService.get_model_for_call`` raising 19802 when the target is
  not reachable and succeeding on Root-shared models for Child callers
  (AC-20 / AC-22 / AC-23).

The full ``add_llm_server`` / ``update_llm_server`` flows are exercised
by T08 API-layer integration tests; unit-testing them here would require
mocking ~7 collaborators (Redis, LangChain model factories, the
post-insert hook that calls get_workbench_llm, etc.) for little marginal
signal.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.services.llm import LLMService


DAO = 'bisheng.llm.domain.services.llm.LLMDao'
CONTEXT = 'bisheng.llm.domain.services.llm'


def _mk_server(sid: int, tenant_id: int, name: str = ''):
    s = MagicMock()
    s.id = sid
    s.tenant_id = tenant_id
    s.name = name or f's{sid}'
    # model_dump needs to exclude config; the Service uses .model_dump(exclude={'config'})
    # → produce a plain dict return so LLMServerInfo(**dump) constructs cleanly.
    s.model_dump = MagicMock(return_value={
        'id': sid, 'tenant_id': tenant_id, 'name': name or f's{sid}',
        'description': '', 'type': 'openai', 'limit_flag': False, 'limit': 0,
        'user_id': 1,
    })
    return s


# --- get_all_llm merge --------------------------------------------------


@pytest.mark.asyncio
async def test_child_user_llm_list_merges_root_shared():
    """AC-03: Child (leaf=5) sees own servers + Root-shared ones flagged readonly."""
    own = _mk_server(10, tenant_id=5, name='own')
    shared = _mk_server(100, tenant_id=1, name='root-shared')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[own])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[100])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[shared])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm()

    ids = [r.id for r in result]
    assert 10 in ids and 100 in ids
    shared_row = [r for r in result if r.id == 100][0]
    own_row = [r for r in result if r.id == 10][0]
    assert shared_row.is_root_shared_readonly is True
    assert own_row.is_root_shared_readonly is False


@pytest.mark.asyncio
async def test_super_admin_without_scope_sees_all_root():
    """AC-15: leaf=1 (super admin without scope) → just the Root rows, no flag."""
    root1 = _mk_server(1, tenant_id=1, name='r1')
    root2 = _mk_server(2, tenant_id=1, name='r2')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[root1, root2])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm()

    assert len(result) == 2
    assert all(r.is_root_shared_readonly is False for r in result)


@pytest.mark.asyncio
async def test_super_admin_with_scope_acts_as_child():
    """AC-13 / AC-14: super admin with F019 scope=5 sees the Child 5 view.

    Because ``get_current_tenant_id`` already honours the admin-scope
    override (F019), the Service code path is identical to a genuine
    Child user; mocking ``get_current_tenant_id`` to return 5 simulates
    the middleware outcome.
    """
    own = _mk_server(50, tenant_id=5, name='child5-own')
    shared = _mk_server(200, tenant_id=1, name='root-shared-to-5')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[own])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[200])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[shared])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm()

    assert [r.id for r in result] == [50, 200]
    assert {r.id: r.is_root_shared_readonly for r in result} == {50: False, 200: True}


@pytest.mark.asyncio
async def test_get_all_llm_dedupes_leaf_vs_shared_overlap():
    """Root's own callers should not see duplicate entries when a Root
    row exists in both the leaf query (leaf==Root) and the shared list
    (which is always empty when leaf==Root). Regression guard for the
    short-circuit in ``aget_shared_server_ids_for_leaf(1)``."""
    root1 = _mk_server(1, tenant_id=1)
    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[root1])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm()
    assert [r.id for r in result] == [1]


# --- get_model_for_call -------------------------------------------------


@pytest.mark.asyncio
async def test_get_model_for_call_own_model_returns():
    """AC-22: caller tenant owns the model → returned directly (event
    filter finds it; no bypass needed)."""
    own = MagicMock(id=10, server_id=50, tenant_id=5)
    with patch(f'{DAO}.aget_model_by_id', new=AsyncMock(return_value=own)):
        result = await LLMService.get_model_for_call(10)
    assert result is own


@pytest.mark.asyncio
async def test_get_model_for_call_root_shared_accessible_for_child():
    """AC-20: model hidden by event filter but owned by a Root server in
    the caller's shared list → bypass lookup resolves it."""
    raw = MagicMock(id=100, server_id=200, tenant_id=1)
    mock_fn = AsyncMock()
    mock_fn.side_effect = [None, raw]  # event-filtered miss, then bypass hit

    with patch(f'{DAO}.aget_model_by_id', mock_fn), \
            patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[200])):
        result = await LLMService.get_model_for_call(100)
    assert result is raw


@pytest.mark.asyncio
async def test_get_model_for_call_cross_child_raises_19802():
    """AC-22 / AC-23: model exists but belongs to a different Child and
    is not Root-shared → 19802."""
    from fastapi import HTTPException

    raw = MagicMock(id=100, server_id=201, tenant_id=7)
    mock_fn = AsyncMock()
    mock_fn.side_effect = [None, raw]

    with patch(f'{DAO}.aget_model_by_id', mock_fn), \
            patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_model_for_call(100)
    assert excinfo.value.status_code == 19802


@pytest.mark.asyncio
async def test_get_model_for_call_unknown_id_raises_19802():
    """Boundary: model id is simply unknown (no row at all) → 19802."""
    from fastapi import HTTPException

    mock_fn = AsyncMock(return_value=None)  # both attempts miss
    with patch(f'{DAO}.aget_model_by_id', mock_fn):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_model_for_call(9999)
    assert excinfo.value.status_code == 19802
