"""F017 unit tests — ResourceShareService FGA tuple wrapper (T03).

Mocks FGAClient + TenantDao to verify write/read/delete parameter shapes.
Follows F013 test style: AsyncMock + patch, no real OpenFGA store.

Covered behaviors:
- ``enable_sharing`` writes one shared_with tuple per active Child
- ``enable_sharing`` returns empty + does not call FGA when no active Children
- ``disable_sharing`` deletes only ``shared_with → tenant:*`` tuples, ignoring
  other relations (e.g. owner) present on the same object
- ``distribute_to_child`` / ``revoke_from_child`` write / delete Tenant-level
  ``shared_to`` tuple with correct (user, relation, object)
- ``list_sharing_children`` returns the Child ids parsed from read_tuples
- Unsupported resource type raises ValueError
"""

from __future__ import annotations

from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.tenant.domain.services.resource_share_service import (
    SUPPORTED_SHAREABLE_TYPES,
    ResourceShareService,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_fga(read_return: List[dict] = None):
    """Create a mock FGAClient with async stubs."""
    fga = AsyncMock()
    fga.write_tuples = AsyncMock(return_value=None)
    fga.read_tuples = AsyncMock(return_value=read_return or [])
    return fga


def _patch_fga(fga):
    return patch.object(ResourceShareService, '_get_fga', return_value=fga)


def _patch_children(child_ids: List[int]):
    return patch(
        'bisheng.tenant.domain.services.resource_share_service.TenantDao.aget_children_ids_active',
        AsyncMock(return_value=child_ids),
    )


# ── enable_sharing ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_sharing_writes_shared_with_tuples_per_child():
    """One shared_with tuple per active Child, correct (user, relation, object) shape."""
    fga = _make_fga()
    with _patch_fga(fga), _patch_children([5, 7, 9]):
        result = await ResourceShareService.enable_sharing(
            'knowledge_space', '42', root_tenant_id=1,
        )

    assert result == [5, 7, 9]
    fga.write_tuples.assert_awaited_once()
    writes = fga.write_tuples.await_args.kwargs['writes']
    assert len(writes) == 3
    assert {w['user'] for w in writes} == {'tenant:5', 'tenant:7', 'tenant:9'}
    assert {w['relation'] for w in writes} == {'shared_with'}
    assert {w['object'] for w in writes} == {'knowledge_space:42'}


@pytest.mark.asyncio
async def test_enable_sharing_no_active_children_returns_empty():
    """No FGA write when there are no active Children; return empty list."""
    fga = _make_fga()
    with _patch_fga(fga), _patch_children([]):
        result = await ResourceShareService.enable_sharing(
            'workflow', 'abc-123', root_tenant_id=1,
        )
    assert result == []
    fga.write_tuples.assert_not_awaited()


# ── disable_sharing ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disable_sharing_deletes_only_shared_with_tenant_tuples():
    """disable_sharing must ignore non-shared_with relations and non-tenant users."""
    existing_tuples = [
        {'user': 'tenant:5', 'relation': 'shared_with', 'object': 'assistant:x'},
        {'user': 'tenant:7', 'relation': 'shared_with', 'object': 'assistant:x'},
        # Should NOT be deleted:
        {'user': 'user:100', 'relation': 'owner', 'object': 'assistant:x'},
        {'user': 'user:200', 'relation': 'editor', 'object': 'assistant:x'},
    ]
    fga = _make_fga(read_return=existing_tuples)
    with _patch_fga(fga):
        result = await ResourceShareService.disable_sharing('assistant', 'x')

    assert result == [5, 7]
    fga.read_tuples.assert_awaited_once_with(
        relation='shared_with', object='assistant:x',
    )
    fga.write_tuples.assert_awaited_once()
    deletes = fga.write_tuples.await_args.kwargs['deletes']
    assert len(deletes) == 2
    assert {d['user'] for d in deletes} == {'tenant:5', 'tenant:7'}
    assert {d['relation'] for d in deletes} == {'shared_with'}


@pytest.mark.asyncio
async def test_disable_sharing_no_shared_tuples_is_noop():
    """When object has no shared_with tuples, no delete call is made."""
    fga = _make_fga(read_return=[
        {'user': 'user:100', 'relation': 'owner', 'object': 'channel:c1'},
    ])
    with _patch_fga(fga):
        result = await ResourceShareService.disable_sharing('channel', 'c1')
    assert result == []
    fga.write_tuples.assert_not_awaited()


# ── distribute_to_child / revoke_from_child ──────────────────────


@pytest.mark.asyncio
async def test_distribute_to_child_writes_shared_to_tuple():
    """Tenant-level shared_to tuple: user=tenant:{child}, relation=shared_to, object=tenant:{root}."""
    fga = _make_fga()
    with _patch_fga(fga):
        await ResourceShareService.distribute_to_child(child_id=5, root_tenant_id=1)
    fga.write_tuples.assert_awaited_once_with(writes=[
        {'user': 'tenant:5', 'relation': 'shared_to', 'object': 'tenant:1'},
    ])


@pytest.mark.asyncio
async def test_revoke_from_child_deletes_shared_to_tuple():
    """Symmetric delete of the shared_to tuple."""
    fga = _make_fga()
    with _patch_fga(fga):
        await ResourceShareService.revoke_from_child(child_id=5, root_tenant_id=1)
    fga.write_tuples.assert_awaited_once_with(deletes=[
        {'user': 'tenant:5', 'relation': 'shared_to', 'object': 'tenant:1'},
    ])


# ── list_sharing_children ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sharing_children_parses_child_ids():
    """Return child ids parsed from shared_with tuples; ignore other relations."""
    fga = _make_fga(read_return=[
        {'user': 'tenant:5', 'relation': 'shared_with', 'object': 'tool:t1'},
        {'user': 'tenant:7', 'relation': 'shared_with', 'object': 'tool:t1'},
        {'user': 'user:1', 'relation': 'owner', 'object': 'tool:t1'},
    ])
    with _patch_fga(fga):
        result = await ResourceShareService.list_sharing_children('tool', 't1')
    assert sorted(result) == [5, 7]


# ── Validation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_resource_type_raises_on_enable():
    with pytest.raises(ValueError, match='Unsupported resource type'):
        await ResourceShareService.enable_sharing('dashboard', '1')


@pytest.mark.asyncio
async def test_unsupported_resource_type_raises_on_disable():
    with pytest.raises(ValueError, match='Unsupported resource type'):
        await ResourceShareService.disable_sharing('dashboard', '1')


def test_supported_types_constant_matches_spec():
    """SUPPORTED_SHAREABLE_TYPES must stay aligned with the live DSL set."""
    assert SUPPORTED_SHAREABLE_TYPES == {
        'knowledge_space', 'workflow', 'assistant', 'channel', 'tool', 'llm_server',
    }


# ── OpenFGA-disabled degradation ─────────────────────────────────


@pytest.mark.asyncio
async def test_enable_sharing_noop_when_fga_disabled():
    """When get_fga_client() returns None (OpenFGA disabled in local dev),
    enable_sharing returns empty without crashing."""
    with patch.object(ResourceShareService, '_get_fga', return_value=None):
        result = await ResourceShareService.enable_sharing('assistant', '1')
    assert result == []


@pytest.mark.asyncio
async def test_distribute_to_child_noop_when_fga_disabled():
    with patch.object(ResourceShareService, '_get_fga', return_value=None):
        # Should not raise even with no FGA
        await ResourceShareService.distribute_to_child(child_id=5)


@pytest.mark.asyncio
async def test_enable_sharing_prefers_async_fga_accessor():
    fga = _make_fga()
    with patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=fga,
    ) as async_get_fga, patch.object(
        ResourceShareService,
        '_get_fga',
        return_value=None,
    ), _patch_children([5]):
        result = await ResourceShareService.enable_sharing('assistant', '1')

    assert result == [5]
    async_get_fga.assert_awaited_once()
    fga.write_tuples.assert_awaited_once()
