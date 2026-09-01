"""Root's stored config must survive a narrowed tenant filter.

Every ``SELECT`` goes through the tenant auto-filter, which narrows by the
request's visible-tenant set. When that set does not contain Root, Root's own
``tenant_workstation_config`` row reads back as missing — indistinguishable from
"this deployment has never saved a config". Treating that as "no config" is
destructive: ``get_daily_chat_config_with_meta`` fabricates built-in defaults
from it, and the 工作台配置 page round-trips whatever it was shown, so the next
保存 replaces the real config (welcome message, icons, org KBs, tool pool) with
defaults. That is exactly what happened on 2026-08-13.

``aresolve`` / ``resolve`` therefore re-read unfiltered before concluding that
Root has no config, and the service reports ``is_fallback`` so callers can tell a
fabricated default from a saved config.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.workstation.domain.models.tenant_workstation_config import (
    TenantWorkstationConfigDao,
)

ROOT = 1
CHILD = 36
KEY = "workstation"
STORED = '{"welcomeMessage": "\\u6211\\u662f BISHENG"}'


def _filtered_reader(visible: set[int] | None):
    """Stand-in for ``aget``/``get`` under a tenant filter.

    Rows exist only for Root. ``visible`` is the request's visible-tenant set:
    a read is served only when the filter is bypassed or Root is visible —
    mirroring how the real listener rewrites the statement.
    """

    def read(tenant_id: int, key: str):
        if tenant_id != ROOT or key != KEY:
            return None
        if is_tenant_filter_bypassed() or visible is None or ROOT in visible:
            return SimpleNamespace(tenant_id=ROOT, key=key, value=STORED)
        return None

    return read


@pytest.mark.parametrize("visible", [None, {ROOT}, {CHILD}, set()])
async def test_aresolve_returns_root_config_whatever_the_visible_set(monkeypatch, visible):
    reader = _filtered_reader(visible)
    monkeypatch.setattr(
        TenantWorkstationConfigDao,
        "aget",
        classmethod(lambda cls, tenant_id, key: _async(reader(tenant_id, key))),
    )

    value, inherited, source_tenant_id, has_override = await TenantWorkstationConfigDao.aresolve(ROOT, KEY)

    assert value == STORED, "Root's saved config must not read back as absent"
    assert inherited is False
    assert source_tenant_id == ROOT
    assert has_override is True


@pytest.mark.parametrize("visible", [None, {ROOT}, {CHILD}, set()])
def test_resolve_sync_matches_async(monkeypatch, visible):
    reader = _filtered_reader(visible)
    monkeypatch.setattr(
        TenantWorkstationConfigDao, "get", classmethod(lambda cls, tenant_id, key: reader(tenant_id, key))
    )

    assert TenantWorkstationConfigDao.resolve(ROOT, KEY) == (STORED, False, ROOT, True)


async def test_aresolve_reports_no_config_when_root_row_really_is_absent(monkeypatch):
    """The fallback path stays intact for a genuinely fresh deployment."""
    monkeypatch.setattr(
        TenantWorkstationConfigDao,
        "aget",
        classmethod(lambda cls, tenant_id, key: _async(None)),
    )

    assert await TenantWorkstationConfigDao.aresolve(ROOT, KEY) == (None, False, ROOT, False)


async def test_child_tenant_still_inherits_from_root(monkeypatch):
    """A Child with no override keeps reading Root's config, marked inherited."""
    reader = _filtered_reader({CHILD, ROOT})
    monkeypatch.setattr(
        TenantWorkstationConfigDao,
        "aget",
        classmethod(lambda cls, tenant_id, key: _async(reader(tenant_id, key) if tenant_id == ROOT else None)),
    )

    value, inherited, source_tenant_id, has_override = await TenantWorkstationConfigDao.aresolve(CHILD, KEY)

    assert value == STORED
    assert inherited is True
    assert source_tenant_id == ROOT
    assert has_override is False


async def _async(value):
    return value
