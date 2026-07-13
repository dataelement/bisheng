"""Regression: sync_information_article must run under per-tenant context.

The information-source tables (channel_info_source / channel / ...) are
tenant-aware. Celery Beat fires the task with no request context, so the task
body must iterate every active tenant and set its context before querying —
otherwise the first SELECT raises NoTenantContextError and nothing syncs on a
multi-tenant deploy. Mirrors test_information_reconcile_worker.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bisheng.worker.information.article as article_mod


def test_sync_iterates_each_active_tenant_under_context():
    """Each active tenant's context is set and the per-tenant sync runs once."""
    tenant_seen: list[int] = []
    synced_under: list[int] = []

    with (
        patch.object(article_mod, "_active_tenant_ids_sync", return_value=[1, 2, 3]),
        patch.object(article_mod, "set_current_tenant_id", side_effect=lambda t: tenant_seen.append(t) or f"tok-{t}"),
        patch.object(article_mod, "current_tenant_id", MagicMock()),
        patch.object(
            article_mod,
            "_sync_information_article_for_tenant",
            side_effect=lambda info: synced_under.append(tenant_seen[-1]),
        ),
    ):
        article_mod.sync_information_article.run()

    assert tenant_seen == [1, 2, 3]
    assert synced_under == [1, 2, 3]


def test_sync_isolates_per_tenant_failure_and_resets_context():
    """One tenant failing does not stop the rest; context is reset every time."""
    tenant_seen: list[int] = []
    reset_tokens: list = []

    ctx_mock = MagicMock()
    ctx_mock.reset.side_effect = lambda tok: reset_tokens.append(tok)

    def _body(info):
        if tenant_seen[-1] == 2:
            raise RuntimeError("boom")

    with (
        patch.object(article_mod, "_active_tenant_ids_sync", return_value=[1, 2, 3]),
        patch.object(article_mod, "set_current_tenant_id", side_effect=lambda t: tenant_seen.append(t) or f"tok-{t}"),
        patch.object(article_mod, "current_tenant_id", ctx_mock),
        patch.object(article_mod, "_sync_information_article_for_tenant", side_effect=_body),
    ):
        article_mod.sync_information_article.run()

    assert tenant_seen == [1, 2, 3]
    # finally-block reset fires once per tenant, even for the one that raised.
    assert reset_tokens == ["tok-1", "tok-2", "tok-3"]


def test_active_tenant_ids_single_tenant_fallback():
    """Single-tenant deploy syncs only the default tenant."""
    fake_settings = SimpleNamespace(multi_tenant=SimpleNamespace(enabled=False))
    with patch("bisheng.common.services.config_service.settings", fake_settings):
        assert article_mod._active_tenant_ids_sync() == [article_mod.DEFAULT_TENANT_ID]


def test_active_tenant_ids_multi_tenant_includes_root_and_children():
    """Multi-tenant deploy syncs root + every active child tenant."""
    fake_settings = SimpleNamespace(multi_tenant=SimpleNamespace(enabled=True))
    with (
        patch("bisheng.common.services.config_service.settings", fake_settings),
        patch("bisheng.database.models.tenant.TenantDao.get_children_ids_active", return_value=[2, 3]),
    ):
        assert article_mod._active_tenant_ids_sync() == [1, 2, 3]
