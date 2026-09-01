from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import MutationStepContext
from bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner import (
    ProductionMutationStepOwner,
)
from bisheng.permission.domain.services.owner_service import OwnerService
from bisheng.permission.domain.services.permission_service import PermissionService


class _FakeIndices:
    def __init__(self, backend) -> None:
        self.backend = backend

    def exists(self, *, index: str) -> bool:
        return index in self.backend.es

    def delete(self, *, index: str) -> None:
        self.backend.es.pop(index, None)


class _FakeESClient:
    def __init__(self, backend) -> None:
        self.backend = backend
        self.indices = _FakeIndices(backend)

    def delete_by_query(self, *, index: str, body: dict) -> dict:
        if self.backend.fail_source_delete_once and index == "source-index":
            self.backend.fail_source_delete_once = False
            raise RuntimeError("injected source cleanup failure")
        file_ids = set(body["query"]["terms"]["metadata.document_id"])
        before = len(self.backend.es[index])
        self.backend.es[index] = [
            row for row in self.backend.es[index] if int(row["_source"]["metadata"]["document_id"]) not in file_ids
        ]
        return {"deleted": before - len(self.backend.es[index]), "failures": []}

    def count(self, *, index: str, body: dict) -> dict:
        file_ids = set(body["query"]["terms"]["metadata.document_id"])
        return {
            "count": sum(
                int(row["_source"]["metadata"]["document_id"]) in file_ids for row in self.backend.es.get(index, [])
            )
        }


class _FakeESStore:
    def __init__(self, backend, index_name: str) -> None:
        self.backend = backend
        self.index_name = index_name
        self.client = _FakeESClient(backend)

    def add_texts(self, *, texts: list[str], metadatas: list[dict]) -> None:
        rows = self.backend.es[self.index_name]
        for text, metadata in zip(texts, metadatas, strict=True):
            rows.append(
                {
                    "_id": f"{self.index_name}-{len(rows) + 1}",
                    "_source": {"text": text, "metadata": dict(metadata)},
                }
            )


class _FakeCollection:
    def __init__(self, backend, name: str) -> None:
        self.backend = backend
        self.name = name

    @property
    def num_entities(self) -> int:
        return len(self.backend.milvus.get(self.name, []))

    def delete(self, expression: str) -> None:
        ids = {int(value.strip()) for value in expression.split("[", 1)[1].rstrip("]").split(",") if value.strip()}
        self.backend.milvus[self.name] = [
            row for row in self.backend.milvus.get(self.name, []) if int(row["document_id"]) not in ids
        ]

    def query(self, *, expr: str, output_fields: list[str]) -> list[dict]:
        assert output_fields == ["count(*)"]
        ids = {int(value.strip()) for value in expr.split("[", 1)[1].rstrip("]").split(",") if value.strip()}
        return [{"count(*)": sum(int(row["document_id"]) in ids for row in self.backend.milvus.get(self.name, []))}]

    def drop(self) -> None:
        self.backend.milvus.pop(self.name, None)


class _FakeMilvusStore:
    def __init__(self, backend, name: str) -> None:
        self.backend = backend
        self.name = name

    @property
    def col(self):
        return _FakeCollection(self.backend, self.name) if self.name in self.backend.milvus else None

    def add_texts(self, *, texts: list[str], metadatas: list[dict]) -> None:
        del texts
        if self.backend.fail_target_add_once and self.name == "source-collection":
            self.backend.fail_target_add_once = False
            raise RuntimeError("injected target add failure")
        self.backend.milvus[self.name].extend(dict(metadata) for metadata in metadatas)


class _FakeRetrievalBackend:
    def __init__(self) -> None:
        self.es: dict[str, list[dict]] = defaultdict(list)
        self.milvus: dict[str, list[dict]] = defaultdict(list)
        self.fail_source_delete_once = False
        self.fail_target_add_once = False

    def es_store(self, name: str) -> _FakeESStore:
        return _FakeESStore(self, name)

    def milvus_store(self, name: str) -> _FakeMilvusStore:
        return _FakeMilvusStore(self, name)

    def chunks(self, client: _FakeESClient, index: str, query: dict) -> list[dict]:
        file_ids = set(query["query"]["terms"]["metadata.document_id"])
        return [
            dict(row) for row in self.es.get(index, []) if int(row["_source"]["metadata"]["document_id"]) in file_ids
        ]


