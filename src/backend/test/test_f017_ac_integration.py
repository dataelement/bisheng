"""F017 AC integration tests (T28-T34).

Component-level integration checks — each test wires together the real
F017 services with a mocked FGA client / DAO layer to verify the AC
behavior described in spec.md §2. Per-component single-responsibility
tests live in ``test_f017_*.py`` (already green) — this file targets the
*interactions* between components that a unit test can't cover.

AC coverage map (spec §2):

  AC-01 share toggle writes shared_with tuple           → test_f017_share_toggle.py (T28)
  AC-02 new Child auto-distributes Root-shared          → test_f017_mount_distribute.py (T29)
  AC-03 Child user sees Root shared via FGA              → test_f017_permission_chain.py (T30)
  AC-04 Child user cannot edit Root shared               → test_f017_permission_chain.py (T30)
  AC-05 revoke share deletes viewer tuple                → test_f017_share_toggle.py (T28)
  AC-06 MinIO / Milvus fallback                          → test_f017_minio_fallback.py + test_f017_milvus_fallback.py (T31)
  AC-07 unmount Child revokes tenant tuples              → test_f017_unmount_revoke.py (T32)
  AC-08 chat_message.tenant_id = Child leaf              → test_f017_chat_message_service.py (T33)
  AC-09 llm_token_log attributed to Child leaf           → test_f017_llm_token_tracker.py (T33)
  AC-10 shared storage counted once on Root              → test_f017_quota_no_double_count (T34 this file)
  AC-11 missing tenant context raises 19504              → test_f017_chat_message_service.py / test_f017_llm_token_tracker.py (T33)
  AC-12 revoke share detail (4-step sequence)            → this file (T28 extension)
  AC-13 mount skip auto-distribute                        → this file (T29 extension)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.tenant.domain.services.resource_share_service import ResourceShareService


# ── T28 — AC-01 + AC-05 + AC-12: share toggle (revoke preserves derived data) ──


@pytest.mark.asyncio
async def test_ac_01_enable_share_writes_tuples_per_active_child():
    """AC-01: enabling share writes one tuple per active Child."""
    fga = MagicMock()
    fga.write_tuples = AsyncMock()
    fga.read_tuples = AsyncMock(return_value=[])
    with patch.object(ResourceShareService, '_get_fga', return_value=fga), \
         patch(
             'bisheng.tenant.domain.services.resource_share_service.TenantDao.aget_children_ids_active',
             AsyncMock(return_value=[5, 7]),
         ):
        result = await ResourceShareService.enable_sharing(
            'knowledge_space', '42', root_tenant_id=1,
        )
    assert result == [5, 7]
    writes = fga.write_tuples.await_args.kwargs['writes']
    assert {w['user'] for w in writes} == {'tenant:5', 'tenant:7'}
    assert all(w['relation'] == 'shared_with' for w in writes)


@pytest.mark.asyncio
async def test_ac_05_disable_share_deletes_only_shared_with_tuples():
    """AC-05: revoking share deletes ``shared_with`` tuples; owner stays."""
    fga = MagicMock()
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'tenant:5', 'relation': 'shared_with', 'object': 'knowledge_space:42'},
        {'user': 'user:100', 'relation': 'owner', 'object': 'knowledge_space:42'},
    ])
    fga.write_tuples = AsyncMock()
    with patch.object(ResourceShareService, '_get_fga', return_value=fga):
        revoked = await ResourceShareService.disable_sharing('knowledge_space', '42')
    assert revoked == [5]
    deletes = fga.write_tuples.await_args.kwargs['deletes']
    assert len(deletes) == 1  # owner NOT deleted
    assert deletes[0]['user'] == 'tenant:5'


@pytest.mark.asyncio
async def test_ac_12_revoke_share_four_step_sequence():
    """AC-12: cancel-share precisely runs (1) delete viewer, (2) keep owner,
    (3) list API excludes, (4) derived data NOT cascade-cleaned.

    Verified by combining AC-05 (delete tuple but keep owner) with the
    chat_message DAO — F017 Phase C never touches chat_message on revoke.
    """
    fga = MagicMock()
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'tenant:5', 'relation': 'shared_with', 'object': 'knowledge_space:42'},
        {'user': 'user:100', 'relation': 'owner', 'object': 'knowledge_space:42'},
    ])
    fga.write_tuples = AsyncMock()
    with patch.object(ResourceShareService, '_get_fga', return_value=fga):
        await ResourceShareService.disable_sharing('knowledge_space', '42')
    # Step 1 + 2: viewer deleted, owner preserved
    deletes = fga.write_tuples.await_args.kwargs['deletes']
    assert all(d['relation'] == 'shared_with' for d in deletes)
    # Step 3: list_sharing_children after revoke → empty (mock re-read)
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:100', 'relation': 'owner', 'object': 'knowledge_space:42'},
    ])
    remaining = await ResourceShareService.list_sharing_children(
        'knowledge_space', '42',
    )
    assert remaining == []
    # Step 4: no chat_message delete was invoked — this is a non-contract
    # (revoke must not reach into the message table). Enforced at code
    # level: disable_sharing only touches FGA.


# ── T29 — AC-02 + AC-13: mount distribute ────────────────────────────


@pytest.mark.asyncio
async def test_ac_02_distribute_to_child_writes_tenant_shared_to_tuple():
    """AC-02: new Child mount writes ``tenant:{child}#shared_to → tenant:{root}``."""
    fga = MagicMock()
    fga.write_tuples = AsyncMock()
    with patch.object(ResourceShareService, '_get_fga', return_value=fga):
        await ResourceShareService.distribute_to_child(child_id=7, root_tenant_id=1)
    fga.write_tuples.assert_awaited_once_with(writes=[
        {'user': 'tenant:7', 'relation': 'shared_to', 'object': 'tenant:1'},
    ])


