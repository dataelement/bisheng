"""F018 T03: ResourceOwnershipService tests.

Covers spec AC-01/03/04/05/06/07/08/08b/08c/08d + AD-02/AD-03.

Strategy:
  - SQL paths (_resolve_resources, _bulk_update_user_ids, list_pending_transfer)
    use real SQLite via ``async_db_session`` + factory-inserted rows so the
    bindparam/text() SQL is genuinely exercised. Patching the async session
    factory redirects the service to the test engine.
  - FGA (PermissionService.batch_write_tuples) + AuditLogDao.ainsert_v2 are
    AsyncMock'd — they already have dedicated unit tests in F004/F011.
  - UserTenantDao.aget_active_user_tenant is AsyncMock'd per test to
    control the receiver's leaf-tenant value (AC-08 branches).
"""

from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferBatchLimitError,
    ResourceTransferPermissionError,
    ResourceTransferReceiverOutOfTenantError,
    ResourceTransferSelfError,
    ResourceTransferTxFailedError,
    ResourceTransferUnsupportedTypeError,
)
from bisheng.tenant.domain.services.resource_ownership_service import (
    MAX_BATCH,
    ResourceOwnershipService,
    ResourceRow,
)

SERVICE_MOD = 'bisheng.tenant.domain.services.resource_ownership_service'
ROOT_TENANT_ID = 1


# ---------------------------------------------------------------------------
# Operator test doubles
# ---------------------------------------------------------------------------

def _mk_user(user_id: int, *, is_admin: bool = False, is_super: bool = False,
             tenant_id: int = 2, leaf_tenant_id: int | None = None):
    u = MagicMock()
    u.user_id = user_id
    u.tenant_id = tenant_id
    u.leaf_tenant_id = leaf_tenant_id or tenant_id
    u.is_admin = MagicMock(return_value=is_admin)
    u.is_global_super = MagicMock(return_value=is_super)
    u.admin_scope_tenant_id = None
    return u


@pytest.fixture()
def from_user():
    return _mk_user(user_id=100, tenant_id=2)


@pytest.fixture()
def to_user_same_tenant():
    return _mk_user(user_id=200, tenant_id=2)


@pytest.fixture()
def tenant_admin():
    return _mk_user(user_id=10, is_admin=True, tenant_id=2)


@pytest.fixture()
def global_super():
    return _mk_user(user_id=1, is_super=True, tenant_id=ROOT_TENANT_ID)


# ---------------------------------------------------------------------------
# Helpers: session redirection (SQL-heavy paths) + leaf resolver patching
# ---------------------------------------------------------------------------

@pytest.fixture()
async def sqlite_session(async_db_session):
    """Yield an async SQLite session with a redirected ``get_async_db_session``
    context manager so the service writes into the test engine."""

    @asynccontextmanager
    async def fake_factory():
        yield async_db_session

    with patch(f'{SERVICE_MOD}.get_async_db_session', fake_factory):
        yield async_db_session


@pytest.fixture()
def patch_leaf_resolver():
    """Patch ``UserTenantDao.aget_active_user_tenant`` to return a leaf id."""

    def _patch(user_to_leaf: dict[int, int]):
        def side_effect(user_id: int):
            leaf = user_to_leaf.get(user_id)
            if leaf is None:
                return None
            rec = MagicMock()
            rec.tenant_id = leaf
            return rec

        return patch(
            f'{SERVICE_MOD}.UserTenantDao.aget_active_user_tenant',
            new_callable=AsyncMock, side_effect=side_effect,
        )

    return _patch


