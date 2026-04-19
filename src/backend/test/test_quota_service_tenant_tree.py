"""Unit tests for F016 T03 — tenant-tree quota counting helpers.

Covers AC-02 (strict equality prevents shared-resource leakage), AC-07 (Root
usage aggregation), AC-09 (strict_tenant_filter wrapping).

Uses mock/patch to avoid DB + celery dependencies (matches test_quota_service.py
baseline style).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCountUsageStrict:
    """AC-02, AC-09: strict_tenant_filter defensive wrapping."""

    @pytest.mark.asyncio
    async def test_count_usage_strict_wraps_in_strict_filter(self):
        """Verify _count_usage_strict enters strict_tenant_filter context manager."""
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch('bisheng.core.context.tenant.strict_tenant_filter') as mock_cm, \
             patch.object(QuotaService, 'get_tenant_resource_count', new=AsyncMock(return_value=42)):
            # strict_tenant_filter returns a context manager; simulate one.
            mock_cm.return_value.__enter__ = MagicMock()
            mock_cm.return_value.__exit__ = MagicMock()
            result = await QuotaService._count_usage_strict(5, 'knowledge_space')

        assert result == 42
        mock_cm.assert_called_once()
        mock_cm.return_value.__enter__.assert_called_once()
        mock_cm.return_value.__exit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_usage_strict_returns_zero_on_missing_template(self):
        """Resource type with no SQL template + strict_filter enabled → 0 (stub-safe).

        ``_count_resource`` returns 0 early when the template map lookup misses,
        so no DB session is opened and no patching is needed.
        """
        from bisheng.role.domain.services.quota_service import QuotaService

        result = await QuotaService._count_usage_strict(5, 'nonexistent_type')
        assert result == 0


class TestAggregateRootUsage:
    """AC-07: Root usage = Root self + Σ active Child (INV-T9)."""

    @pytest.mark.asyncio
    async def test_aggregate_root_with_no_children_returns_self(self):
        """Root with zero active children → root_self count only."""
        from bisheng.role.domain.services.quota_service import QuotaService

        with patch.object(QuotaService, '_count_usage_strict', new=AsyncMock(return_value=7)) as mock_count, \
             patch('bisheng.database.models.tenant.TenantDao.aget_children_ids_active',
                   new=AsyncMock(return_value=[])):
            result = await QuotaService._aggregate_root_usage(1, 'knowledge_space')

        assert result == 7
        # Only one call: for root itself.
        mock_count.assert_awaited_once_with(1, 'knowledge_space')

    @pytest.mark.asyncio
    async def test_aggregate_root_sums_self_plus_active_children(self):
        """AC-07 scenario: Child A=30, Child B=50, Root=20 → Root total=100."""
        from bisheng.role.domain.services.quota_service import QuotaService

        # _count_usage_strict returns: Root(id=1)=20, Child(5)=30, Child(6)=50
        per_tenant_counts = {1: 20, 5: 30, 6: 50}

        async def fake_count(tid, rt):
            return per_tenant_counts[tid]

        with patch.object(QuotaService, '_count_usage_strict', new=AsyncMock(side_effect=fake_count)) as mock_count, \
             patch('bisheng.database.models.tenant.TenantDao.aget_children_ids_active',
                   new=AsyncMock(return_value=[5, 6])):
            result = await QuotaService._aggregate_root_usage(1, 'knowledge_space')

        assert result == 100
        # Root self (1) + 2 children (5, 6) = 3 calls total.
        assert mock_count.await_count == 3

    @pytest.mark.asyncio
    async def test_aggregate_root_excludes_archived_children(self):
        """aget_children_ids_active(root_id) only returns status='active' ids.

        This test verifies the contract — F011's DAO is the source of truth
        for filtering. If DAO returns [5] excluding archived Child 7, the sum
        does not include Child 7's usage.
        """
        from bisheng.role.domain.services.quota_service import QuotaService

        per_tenant_counts = {1: 10, 5: 30, 7: 99}  # tenant 7 is archived

        async def fake_count(tid, rt):
            return per_tenant_counts[tid]

        # DAO returns only active children → [5]; archived Child 7 excluded.
        with patch.object(QuotaService, '_count_usage_strict', new=AsyncMock(side_effect=fake_count)), \
             patch('bisheng.database.models.tenant.TenantDao.aget_children_ids_active',
                   new=AsyncMock(return_value=[5])):
            result = await QuotaService._aggregate_root_usage(1, 'knowledge_space')

        # 10 (Root) + 30 (Child 5) = 40; Child 7's 99 excluded.
        assert result == 40
