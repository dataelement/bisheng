"""Shared-only migration: storage failures must not discard source resources."""

from types import SimpleNamespace as N
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.knowledge.domain.repositories.implementations import knowledge_migration_operations_impl as module
from bisheng.knowledge.domain.services.file_migration.executor import MigrationExecutionUnit


async def test_index_stage_validates_shared_contract_without_legacy_copy(monkeypatch):
    projection = N(validate_source=AsyncMock())
    operations = module.KnowledgeMigrationOperationsImpl(shared_projection=projection)
    context = N(unit=N(source_document_id=91), batch=N(tenant_id=1))
    monkeypatch.setattr(operations, "_load_context", AsyncMock(return_value=context))
    await operations.build_target_indexes(MigrationExecutionUnit(unit_id=1))
    projection.validate_source.assert_awaited_once_with(context)


async def test_projection_failure_keeps_source_objects_and_permissions(monkeypatch):
    projection = N(converge_unit=AsyncMock(side_effect=RuntimeError("ES unavailable")))
    operations = module.KnowledgeMigrationOperationsImpl(shared_projection=projection)
    load = AsyncMock()
    cleanup = Mock(side_effect=AssertionError("must retain source objects"))
    monkeypatch.setattr(operations, "_load_context", load)
    monkeypatch.setattr(module, "delete_minio_files", cleanup)
    with pytest.raises(RuntimeError, match="ES unavailable"):
        await operations.cleanup_source_external(MigrationExecutionUnit(unit_id=1))
    load.assert_not_awaited()
    cleanup.assert_not_called()


async def test_preserve_link_cleanup_waits_for_shared_projection():
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import PreserveLinkMigrationOperations

    projection = N(converge_unit=AsyncMock(side_effect=RuntimeError("membership pending")))
    operations = PreserveLinkMigrationOperations(publish_service_factory=None, shared_projection=projection)
    with pytest.raises(RuntimeError, match="membership pending"):
        await operations.cleanup_source_external(MigrationExecutionUnit(unit_id=1))


async def test_lost_migration_lease_prevents_shared_storage_access():
    from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_shared_projection import (
        KnowledgeMigrationSharedProjection,
    )
    from bisheng.knowledge.domain.services.file_migration.executor import StaleMigrationAttemptError

    sessions = Mock(side_effect=AssertionError("must not access storage after lease loss"))
    components = Mock(side_effect=AssertionError("must not initialize shared clients"))
    projection = KnowledgeMigrationSharedProjection(session_factory=sessions, components_factory=components)
    with pytest.raises(StaleMigrationAttemptError):
        await projection.converge_unit(MigrationExecutionUnit(unit_id=1, cancelled=lambda: True))
    sessions.assert_not_called()
    components.assert_not_called()


async def test_shared_route_ignores_obsolete_space_model_fields(monkeypatch):
    from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError, SharedStorageErrorCode
    from bisheng.knowledge.domain.repositories.implementations import knowledge_migration_shared_projection as shared

    route = AsyncMock(return_value=N(embedding_model_id=7))
    monkeypatch.setattr(shared, "aresolve_space_shared_routing", route)
    context = N(
        unit=N(source_document_id=91),
        batch=N(tenant_id=1),
        source_spaces={10: N(type=3, tenant_id=1, model="old-a")},
        target_space=N(type=3, tenant_id=1, model="old-b"),
    )
    adapter = shared.KnowledgeMigrationSharedProjection()
    await adapter.validate_source(context)
    route.assert_awaited_once_with(1, 3)
    route.side_effect = SharedStorageContractError(SharedStorageErrorCode.ROUTING_NOT_CONFIGURED, "missing")
    with pytest.raises(SharedStorageContractError):
        await adapter.validate_source(context)


def test_migration_response_exposes_preserve_link():
    from bisheng.knowledge.domain.models.knowledge_migration import KnowledgeMigrationBatch
    from bisheng.knowledge.domain.services.knowledge_migration_service import KnowledgeMigrationService

    batch = KnowledgeMigrationBatch(
        batch_no="link",
        request_id="link",
        operator_id=1,
        operator_name="admin",
        target_space_id=20,
        target_space_name="target",
        preserve_link=True,
    )
    assert KnowledgeMigrationService._batch_response(batch).preserve_link is True
