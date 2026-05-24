"""Unit tests for scripts/revoke_business_resource_share.py.

Verifies the v2.6.0-beta2 cleanup script:
- iterates exactly the 5 retired business types (KS / workflow / assistant /
  channel / tool), never touches llm_server
- merges DB-driven and FGA-driven id discovery
- calls disable_sharing + set_is_shared for each id (dry_run=False)
- skips both calls under dry_run=True (but still reports counts)
- is idempotent — a second pass with no remaining tuples completes cleanly

Mocks all DB / FGA / TenantDao access so the script logic can be exercised
without a live MySQL or OpenFGA store.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts.revoke_business_resource_share import (
    RETIRED_SHAREABLE_TYPES,
    _TYPE_TO_TABLE,
    revoke,
)


def _patch_scans(db_ids: dict[str, set[str]], fga_ids: dict[str, set[str]]):
    """Patch the two scan helpers so the test owns what each pass returns."""

    async def fake_db(object_type: str) -> set[str]:
        return set(db_ids.get(object_type, set()))

    async def fake_fga(object_type: str) -> set[str]:
        return set(fga_ids.get(object_type, set()))

    return (
        patch(
            'scripts.revoke_business_resource_share._scan_db_ids',
            side_effect=fake_db,
        ),
        patch(
            'scripts.revoke_business_resource_share._scan_fga_ids',
            side_effect=fake_fga,
        ),
    )


def _patch_share_service(disable_return: list[int] | None = None):
    """Stub ResourceShareService methods invoked by the script."""
    disable_mock = AsyncMock(return_value=disable_return or [5, 7])
    list_children_mock = AsyncMock(return_value=disable_return or [5, 7])
    set_shared_mock = AsyncMock()
    return (
        patch(
            'scripts.revoke_business_resource_share.ResourceShareService.disable_sharing',
            disable_mock,
        ),
        patch(
            'scripts.revoke_business_resource_share.ResourceShareService.list_sharing_children',
            list_children_mock,
        ),
        patch(
            'scripts.revoke_business_resource_share.ResourceShareService.set_is_shared',
            set_shared_mock,
        ),
        disable_mock,
        list_children_mock,
        set_shared_mock,
    )


def test_retired_types_excludes_llm_server():
    """llm_server must stay in SUPPORTED — never enter the cleanup set."""
    assert 'llm_server' not in RETIRED_SHAREABLE_TYPES
    assert set(RETIRED_SHAREABLE_TYPES) == {
        'knowledge_space', 'workflow', 'assistant', 'channel', 'tool',
    }


def test_type_to_table_covers_every_retired_type():
    assert set(_TYPE_TO_TABLE.keys()) == set(RETIRED_SHAREABLE_TYPES)


@pytest.mark.asyncio
async def test_revoke_calls_disable_and_set_is_shared_for_each_resource():
    db_ids = {'knowledge_space': {'1', '2'}}
    fga_ids = {'knowledge_space': {'2', '3'}}  # union → {1,2,3}; '2' is in both
    db_patch, fga_patch = _patch_scans(db_ids, fga_ids)
    (
        disable_patch, list_patch, set_shared_patch,
        disable_mock, _, set_shared_mock,
    ) = _patch_share_service(disable_return=[5, 7])

    with db_patch, fga_patch, disable_patch, list_patch, set_shared_patch:
        rc = await revoke(types_filter=['knowledge_space'], dry_run=False)

    assert rc == 0
    # disable_sharing called once per merged id, only for knowledge_space
    assert disable_mock.await_count == 3
    called_pairs = {
        (call.args[0], call.args[1]) for call in disable_mock.await_args_list
    }
    assert called_pairs == {
        ('knowledge_space', '1'),
        ('knowledge_space', '2'),
        ('knowledge_space', '3'),
    }
    # set_is_shared mirrors the DB column for each id
    assert set_shared_mock.await_count == 3
    for call in set_shared_mock.await_args_list:
        assert call.args[0] == 'knowledge_space'
        assert call.args[2] is False  # always disabling


@pytest.mark.asyncio
async def test_revoke_skips_disable_in_dry_run_but_still_inspects_counts():
    db_patch, fga_patch = _patch_scans(
        {'workflow': {'a'}}, {'workflow': set()},
    )
    (
        disable_patch, list_patch, set_shared_patch,
        disable_mock, list_mock, set_shared_mock,
    ) = _patch_share_service(disable_return=[9])

    with db_patch, fga_patch, disable_patch, list_patch, set_shared_patch:
        rc = await revoke(types_filter=['workflow'], dry_run=True)

    assert rc == 0
    # dry_run must not mutate FGA or DB
    disable_mock.assert_not_awaited()
    set_shared_mock.assert_not_awaited()
    # but list_sharing_children IS called so the dry-run report is truthful
    list_mock.assert_awaited()


@pytest.mark.asyncio
async def test_revoke_returns_error_when_no_retired_types_selected():
    """Selecting llm_server alone (or any non-retired type) is a no-op + rc=1."""
    db_patch, fga_patch = _patch_scans({}, {})
    (
        disable_patch, list_patch, set_shared_patch,
        disable_mock, *_,
    ) = _patch_share_service()

    with db_patch, fga_patch, disable_patch, list_patch, set_shared_patch:
        rc = await revoke(types_filter=['llm_server'], dry_run=False)

    assert rc == 1
    disable_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_is_idempotent_with_empty_scan():
    """Second-pass cleanup: both scans empty → no FGA writes, success."""
    db_patch, fga_patch = _patch_scans(
        {t: set() for t in RETIRED_SHAREABLE_TYPES},
        {t: set() for t in RETIRED_SHAREABLE_TYPES},
    )
    (
        disable_patch, list_patch, set_shared_patch,
        disable_mock, _, set_shared_mock,
    ) = _patch_share_service()

    with db_patch, fga_patch, disable_patch, list_patch, set_shared_patch:
        rc = await revoke(types_filter=RETIRED_SHAREABLE_TYPES, dry_run=False)

    assert rc == 0
    disable_mock.assert_not_awaited()
    set_shared_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_never_touches_llm_server_when_full_set_selected():
    """Passing the full RETIRED set must still skip llm_server entirely
    (since llm_server is not in RETIRED in the first place)."""
    db_patch, fga_patch = _patch_scans(
        {t: {'x'} for t in RETIRED_SHAREABLE_TYPES},
        {},
    )
    (
        disable_patch, list_patch, set_shared_patch,
        disable_mock, *_,
    ) = _patch_share_service(disable_return=[5])

    with db_patch, fga_patch, disable_patch, list_patch, set_shared_patch:
        await revoke(types_filter=RETIRED_SHAREABLE_TYPES, dry_run=False)

    # Every disable_sharing call must target a retired (business) type
    for call in disable_mock.await_args_list:
        assert call.args[0] in RETIRED_SHAREABLE_TYPES
        assert call.args[0] != 'llm_server'