def _spaces() -> dict[int, Knowledge]:
    return {
        10: Knowledge(
            id=10,
            tenant_id=42,
            user_id=7,
            name="source",
            type=KnowledgeTypeEnum.SPACE.value,
            state=KnowledgeState.PUBLISHED.value,
            model="1",
            index_name="source-index",
            collection_name="source-collection",
        ),
        20: Knowledge(
            id=20,
            tenant_id=42,
            user_id=7,
            name="target",
            type=KnowledgeTypeEnum.SPACE.value,
            state=KnowledgeState.PUBLISHED.value,
            model="1",
            index_name="target-index",
            collection_name="target-collection",
        ),
    }


def _move_context(step_code: str) -> MutationStepContext:
    return MutationStepContext(
        tenant_id=42,
        request_id=301,
        instance_id=401,
        execution_token="generation-1",
        action="move",
        step_code=step_code,
        idempotency_key=f"f046:301:{step_code}",
        resource_type="knowledge_file",
        resource_id=101,
        applicant_user_id=7,
        source_space_id=10,
        target_space_id=20,
        manifest={
            "action": "move",
            "root": {"id": 101, "old_space_id": 10, "file_type": 1, "old_status": 2},
            "rows": [
                {
                    "id": 101,
                    "old_space_id": 10,
                    "new_space_id": 20,
                    "file_type": 1,
                }
            ],
            "index_resource_ids": [101],
            "tag_snapshot": {"101": [9]},
            "parent_tuple": {
                "resource_type": "knowledge_file",
                "resource_id": 101,
                "old_parent_type": "knowledge_space",
                "old_parent_id": 10,
                "new_parent_type": "knowledge_space",
                "new_parent_id": 20,
            },
        },
    )


def _rename_context(step_code: str) -> MutationStepContext:
    return MutationStepContext(
        tenant_id=42,
        request_id=302,
        instance_id=402,
        execution_token="generation-1",
        action="rename",
        step_code=step_code,
        idempotency_key=f"f046:302:{step_code}",
        resource_type="knowledge_file",
        resource_id=101,
        applicant_user_id=7,
        source_space_id=10,
        target_space_id=10,
        manifest={
            "action": "rename",
            "new_name": "new.pdf",
            "root": {
                "id": 101,
                "old_space_id": 10,
                "file_type": 1,
                "old_status": 2,
                "old_name": "old.pdf",
            },
            "rows": [
                {
                    "id": 101,
                    "old_space_id": 10,
                    "file_type": 1,
                    "old_status": 2,
                    "old_name": "old.pdf",
                }
            ],
        },
    )


@pytest.fixture
def production_backend(monkeypatch: pytest.MonkeyPatch):
    backend = _FakeRetrievalBackend()
    spaces = _spaces()
    backend.es["source-index"] = [
        {
            "_id": "source-1",
            "_source": {
                "text": "document_name: old.pdf\nchunk-1",
                "metadata": {"document_id": 101, "knowledge_id": 10, "document_name": "old.pdf"},
            },
        },
        {
            "_id": "source-2",
            "_source": {
                "text": "document_name: old.pdf\nchunk-2",
                "metadata": {"document_id": 101, "knowledge_id": 10, "document_name": "old.pdf"},
            },
        },
    ]
    backend.milvus["source-collection"] = [
        {"document_id": 101, "knowledge_id": 10},
        {"document_id": 101, "knowledge_id": 10},
    ]
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeDao.query_by_id",
        lambda knowledge_id: spaces.get(int(knowledge_id)),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeRag.init_knowledge_es_vectorstore_sync",
        lambda knowledge: backend.es_store(knowledge.index_name),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeRag.init_es_vectorstore_sync",
        lambda name, **_kwargs: backend.es_store(name),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeRag.init_knowledge_milvus_vectorstore_sync",
        lambda _user_id, knowledge: backend.milvus_store(knowledge.collection_name),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeRag.init_milvus_vectorstore",
        lambda name, _embeddings, **_kwargs: backend.milvus_store(name),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.LLMService.get_bisheng_knowledge_embedding_sync",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "bisheng.worker.knowledge.rebuild_knowledge_worker.get_all_es_chunks",
        backend.chunks,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeUtils.split_chunk_metadata",
        lambda text: text.split("\n", 1)[-1],
        raising=False,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_mutation_step_owner.KnowledgeUtils.aggregate_chunk_metadata",
        lambda text, metadata: f"document_name: {metadata['document_name']}\n{text}",
        raising=False,
    )
    subjects = {"knowledge_space:10"}

    async def write_parent(operations, **_kwargs):
        for operation in operations:
            if operation.action == "delete":
                subjects.discard(operation.user)
            else:
                subjects.add(operation.user)

    monkeypatch.setattr(PermissionService, "batch_write_tuples", write_parent)
    monkeypatch.setattr(
        OwnerService,
        "read_relation_subjects_strict",
        AsyncMock(side_effect=lambda *_args, **_kwargs: set(subjects)),
        raising=False,
    )
    return backend


