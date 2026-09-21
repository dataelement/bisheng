from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.repositories.implementations import (
    knowledge_migration_operations_impl as operations_module,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_operations_impl import (
    KnowledgeMigrationOperationsImpl,
)
from bisheng.knowledge.domain.services.file_migration.executor import (
    MigrationExecutionUnit,
)


@pytest.mark.asyncio
async def test_target_verification_rejects_incomplete_copied_tags(
    monkeypatch,
):
    source_space = SimpleNamespace(id=10)
    target_space = SimpleNamespace(id=20)
    context = SimpleNamespace(
        batch=SimpleNamespace(tenant_id=1),
        files=(
            SimpleNamespace(
                control=SimpleNamespace(target_resource_manifest={}),
                source=SimpleNamespace(id=100, knowledge_id=10),
                target=SimpleNamespace(
                    id=200,
                    knowledge_id=20,
                    user_id=7,
                    file_level_path="",
                ),
            ),
        ),
        source_spaces={10: source_space},
        target_space=target_space,
        target_owner=SimpleNamespace(user_id=7),
    )
    target_tags = {"approved": [], "pending": []}

    async def load_context(unit_id):
        assert unit_id == 1
        return context

    async def empty_tags(file_id, tenant_id):
        del file_id, tenant_id
        return target_tags

    async def empty_permissions(object_ref):
        del object_ref
        return ()

    operations = KnowledgeMigrationOperationsImpl()
    monkeypatch.setattr(operations, "_load_context", load_context)
    monkeypatch.setattr(operations_module, "_storage_exists", lambda _: {})
    monkeypatch.setattr(operations_module, "_tag_ids", empty_tags)
    monkeypatch.setattr(
        operations_module,
        "_read_permission_tuples",
        empty_permissions,
    )
    monkeypatch.setattr(
        operations_module,
        "_target_permissions",
        lambda *args, **kwargs: (),
    )

    await operations.verify_target(MigrationExecutionUnit(unit_id=1))

    target_tags["approved"] = [8]
    with pytest.raises(
        RuntimeError,
        match="target tags do not match source tags",
    ):
        await operations.verify_target(MigrationExecutionUnit(unit_id=1))
