"""Business-owned F048 migration source-port contracts."""

from __future__ import annotations

from bisheng.api.services.permission_migration_source import (
    ApplicationMigrationRow,
    ApplicationPermissionMigrationSource,
)
from bisheng.channel.domain.services.permission_migration_source import (
    ChannelMigrationRow,
    ChannelPermissionMigrationSource,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.permission_migration_source import (
    KnowledgeMigrationRow,
    KnowledgePermissionMigrationSource,
    _build_file_migration_row,
)
from bisheng.telemetry_search.domain.services.permission_migration_source import (
    DashboardMigrationRow,
    DashboardPermissionMigrationSource,
)
from bisheng.tool.domain.services.permission_migration_source import (
    ToolMigrationRow,
    ToolPermissionMigrationSource,
)


class FakeRepository:
    def __init__(self, rows, next_cursor: str | None = None):
        self.rows = rows
        self.next_cursor = next_cursor
        self.calls = []

    async def aexport_permission_rows(self, *, cursor, limit):
        self.calls.append((cursor, limit))
        return self.rows, self.next_cursor


async def test_knowledge_source_keeps_creator_divergence_and_canonical_parent():
    repository = FakeRepository(
        (
            KnowledgeMigrationRow(
                tenant_id=7,
                resource_type="knowledge_space",
                resource_id="1",
                status="PUBLISHED",
                owner_user_id=11,
                creator_user_ids=(12,),
            ),
            KnowledgeMigrationRow(
                tenant_id=7,
                resource_type="knowledge_file",
                resource_id="2",
                status="SUCCESS",
                owner_user_id=11,
                parent_type="knowledge_space",
                parent_id="1",
            ),
            KnowledgeMigrationRow(
                tenant_id=7,
                resource_type="knowledge_file",
                resource_id="3",
                status="FAILED",
                owner_user_id=11,
                parent_type="folder",
                parent_id="missing",
                migratable=False,
                skip_reason="STALE_FAILED_RESOURCE",
            ),
        ),
        "knowledge:2",
    )

    page = await KnowledgePermissionMigrationSource(repository).aexport(
        cursor=None,
        limit=500,
    )

    assert repository.calls == [(None, 500)]
    assert page.next_cursor == "knowledge:2"
    assert page.items[0].creator_user_ids == (12,)
    assert page.items[0].owner_user_id == 11
    assert page.items[1].parent_type == "knowledge_space"
    assert page.items[1].parent_id == "1"
    assert page.items[2].migratable is False
    assert page.items[2].skip_reason == "STALE_FAILED_RESOURCE"


def test_knowledge_file_source_uses_root_tenant_and_marks_orphan_failed_rows_stale():
    source = KnowledgeFile(
        id=91,
        tenant_id=18,
        user_id=11,
        knowledge_id=7,
        file_name="failed.txt",
        file_type=FileType.FILE.value,
        file_level_path="81/82",
        status=KnowledgeFileStatus.FAILED.value,
    )

    row = _build_file_migration_row(
        source,
        knowledge_type=KnowledgeTypeEnum.NORMAL.value,
        knowledge_tenant_id=13,
        existing_parent_ids={"81"},
    )

    assert row.tenant_id == 13
    assert row.parent_id == "82"
    assert row.migratable is False
    assert row.skip_reason == "STALE_FAILED_RESOURCE"


async def test_channel_source_keeps_creator_and_user_id_as_separate_facts():
    repository = FakeRepository(
        (
            ChannelMigrationRow(
                tenant_id=7,
                resource_id="ch-1",
                status="ACTIVE",
                owner_user_id=11,
                creator_user_ids=(12,),
            ),
        )
    )

    page = await ChannelPermissionMigrationSource(repository).aexport(
        cursor="channel:0",
        limit=20,
    )

    item = page.items[0]
    assert item.resource_type == "channel"
    assert item.owner_user_id == 11
    assert item.creator_user_ids == (12,)
    assert item.ownership_kind == "USER"


async def test_application_source_requires_builtin_and_allowlist_for_system_owner():
    repository = FakeRepository(
        (
            ApplicationMigrationRow(
                tenant_id=7,
                resource_type="workflow",
                resource_id="wf-1",
                status="ONLINE",
                owner_user_id=11,
                builtin=False,
                system_allowlisted=False,
            ),
            ApplicationMigrationRow(
                tenant_id=7,
                resource_type="assistant",
                resource_id="builtin-1",
                status="ONLINE",
                owner_user_id=None,
                builtin=True,
                system_allowlisted=True,
            ),
        )
    )

    page = await ApplicationPermissionMigrationSource(repository).aexport(
        cursor=None,
        limit=50,
    )

    assert [item.ownership_kind for item in page.items] == ["USER", "SYSTEM"]
    assert page.items[1].system_allowlisted is True


async def test_tool_and_dashboard_sources_use_double_system_predicate():
    tool_repository = FakeRepository(
        (
            ToolMigrationRow(
                tenant_id=7,
                resource_id="9",
                status="ACTIVE",
                owner_user_id=None,
                preset=True,
                system_allowlisted=True,
            ),
        )
    )
    dashboard_repository = FakeRepository(
        (
            DashboardMigrationRow(
                tenant_id=7,
                resource_id="3",
                status="published",
                owner_user_id=None,
                dashboard_type="preset_oss",
                system_allowlisted=True,
            ),
            DashboardMigrationRow(
                tenant_id=7,
                resource_id="4",
                status="draft",
                owner_user_id=11,
                dashboard_type="custom",
                system_allowlisted=False,
            ),
        )
    )

    tool_page = await ToolPermissionMigrationSource(tool_repository).aexport(
        cursor=None,
        limit=50,
    )
    dashboard_page = await DashboardPermissionMigrationSource(dashboard_repository).aexport(cursor=None, limit=50)

    assert tool_page.items[0].ownership_kind == "SYSTEM"
    assert [item.ownership_kind for item in dashboard_page.items] == [
        "SYSTEM",
        "USER",
    ]
    assert dashboard_page.items[1].owner_user_id == 11


async def test_invalid_system_predicate_is_exported_as_user_fact_for_inventory_blocking():
    repository = FakeRepository(
        (
            ToolMigrationRow(
                tenant_id=7,
                resource_id="9",
                status="ACTIVE",
                owner_user_id=None,
                preset=True,
                system_allowlisted=False,
            ),
        )
    )

    page = await ToolPermissionMigrationSource(repository).aexport(
        cursor=None,
        limit=50,
    )

    assert page.items[0].ownership_kind == "USER"
    assert page.items[0].owner_user_id is None
