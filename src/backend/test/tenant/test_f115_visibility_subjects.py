"""F115 AC-23/24/25/27/28/29/37/52: business-owned current subject facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def source(kind, ident, relation=None, children=False):
    return SimpleNamespace(
        subject_type=kind, subject_id=str(ident), userset_relation=relation, include_children=children
    )


async def test_current_directory_filters_inactive_and_keeps_usersets(monkeypatch):
    from bisheng.tenant.domain.services import f048_permission_subject as module

    directory = module.TenantPermissionSubjectDirectory()
    directory._summary_queries = SimpleNamespace(
        load=AsyncMock(
            return_value={
                ("department", "3"): SimpleNamespace(tenant_id=60, name="Dept"),
                ("user_group", "4"): SimpleNamespace(tenant_id=60, group_name="Group"),
            }
        )
    )
    monkeypatch.setattr(
        module,
        "read_current_person_facts",
        AsyncMock(
            return_value={
                1: {"state": "active", "tenant_id": 60, "name": "Owner"},
                2: {"state": "inactive", "tenant_id": None, "name": "Disabled"},
            }
        ),
    )
    rows = await directory.describe_active_sources(
        tenant_id=60,
        sources=(
            source("user", 1),
            source("user", 2),
            source("department", 3, "subtree_member", True),
            source("user_group", 4, "admin"),
            source("service_account", 5),
        ),
    )
    assert [row["type"] for row in rows] == ["user", "department", "user_group"]
    assert rows[-1]["userset_relation"] == "admin"


async def test_ambiguous_person_does_not_mean_empty_authorization(monkeypatch):
    from bisheng.common.errcode.permission import PermissionSubjectUnavailableError
    from bisheng.tenant.domain.services import f048_permission_subject as module

    directory = module.TenantPermissionSubjectDirectory()
    directory._summary_queries = SimpleNamespace(load=AsyncMock(return_value={}))
    monkeypatch.setattr(module, "read_current_person_facts", AsyncMock(return_value={1: {"state": "ambiguous"}}))
    with pytest.raises(PermissionSubjectUnavailableError):
        await directory.describe_active_sources(tenant_id=60, sources=(source("user", 1),))


async def test_unknown_tenant_source_cannot_be_ignored():
    from bisheng.common.errcode.permission import PermissionSubjectUnavailableError
    from bisheng.tenant.domain.services import f048_permission_subject as module

    directory = module.TenantPermissionSubjectDirectory()
    directory._summary_queries = SimpleNamespace(load=AsyncMock(return_value={}))
    with pytest.raises(PermissionSubjectUnavailableError):
        await directory.describe_active_sources(tenant_id=60, sources=(source("tenant", 60),))