@pytest.fixture()
def patch_fga():
    """Patch PermissionService.batch_write_tuples — captures ops for assertions."""
    with patch(
        f'{SERVICE_MOD}.PermissionService.batch_write_tuples',
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture()
def patch_audit():
    with patch(
        f'{SERVICE_MOD}.AuditLogDao.ainsert_v2', new_callable=AsyncMock,
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# Data setup helpers (raw SQL; F000 factories don't cover these 7 tables yet)
# ---------------------------------------------------------------------------

async def _seed_workflow(session, flow_id: str, user_id: int, tenant_id: int):
    await session.execute(
        __import__('sqlalchemy').text(
            "INSERT INTO flow (id, name, user_id, tenant_id, flow_type) "
            "VALUES (:id, :name, :uid, :tid, 10)"
        ),
        {'id': flow_id, 'name': f'wf-{flow_id}', 'uid': user_id, 'tid': tenant_id},
    )


async def _seed_knowledge_space(session, kid: int, user_id: int, tenant_id: int):
    await session.execute(
        __import__('sqlalchemy').text(
            "INSERT INTO knowledge (id, name, user_id, tenant_id, type) "
            "VALUES (:id, :name, :uid, :tid, 3)"
        ),
        {'id': kid, 'name': f'ks-{kid}', 'uid': user_id, 'tid': tenant_id},
    )


async def _seed_assistant(session, aid: str, user_id: int, tenant_id: int):
    await session.execute(
        __import__('sqlalchemy').text(
            "INSERT INTO assistant (id, name, user_id, tenant_id) "
            "VALUES (:id, :name, :uid, :tid)"
        ),
        {'id': aid, 'name': f'as-{aid}', 'uid': user_id, 'tid': tenant_id},
    )


# =========================================================================
# AC-03 / AC-08 / AC-08b / AC-08c / AC-08d / AD-03: validations
# =========================================================================

@pytest.mark.asyncio
class TestValidations:

    async def test_self_transfer_rejected_19606(self, from_user):
        with pytest.raises(ResourceTransferSelfError) as exc:
            await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=100,
                resource_types=['workflow'], operator=from_user,
            )
        assert exc.value.Code == 19606

    async def test_unsupported_type_rejected_19604(self, from_user):
        with pytest.raises(ResourceTransferUnsupportedTypeError) as exc:
            await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['dashboard'],  # dropped from MVP
                operator=from_user,
            )
        assert exc.value.Code == 19604

    async def test_non_owner_non_admin_rejected_19601(self, patch_leaf_resolver):
        """AC-03: a random user transferring someone else's resources → 403."""
        intruder = _mk_user(user_id=999, tenant_id=2)
        with patch_leaf_resolver({200: 2}):
            with pytest.raises(ResourceTransferPermissionError) as exc:
                await ResourceOwnershipService.transfer_owner(
                    tenant_id=2, from_user_id=100, to_user_id=200,
                    resource_types=['workflow'], operator=intruder,
                )
        assert exc.value.Code == 19601

    async def test_receiver_cross_child_rejected_19603(self, from_user, patch_leaf_resolver):
        """AC-08c: tenant_id = ChildA, to_user leaf = ChildB → 19603."""
        with patch_leaf_resolver({200: 3}):  # to_user in Child 3, tenant_id=2
            with pytest.raises(ResourceTransferReceiverOutOfTenantError) as exc:
                await ResourceOwnershipService.transfer_owner(
                    tenant_id=2, from_user_id=100, to_user_id=200,
                    resource_types=['workflow'], operator=from_user,
                )
        assert exc.value.Code == 19603

    async def test_receiver_root_to_child_rejected_19603(
        self, global_super, patch_leaf_resolver,
    ):
        """AC-08d: tenant_id = Root, to_user leaf = Child → 19603.

        Hint that the caller should use F011 migrate-from-root lives in
        the error ``Msg`` + spec §3; we assert only the code here.
        """
        with patch_leaf_resolver({200: 5}):
            with pytest.raises(ResourceTransferReceiverOutOfTenantError):
                await ResourceOwnershipService.transfer_owner(
                    tenant_id=ROOT_TENANT_ID, from_user_id=100, to_user_id=200,
                    resource_types=['workflow'], operator=global_super,
                )

    async def test_receiver_child_to_root_allowed(
        self, tenant_admin, patch_leaf_resolver, sqlite_session,
        patch_fga, patch_audit,
    ):
        """AC-08b: typical 'hand back to HQ' — no rows → 0 transferred, no raise."""
        with patch_leaf_resolver({200: ROOT_TENANT_ID}):
            result = await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['workflow'], operator=tenant_admin,
            )
        assert result['transferred_count'] == 0
        patch_fga.assert_not_called()
        patch_audit.assert_not_called()


