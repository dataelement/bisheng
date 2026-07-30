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
async def test_target_index_verification_uses_copied_milvus_chunks(
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
    target_counts = {"milvus": 2, "elasticsearch": 2}

    async def load_context(unit_id):
        assert unit_id == 1
        return context

    async def index_counts(space, file_id):
        if space is source_space:
            assert file_id == 100
            return {"milvus": 2, "elasticsearch": 1}
        assert space is target_space
        assert file_id == 200
        return target_counts

    async def empty_tags(file_id, tenant_id):
        del file_id, tenant_id
        return {"approved": [], "pending": []}

    async def empty_permissions(object_ref):
        del object_ref
        return ()

    operations = KnowledgeMigrationOperationsImpl()
    monkeypatch.setattr(operations, "_load_context", load_context)
    monkeypatch.setattr(operations_module, "_index_counts", index_counts)
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

    target_counts["elasticsearch"] = 3
    with pytest.raises(
        RuntimeError,
        match="target index counts do not match copied source chunks",
    ):
        await operations.verify_target(MigrationExecutionUnit(unit_id=1))
