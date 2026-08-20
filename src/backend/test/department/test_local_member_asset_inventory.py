from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.department.domain.services.local_member_asset_inventory import (
    _extract_scalar_int,
    build_local_member_asset_inventory,
)
from bisheng.tenant.domain.services.resource_ownership_service import ResourceRow


def test_extract_scalar_int_handles_sqlalchemy_row():
    class FakeRow:
        def __init__(self, value):
            self._value = value

        def __getitem__(self, index):
            return self._value

        def __int__(self):
            raise TypeError("not directly convertible")

    assert _extract_scalar_int(FakeRow(828)) == 828
    assert _extract_scalar_int(828) == 828
    assert _extract_scalar_int((828,)) == 828


@pytest.mark.asyncio
async def test_inventory_excludes_personal_knowledge_spaces_from_transfer():
    personal_rows = [
        ResourceRow(resource_type="knowledge_space", id=11, user_id=42, tenant_id=1),
        ResourceRow(resource_type="knowledge_space", id=12, user_id=42, tenant_id=1),
    ]
    team_rows = [
        ResourceRow(resource_type="knowledge_space", id=99, user_id=42, tenant_id=1),
    ]
    folder_in_personal = [
        ResourceRow(resource_type="folder", id=501, user_id=42, tenant_id=1),
    ]
    folder_in_team = [
        ResourceRow(resource_type="folder", id=502, user_id=42, tenant_id=1),
    ]

    async def _resolve_resources(
        tenant_id: int,
        from_user_id: int,
        resource_types: list[str],
        resource_ids=None,
    ):
        resource_type = resource_types[0]
        if resource_type == "knowledge_space":
            return personal_rows + team_rows
        if resource_type == "folder":
            return folder_in_personal + folder_in_team
        return []

    with (
        patch(
            "bisheng.department.domain.services.local_member_asset_inventory._resolve_user_tenant_ids",
            AsyncMock(return_value=[1]),
        ),
        patch(
            "bisheng.department.domain.services.local_member_asset_inventory._find_personal_knowledge_space_ids",
            AsyncMock(return_value={11, 12}),
        ),
        patch(
            "bisheng.department.domain.services.local_member_asset_inventory.ResourceOwnershipService._resolve_resources",
            side_effect=_resolve_resources,
        ),
        patch(
            "bisheng.department.domain.services.local_member_asset_inventory.KnowledgeFileDao.aget_file_by_ids",
            AsyncMock(
                return_value=[
                    SimpleNamespace(id=501, knowledge_id=11),
                    SimpleNamespace(id=502, knowledge_id=99),
                ]
            ),
        ),
        patch(
            "bisheng.department.domain.services.local_member_asset_inventory._count_linsight_assets",
            AsyncMock(return_value={}),
        ),
    ):
        inventory = await build_local_member_asset_inventory(
            user_id=42,
            fallback_tenant_id=1,
            batch_size=500,
        )

    assert inventory.counts["knowledge_space"] == 1
    assert inventory.counts["personal_knowledge_space"] == 2
    assert inventory.counts.get("folder", 0) == 1
    assert inventory.personal_knowledge_space_ids == [11, 12]
    assert inventory.transfer_count == 2
