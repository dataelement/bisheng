"""对账与 sync outbox drain。"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.points.domain.services.points_reconcile_service import PointsReconcileService
from bisheng.points.domain.services.points_sync_outbox_service import PointsSyncOutboxService


@pytest.mark.asyncio
async def test_reconcile_reports_mismatch_without_mutating():
    service = PointsReconcileService()
    accounts = [SimpleNamespace(user_id=1, balance=10), SimpleNamespace(user_id=2, balance=5)]

    class _Repo:
        async def list_accounts(self, _tenant_id):
            return accounts

        async def sum_lifetime_deltas_by_user(self, _tenant_id):
            return {1: 10, 2: 9}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    with (
        patch(
            "bisheng.points.domain.services.points_reconcile_service.get_async_db_session",
            return_value=_Session(),
        ),
        patch(
            "bisheng.points.domain.services.points_reconcile_service.PointsRepository",
            return_value=_Repo(),
        ),
    ):
        out = await service.reconcile_tenant(1)

    assert out["checked"] == 2
    assert out["mismatches"] == 1
    assert out["details"][0]["user_id"] == 2
    assert out["details"][0]["ledger_sum"] == 9


@pytest.mark.asyncio
async def test_outbox_drain_keeps_pending_when_disabled():
    service = PointsSyncOutboxService()
    fake_settings = SimpleNamespace(points=SimpleNamespace(sync_outbox_enabled=False))
    with patch("bisheng.common.services.config_service.settings", fake_settings):
        out = await service.drain()
    assert out["skipped"] is True
    assert out["reason"] == "sync_outbox_disabled"


@pytest.mark.asyncio
async def test_outbox_drain_marks_skipped_without_adapter():
    row = SimpleNamespace(
        id=1,
        status="pending",
        retry_count=0,
        next_retry_at=None,
        last_error=None,
        sent_at=None,
        payload={"log_id": 1},
    )

    class _Repo:
        async def list_due_sync_outbox(self, *, limit=100, now=None):
            return [row]

        async def save_outbox(self, item):
            return item

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def commit(self):
            return None

    @contextmanager
    def _bypass():
        yield None

    fake_settings = SimpleNamespace(points=SimpleNamespace(sync_outbox_enabled=True))
    service = PointsSyncOutboxService()
    with (
        patch("bisheng.common.services.config_service.settings", fake_settings),
        patch("bisheng.core.context.tenant.bypass_tenant_filter", _bypass),
        patch(
            "bisheng.points.domain.services.points_sync_outbox_service.get_async_db_session",
            return_value=_Session(),
        ),
        patch(
            "bisheng.points.domain.services.points_sync_outbox_service.PointsRepository",
            return_value=_Repo(),
        ),
    ):
        out = await service.drain()

    assert out["processed"] == 1
    assert out["skipped"] == 1
    assert row.status == "skipped"


@pytest.mark.asyncio
async def test_outbox_deliver_success_marks_sent():
    row = SimpleNamespace(
        id=2,
        status="pending",
        retry_count=0,
        next_retry_at=None,
        last_error=None,
        sent_at=None,
        payload={"log_id": 2},
    )

    class _Repo:
        async def list_due_sync_outbox(self, *, limit=100, now=None):
            return [row]

        async def save_outbox(self, item):
            return item

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def commit(self):
            return None

    @contextmanager
    def _bypass():
        yield None

    async def ok_deliver(_row):
        return True

    fake_settings = SimpleNamespace(points=SimpleNamespace(sync_outbox_enabled=True))
    service = PointsSyncOutboxService(deliver=ok_deliver)
    with (
        patch("bisheng.common.services.config_service.settings", fake_settings),
        patch("bisheng.core.context.tenant.bypass_tenant_filter", _bypass),
        patch(
            "bisheng.points.domain.services.points_sync_outbox_service.get_async_db_session",
            return_value=_Session(),
        ),
        patch(
            "bisheng.points.domain.services.points_sync_outbox_service.PointsRepository",
            return_value=_Repo(),
        ),
    ):
        out = await service.drain()

    assert out["sent"] == 1
    assert row.status == "sent"
    assert row.sent_at is not None