async def test_production_owner_builds_verifies_promotes_and_drops_isolated_shadow(production_backend):
    owner = ProductionMutationStepOwner()
    build = await owner.execute_and_verify(_move_context("move.index_prepare"))
    assert build.result_digest.startswith("shadow:verified:2:")
    assert len(production_backend.es["source-index"]) == 2
    assert production_backend.es["target-index"] == []
    assert len(production_backend.es["f046-42-301-move"]) == 2

    verify = await owner.execute_and_verify(_move_context("move.verify"))
    assert verify.result_digest.startswith("shadow:verified:2:")
    await owner.prepare_cutover_and_verify(_move_context("move.verify"))
    finalized = await owner.finalize_cutover_and_verify(_move_context("move.verify"))
    assert finalized.result_digest == "cutover:retrieval:verified:2"
    assert len(production_backend.es["source-index"]) == 2
    assert len(production_backend.es["target-index"]) == 2
    assert "f046-42-301-move" in production_backend.es
    assert "f046_42_301_move" in production_backend.milvus

    # Re-delivery before the atomic DB switch is authoritative and idempotent.
    replay = await owner.finalize_cutover_and_verify(_move_context("move.verify"))
    assert replay.result_digest == "cutover:retrieval:verified:2"
    assert len(production_backend.es["target-index"]) == 2
    cleanup = await owner.cleanup_cutover_and_verify(_move_context("move.verify"))
    assert cleanup.result_digest == "cutover:cleanup:verified:2"
    assert production_backend.es["source-index"] == []
    assert "f046-42-301-move" not in production_backend.es
    assert "f046_42_301_move" not in production_backend.milvus


async def test_rename_target_ready_never_overwrites_old_production_before_phase_commit(production_backend):
    owner = ProductionMutationStepOwner()
    await owner.execute_and_verify(_rename_context("rename.index_shadow"))

    ready = await owner.finalize_cutover_and_verify(_rename_context("rename.verify"))

    assert ready.result_digest.startswith("cutover:rename-target-ready:shadow:verified:2:")
    assert {row["_source"]["metadata"]["document_name"] for row in production_backend.es["source-index"]} == {"old.pdf"}
    assert sum("old.pdf" in row["_source"]["text"] for row in production_backend.es["source-index"]) == 2
    assert sum("new.pdf" in row["_source"]["text"] for row in production_backend.es["source-index"]) == 0
    assert all("new.pdf" not in row["_source"]["text"] for row in production_backend.es["source-index"])
    assert {row["_source"]["metadata"]["document_name"] for row in production_backend.es["f046-42-302-rename"]} == {
        "new.pdf"
    }
    await owner.cleanup_cutover_and_verify(_rename_context("rename.verify"))
    assert {row["_source"]["metadata"]["document_name"] for row in production_backend.es["source-index"]} == {"new.pdf"}
    assert sum("new.pdf" in row["_source"]["text"] for row in production_backend.es["source-index"]) == 2