# =========================================================================
# AC-04 / AC-05 / AC-07: resource resolution and batch limit
# =========================================================================

@pytest.mark.asyncio
class TestResolutionAndBatchLimit:

    async def test_batch_over_500_rejected_19602(
        self, tenant_admin, patch_leaf_resolver, sqlite_session,
    ):
        """AD-02: MAX_BATCH=500 cap enforced after resolution."""
        # Seed 501 workflow rows owned by from_user.
        for i in range(MAX_BATCH + 1):
            await _seed_workflow(sqlite_session, f'wf-{i}', 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            with pytest.raises(ResourceTransferBatchLimitError) as exc:
                await ResourceOwnershipService.transfer_owner(
                    tenant_id=2, from_user_id=100, to_user_id=200,
                    resource_types=['workflow'], operator=tenant_admin,
                )
        assert exc.value.Code == 19602

    async def test_resource_ids_null_selects_all_from_user(
        self, tenant_admin, patch_leaf_resolver, sqlite_session,
        patch_fga, patch_audit,
    ):
        """AC-04: resource_ids=None → transfer every matching row."""
        for fid in ('wf-a', 'wf-b', 'wf-c'):
            await _seed_workflow(sqlite_session, fid, 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            result = await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['workflow'], operator=tenant_admin,
            )

        assert result['transferred_count'] == 3
        assert result['transfer_log_id'] is not None

    async def test_resource_ids_list_filters_to_named(
        self, tenant_admin, patch_leaf_resolver, sqlite_session,
        patch_fga, patch_audit,
    ):
        """AC-05: explicit id list transfers only the named resources."""
        for fid in ('wf-a', 'wf-b', 'wf-c'):
            await _seed_workflow(sqlite_session, fid, 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            result = await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['workflow'], resource_ids=['wf-a', 'wf-c'],
                operator=tenant_admin,
            )

        assert result['transferred_count'] == 2

    async def test_mixed_types_grouped_by_type(
        self, tenant_admin, patch_leaf_resolver, sqlite_session,
        patch_fga, patch_audit,
    ):
        """2 workflows + 1 knowledge_space = 3 transferred across 2 tables."""
        await _seed_workflow(sqlite_session, 'wf-a', 100, 2)
        await _seed_workflow(sqlite_session, 'wf-b', 100, 2)
        await _seed_knowledge_space(sqlite_session, 1, 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            result = await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['workflow', 'knowledge_space'],
                operator=tenant_admin,
            )

        assert result['transferred_count'] == 3
        # Audit metadata captures the per-type id groupings.
        audit_kwargs = patch_audit.call_args.kwargs
        assert set(audit_kwargs['metadata']['resource_types']) == {
            'workflow', 'knowledge_space',
        }


# =========================================================================
# AC-01 / AC-06: happy path and FGA failure rollback
# =========================================================================

@pytest.mark.asyncio
class TestHappyAndRollback:

    async def test_happy_path_updates_mysql_fga_audit(
        self, from_user, patch_leaf_resolver, sqlite_session,
        patch_fga, patch_audit,
    ):
        """AC-01: owner-self transfer flips user_id, writes FGA tuples, audit."""
        await _seed_workflow(sqlite_session, 'wf-1', 100, 2)
        await _seed_assistant(sqlite_session, 'as-1', 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            result = await ResourceOwnershipService.transfer_owner(
                tenant_id=2, from_user_id=100, to_user_id=200,
                resource_types=['workflow', 'assistant'],
                reason='离职交接', operator=from_user,
            )

        assert result['transferred_count'] == 2

        # MySQL user_id flipped for both rows.
        from sqlalchemy import text as sql_text
        new_wf = (await sqlite_session.execute(
            sql_text('SELECT user_id FROM flow WHERE id=:id'),
            {'id': 'wf-1'},
        )).scalar_one()
        new_as = (await sqlite_session.execute(
            sql_text('SELECT user_id FROM assistant WHERE id=:id'),
            {'id': 'as-1'},
        )).scalar_one()
        assert new_wf == 200
        assert new_as == 200

        # FGA got 2 deletes + 2 writes (one pair per resource).
        patch_fga.assert_awaited_once()
        ops = patch_fga.call_args.args[0]
        assert len(ops) == 4
        deletes = [o for o in ops if o.action == 'delete']
        writes = [o for o in ops if o.action == 'write']
        assert len(deletes) == 2
        assert len(writes) == 2
        assert all(o.user == 'user:100' for o in deletes)
        assert all(o.user == 'user:200' for o in writes)
        assert {o.object for o in ops} == {
            'workflow:wf-1', 'assistant:as-1',
        }

        # audit_log was written once with the transfer action and reason.
        patch_audit.assert_awaited_once()
        kwargs = patch_audit.call_args.kwargs
        assert kwargs['action'] == 'resource.transfer_owner'
        assert kwargs['reason'] == '离职交接'
        assert kwargs['metadata']['count'] == 2

    async def test_fga_failure_rolls_back_and_raises_19605(
        self, from_user, patch_leaf_resolver, sqlite_session, patch_audit,
    ):
        """AC-06: FGA raises → ResourceTransferTxFailedError. Audit not written
        because the transaction raised before reaching the audit step.

        Note: this test relies on FailedTuple pre-recording (crash_safe=True)
        to cover compensation — exercised in F004's own test suite; here we
        just verify the service surfaces the 19605 wrapper and skips audit.
        """
        await _seed_workflow(sqlite_session, 'wf-1', 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}), patch(
            f'{SERVICE_MOD}.PermissionService.batch_write_tuples',
            new_callable=AsyncMock, side_effect=RuntimeError('OpenFGA down'),
        ):
            with pytest.raises(ResourceTransferTxFailedError) as exc:
                await ResourceOwnershipService.transfer_owner(
                    tenant_id=2, from_user_id=100, to_user_id=200,
                    resource_types=['workflow'], operator=from_user,
                )
        assert exc.value.Code == 19605
        patch_audit.assert_not_awaited()


# =========================================================================
# AC-10: list_pending_transfer
# =========================================================================

@pytest.mark.asyncio
class TestPendingTransfer:

    async def test_pending_includes_users_whose_leaf_moved(
        self, sqlite_session, patch_leaf_resolver,
    ):
        """User 100 has 2 wf in tenant=2 but their leaf is now tenant=5 → listed."""
        await _seed_workflow(sqlite_session, 'wf-a', 100, 2)
        await _seed_workflow(sqlite_session, 'wf-b', 100, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({100: 5}):
            items = await ResourceOwnershipService.list_pending_transfer(
                tenant_id=2,
            )

        assert len(items) == 1
        assert items[0]['user_id'] == 100
        assert items[0]['resource_count'] == 2
        assert items[0]['current_leaf_tenant_id'] == 5

    async def test_pending_excludes_users_still_in_tenant(
        self, sqlite_session, patch_leaf_resolver,
    ):
        """User 200 still has leaf = tenant_id → filtered out of pending list."""
        await _seed_workflow(sqlite_session, 'wf-x', 200, 2)
        await sqlite_session.commit()

        with patch_leaf_resolver({200: 2}):
            items = await ResourceOwnershipService.list_pending_transfer(
                tenant_id=2,
            )

        assert items == []


# =========================================================================
# Minor invariants
# =========================================================================

def test_max_batch_is_500():
    """Spec AD-02 — regression guard."""
    assert MAX_BATCH == 500


def test_resource_row_is_frozen():
    """ResourceRow should be immutable to avoid accidental mutation."""
    row = ResourceRow(resource_type='workflow', id='x', user_id=1, tenant_id=2)
    with pytest.raises(Exception):
        row.id = 'y'  # type: ignore[misc]
