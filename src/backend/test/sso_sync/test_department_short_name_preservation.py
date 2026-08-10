from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.database.models.department import Department, DepartmentDao
from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService


async def test_legacy_org_sync_rename_preserves_local_short_name() -> None:
    department = SimpleNamespace(
        id=10,
        name="旧名称",
        short_name="本地简称",
        source="local",
    )
    operation = SimpleNamespace(
        local=department,
        new_name="上游新名称",
        change_source=True,
    )
    config = SimpleNamespace(provider="wecom")

    with patch.object(DepartmentDao, "aupdate", new_callable=AsyncMock) as update:
        await OrgSyncService._update_dept(operation, config)

    assert department.name == "上游新名称"
    assert department.short_name == "本地简称"
    update.assert_awaited_once_with(department)


async def test_realtime_upsert_rename_preserves_local_short_name() -> None:
    department = Department(
        id=10,
        dept_id="WECOM@d-10",
        name="旧名称",
        short_name="本地简称",
        parent_id=1,
        tenant_id=1,
        path="/1/10/",
        sort_order=0,
        source="wecom",
        external_id="d-10",
        status="active",
    )

    class _Session:
        async def exec(self, statement):
            params = statement.compile().params
            for field in (
                "name",
                "parent_id",
                "path",
                "sort_order",
                "status",
                "is_deleted",
                "last_sync_ts",
                "sync_parent_external_id",
            ):
                if field in params:
                    setattr(department, field, params[field])

        async def commit(self):
            return None

    @asynccontextmanager
    async def _session_context():
        yield _Session()

    with (
        patch.object(
            DepartmentDao,
            "aget_by_source_external_id",
            new_callable=AsyncMock,
            return_value=department,
        ),
        patch.object(
            DepartmentDao,
            "aget_by_id",
            new_callable=AsyncMock,
            return_value=department,
        ),
        patch(
            "bisheng.database.models.department.get_async_db_session",
            _session_context,
        ),
    ):
        updated = await DepartmentDao.aupsert_by_external_id(
            source="wecom",
            external_id="d-10",
            name="上游新名称",
            parent_id=1,
            path="/1/",
            sort_order=1,
            last_sync_ts=100,
            tenant_id=1,
        )

    assert updated.name == "上游新名称"
    assert updated.short_name == "本地简称"