async def test_rename_promotion_replays_from_shadow_after_delete_add_crash(production_backend):
    owner = ProductionMutationStepOwner()
    await owner.execute_and_verify(_rename_context("rename.index_shadow"))
    production_backend.fail_target_add_once = True

    with pytest.raises(RuntimeError, match="target add failure"):
        await owner.cleanup_cutover_and_verify(_rename_context("rename.verify"))

    assert production_backend.es["source-index"] == []
    assert len(production_backend.es["f046-42-302-rename"]) == 2
    assert len(production_backend.milvus["f046_42_302_rename"]) == 2

    result = await owner.cleanup_cutover_and_verify(_rename_context("rename.verify"))
    assert result.result_digest == "cutover:cleanup:verified:2"
    assert len(production_backend.es["source-index"]) == 2
    assert len(production_backend.milvus["source-collection"]) == 2
    assert "f046-42-302-rename" not in production_backend.es
    replay = await owner.cleanup_cutover_and_verify(_rename_context("rename.verify"))
    assert replay.result_digest == "cutover:cleanup:verified:2"


async def test_same_space_move_never_replaces_unchanged_official_retrieval(production_backend):
    context = _move_context("move.index_prepare")
    manifest = {
        **context.manifest,
        "target_space_id": 10,
        "rows": [
            {
                **context.manifest["rows"][0],
                "new_space_id": 10,
            }
        ],
    }
    context = replace(context, target_space_id=10, manifest=manifest)
    owner = ProductionMutationStepOwner()
    await owner.execute_and_verify(context)

    result = await owner.finalize_cutover_and_verify(context)

    assert result.result_digest == "cutover:retrieval:same-space-noop"
    assert len(production_backend.es["source-index"]) == 2
    assert len(production_backend.milvus["source-collection"]) == 2


async def test_production_owner_retries_source_cleanup_without_losing_shadow(production_backend):
    owner = ProductionMutationStepOwner()
    await owner.execute_and_verify(_move_context("move.index_prepare"))
    await owner.prepare_cutover_and_verify(_move_context("move.verify"))
    await owner.finalize_cutover_and_verify(_move_context("move.verify"))
    production_backend.fail_source_delete_once = True
    with pytest.raises(RuntimeError, match="source cleanup failure"):
        await owner.cleanup_cutover_and_verify(_move_context("move.verify"))
    assert len(production_backend.es["target-index"]) == 2
    assert len(production_backend.es["f046-42-301-move"]) == 2

    result = await owner.cleanup_cutover_and_verify(_move_context("move.verify"))
    assert result.result_digest == "cutover:cleanup:verified:2"
    assert production_backend.es["source-index"] == []


async def test_production_owner_parent_swap_and_rollback_are_read_after_verified(
    monkeypatch: pytest.MonkeyPatch,
    production_backend,
):
    del production_backend
    subjects = {"knowledge_space:10"}

    async def write(operations, **kwargs):
        assert kwargs == {"crash_safe": True, "raise_on_failure": True, "stop_on_failure": True}
        for operation in operations:
            if operation.action == "delete":
                subjects.discard(operation.user)
            else:
                subjects.add(operation.user)

    read = AsyncMock(side_effect=lambda *_args, **_kwargs: set(subjects))
    monkeypatch.setattr(PermissionService, "batch_write_tuples", write)
    monkeypatch.setattr(OwnerService, "read_relation_subjects_strict", read, raising=False)
    owner = ProductionMutationStepOwner()

    await owner.execute_and_verify(_move_context("move.parent_prepare"))
    await owner.prepare_cutover_and_verify(_move_context("move.verify"))
    assert subjects == {"knowledge_space:10", "knowledge_space:20"}
    await owner.cleanup_cutover_and_verify(_move_context("move.verify"))
    assert subjects == {"knowledge_space:20"}

    subjects.add("knowledge_space:10")
    await owner.rollback_cutover_and_verify(_move_context("move.verify"))
    assert subjects == {"knowledge_space:10"}
    assert read.await_count == 4


# Retired with OwnerService.read_relation_subjects_strict: F048 moved the
# authoritative read into the decision layer, which forces HIGHER_CONSISTENCY
# whenever the projection is degraded (test/permission/test_f048_*).
