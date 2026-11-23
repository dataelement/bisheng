"""Execution-scoped bounded material reuse through the actual publication entry."""

from pathlib import Path

import pytest

from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_permission_namespace import PermissionNamespacePlan
from test.knowledge_unification.test_migration_artifacts import ObjectIO, content, descriptor
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


async def test_verified_disk_pages_survive_memory_eviction_and_expire_with_execution():
    io = ObjectIO()
    store = UnificationArtifactStore(io)
    values = [content(records=[{"id": n, "value": "x" * 512}]) for n in range(3)]
    for value in values:
        io.objects[descriptor(value)["object_key"]] = value
    with store.verified_reads(max_bytes=700) as execution:
        directory = Path(execution.directory)
        for _ in range(2):
            for value in values:
                assert await store.aload_canonical(descriptor(value), run_id="e2e-f118-run", kind="baseline") == value
        assert execution.memory_bytes <= 700
        assert sum(call[0] == "get" for call in io.calls) == len(values)
        with store.verified_reads() as nested:
            assert nested is execution
        assert directory.exists()
    assert not directory.exists() and store.verified_inputs is None
    await store.aload_canonical(descriptor(values[0]), run_id="e2e-f118-run", kind="baseline")
    assert sum(call[0] == "get" for call in io.calls) == len(values) + 1


async def test_upload_readback_bypasses_verified_cache_and_exception_cleans_scope():
    io = ObjectIO()
    store = UnificationArtifactStore(io)
    value = content()
    ref = descriptor(value)
    with pytest.raises(RuntimeError, match="cancelled operation"):
        with store.verified_reads() as execution:
            directory = Path(execution.directory)
            await store.aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
            await store.aput_canonical(run_id="e2e-f118-run", kind="baseline", content=value)
            assert sum(call[0] == "get" for call in io.calls) == 2
            assert await store.aload_canonical(ref, run_id="e2e-f118-run", kind="baseline") == value
            raise RuntimeError("cancelled operation")
    assert not directory.exists() and store.verified_inputs is None


async def test_actual_full_publication_compiles_each_namespace_once(published_input, monkeypatch):
    value = published_input
    calls = []
    original = PermissionNamespacePlan.finish

    def finish(self):
        calls.append(self._tenant)
        return original(self)

    monkeypatch.setattr(PermissionNamespacePlan, "finish", finish)
    with value.artifacts.store.verified_reads():
        assert (await app(value).arun_permissions(**value.input, operator_id=7)).complete
    assert len(calls) == len(set(calls))
    assert value.store.scans == 3