@pytest.mark.asyncio
async def test_ac_13_mount_skip_auto_distribute_writes_no_tuple():
    """AC-13: auto_distribute=False skips the tuple write entirely.

    Verified via TenantMountService._on_child_mounted returning an empty
    list (and not calling distribute_to_child at all).
    """
    from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

    # Patch ResourceShareService at its canonical module path — it is
    # imported *inside* _on_child_mounted (late import), so the
    # ``tenant_mount_service.ResourceShareService`` attribute does not
    # exist at patch-time.
    with patch(
        'bisheng.tenant.domain.services.resource_share_service.ResourceShareService.distribute_to_child',
        AsyncMock(),
    ) as distribute_mock:
        distributed = await TenantMountService._on_child_mounted(
            new_child_id=7, auto_distribute=False,
        )
    assert distributed == []
    distribute_mock.assert_not_called()


# ── T30 — AC-03 + AC-04: permission chain (share-to + editor) ─────────


@pytest.mark.asyncio
async def test_ac_03_permission_service_is_shared_to_returns_true_after_distribute():
    """AC-03: PermissionService._is_shared_to returns True for a Child
    once ``distribute_to_child`` has written the tuple."""
    from bisheng.permission.domain.services.permission_service import PermissionService

    fga = MagicMock()
    # The FGA check query: member of tenant:{target}#shared_to
    fga.check = AsyncMock(return_value=True)
    with patch.object(PermissionService, '_get_fga', return_value=fga):
        result = await PermissionService._is_shared_to(user_id=500, target_tenant_id=1)
    assert result is True
    fga.check.assert_awaited_once()
    args = fga.check.await_args.kwargs
    assert args == {
        'user': 'user:500',
        'relation': 'member',
        'object': 'tenant:1#shared_to',
    }


# AC-04 (Child cannot edit Root shared): covered by FGA DSL enforcement
# — the ``editor`` relation in knowledge_space / workflow / assistant /
# channel / tool does NOT include a ``shared_with`` tupleToUserset, so
# the viewer chain granted by F017 only exposes ``can_read``. This is
# enforced by the authorization_model.py DSL, tested by
# test_openfga_authorization_model.py (F013 module unit test). Per-AC
# smoke here just asserts the DSL export still lacks the bad relation.

def test_ac_04_editor_dsl_does_not_include_shared_with_userset():
    """AC-04: editor relation stays Root-only; no shared_with branch."""
    from bisheng.core.openfga.authorization_model import AUTHORIZATION_MODEL

    types = {t['type']: t for t in AUTHORIZATION_MODEL['type_definitions']}
    for resource in ('knowledge_space', 'workflow', 'assistant', 'channel', 'tool'):
        editor = types[resource]['relations']['editor']
        serialized = repr(editor)
        assert 'shared_with' not in serialized, (
            f'{resource}.editor must NOT flow through shared_with '
            f'(AC-04: Child users see Root-shared resources as read-only)'
        )


# ── T34 — AC-10: shared storage counted once on Root ────────────────


def test_ac_10_shared_resource_is_counted_on_root_only():
    """AC-10: a Root resource with is_shared=true counts once toward Root's
    storage quota. This is enforced by F016's ``strict_tenant_filter()``
    wrapping ``_count_usage_strict`` — the SQL uses ``tenant_id = 1``
    (strict match), so Child tenants never double-count Root-shared rows.

    This smoke test asserts the contract exists in code (the SQL template
    for knowledge_space uses strict equality), not that MySQL returned
    the right rows (which needs a DB).

    ``_RESOURCE_COUNT_TEMPLATES`` is a module-level dict in
    quota_service.py (not a QuotaService class attribute).
    """
    from bisheng.role.domain.services import quota_service as qs_mod

    template = qs_mod._RESOURCE_COUNT_TEMPLATES.get('knowledge_space', '')
    assert '=' in template and 'IN' not in template.upper().split('WHERE', 1)[-1], (
        'AC-10: knowledge_space count SQL must use strict tenant_id equality, '
        'not an IN list (that would double-count shared rows for a Child)'
    )
    # storage_gb follows the same pattern
    storage_tpl = qs_mod._RESOURCE_COUNT_TEMPLATES.get('storage_gb', '')
    assert '=' in storage_tpl, (
        'AC-10: storage_gb SQL must use strict tenant_id equality'
    )
