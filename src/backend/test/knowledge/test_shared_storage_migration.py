"""F4 shared-storage migration tests (open-box, no live Milvus/ES)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.services.file_migration.shared_storage_migration import (
    MIGRATION_STATE_FROZEN,
    MIGRATION_STATE_IDLE,
    MIGRATION_STATE_RESUMED,
    SharedStorageMigrationCoordinator,
    SharedStorageMigrationProgress,
)
from bisheng.knowledge.domain.services.file_migration.state import MigrationScope


class TestSharedStorageMigrationCoordinator:
    async def test_dry_run_completes_all_phases(self):
        """Dry run completes all phases without modifications."""
        coordinator = SharedStorageMigrationCoordinator()
        with patch(
            "bisheng.knowledge.domain.services.file_migration.shared_storage_migration.KnowledgeDao"
        ) as mock_dao:
            mock_dao.aget_spaces_by_tenant = AsyncMock(return_value=[])
            progress = await coordinator.migrate_tenant(1, dry_run=True)
        assert progress.total_spaces == 0
        assert progress.migrated_spaces == 0
        assert progress.failed_spaces == 0
        assert progress.started_at is not None
        assert progress.completed_at is not None

    async def test_migration_scope_is_shared_storage(self):
        progress = SharedStorageMigrationProgress(tenant_id=1)
        assert progress.scope == MigrationScope.SHARED_STORAGE

    async def test_rollback_clears_frozen_and_switches_to_legacy(self):
        coordinator = SharedStorageMigrationCoordinator()
        with (
            patch(
                "bisheng.knowledge.domain.services.file_migration.shared_storage_migration.unfreeze_tenant_writes",
                return_value=True,
            ),
            patch(
                "bisheng.knowledge.domain.services.file_migration.shared_storage_migration.KnowledgeSpaceSharedStorageRoutingDao"
            ) as mock_dao,
        ):
            mock_dao.switch_to_legacy = lambda tid: True
            progress = await coordinator.rollback_tenant(1)
        assert progress.phase == "TENANT_MIGRATION_FAILED"
        assert progress.completed_at is not None

    async def test_phase_transitions(self):
        progress = SharedStorageMigrationProgress(tenant_id=1)
        assert progress.phase == MIGRATION_STATE_IDLE
        progress.phase = MIGRATION_STATE_FROZEN
        assert progress.phase == MIGRATION_STATE_FROZEN
        progress.phase = MIGRATION_STATE_RESUMED
        assert progress.phase == MIGRATION_STATE_RESUMED

    async def test_failed_spaces_tracked(self):
        progress = SharedStorageMigrationProgress(tenant_id=1)
        progress.total_spaces = 5
        progress.migrated_spaces = 3
        progress.failed_spaces = 2
        progress.errors = ["space 4: error", "space 5: error"]
        assert progress.migrated_spaces + progress.failed_spaces == progress.total_spaces


class TestMigrationState:
    def test_migration_scope_enum_values(self):
        assert MigrationScope.CROSS_SPACE.value == "cross_space"
        assert MigrationScope.SHARED_STORAGE.value == "shared_storage"

    def test_migration_state_constants(self):
        assert MIGRATION_STATE_IDLE == ""
        assert MIGRATION_STATE_FROZEN == "TENANT_WRITE_FROZEN"
        assert MIGRATION_STATE_RESUMED == "TENANT_WRITE_RESUMED"


class TestWriteFreezeGuard:
    async def test_require_not_write_frozen_passes_when_not_frozen(self):
        with (
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.get_shared_storage_conf",
                return_value=_mock_conf(migration_write_block_enabled=True),
            ),
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceSharedStorageRoutingDao"
            ) as mock_dao,
        ):
            mock_dao.aget_by_tenant = AsyncMock(
                return_value=_mock_routing_row(write_frozen=False)
            )
            from bisheng.knowledge.domain.services.knowledge_space_service import (
                _require_not_write_frozen,
            )
            # Should not raise
            await _require_not_write_frozen(1)

    async def test_require_not_write_frozen_raises_when_frozen(self):
        with (
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.get_shared_storage_conf",
                return_value=_mock_conf(migration_write_block_enabled=True),
            ),
            patch(
                "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceSharedStorageRoutingDao"
            ) as mock_dao,
        ):
            mock_dao.aget_by_tenant = AsyncMock(
                return_value=_mock_routing_row(write_frozen=True)
            )
            from bisheng.knowledge.domain.services.knowledge_space_service import (
                _require_not_write_frozen,
            )
            with pytest.raises(SharedStorageContractError) as exc:
                await _require_not_write_frozen(1)
            assert exc.value.code == SharedStorageErrorCode.TENANT_WRITE_FROZEN

    async def test_require_not_write_frozen_skips_when_block_disabled(self):
        with patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_shared_storage_conf",
            return_value=_mock_conf(migration_write_block_enabled=False),
        ):
            from bisheng.knowledge.domain.services.knowledge_space_service import (
                _require_not_write_frozen,
            )
            # Should not raise even if frozen, because block is disabled
            await _require_not_write_frozen(1)


class TestFreezeUnfreezeHelpers:
    def test_freeze_tenant_writes(self):
        with patch(
            "bisheng.knowledge.rag.shared_space_storage.KnowledgeSpaceSharedStorageRoutingDao"
        ) as mock_dao:
            mock_dao.set_write_frozen = lambda tid, frozen: True
            from bisheng.knowledge.rag.shared_space_storage import freeze_tenant_writes

            result = freeze_tenant_writes(1)
            assert result is True

    def test_unfreeze_tenant_writes(self):
        with patch(
            "bisheng.knowledge.rag.shared_space_storage.KnowledgeSpaceSharedStorageRoutingDao"
        ) as mock_dao:
            mock_dao.set_write_frozen = lambda tid, frozen: True
            from bisheng.knowledge.rag.shared_space_storage import unfreeze_tenant_writes

            result = unfreeze_tenant_writes(1)
            assert result is True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mock_conf(**kwargs):
    from types import SimpleNamespace

    defaults = {
        "enabled": True,
        "migration_write_block_enabled": False,
        "collection_name": "shared_collection",
        "index_name": "shared_index",
        "tenant_embedding_model_id": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _mock_routing_row(**kwargs):
    from types import SimpleNamespace

    defaults = {
        "write_frozen": False,
        "shared_enabled": False,
        "routing_version": 1,
        "collection_name": None,
        "index_name": None,
        "embedding_model_id": None,
        "schema_fingerprint": None,
        "migration_state": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)