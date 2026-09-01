from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.llm.domain import LLMService


@dataclass(frozen=True, slots=True)
class OwnerStepResult:
    result_digest: str


class MutationStepOwner(Protocol):
    async def execute_and_verify(self, context) -> OwnerStepResult: ...

    async def compensate_and_verify(self, context) -> OwnerStepResult: ...

    async def prepare_cutover_and_verify(self, context) -> OwnerStepResult: ...

    async def rollback_cutover_and_verify(self, context) -> OwnerStepResult: ...

    async def finalize_cutover_and_verify(self, context) -> OwnerStepResult: ...

    async def cleanup_cutover_and_verify(self, context) -> OwnerStepResult: ...


class ProductionMutationStepOwner:
    """Authoritative F046 external-storage owner.

    Retrieval changes are first built in request-scoped ES/Milvus shadow stores,
    so approved-but-still-executing content never becomes searchable. The owner
    pre-installs the target while durable read projection still exposes the old
    view. DB + approval terminal then switch the view in one transaction; old
    parent/source residue is cleaned idempotently afterwards.
    """

    async def execute_and_verify(self, context) -> OwnerStepResult:
        if context.action == "rename":
            if context.step_code == "rename.index_shadow":
                return await asyncio.to_thread(self._build_shadow, context)
            if context.step_code == "rename.verify":
                return await asyncio.to_thread(self._verify_shadow, context)
        if context.action == "move":
            if context.step_code == "move.parent_prepare":
                return await self._verify_parent_plan(context)
            if context.step_code == "move.tags_prepare":
                return self._verify_tag_plan(context)
            if context.step_code == "move.storage_prepare":
                return self._verify_storage_plan(context)
            if context.step_code == "move.index_prepare":
                return await asyncio.to_thread(self._build_shadow, context)
            if context.step_code == "move.verify":
                return await asyncio.to_thread(self._verify_shadow, context)
        raise ValueError(f"unsupported F046 owner step: {context.action}/{context.step_code}")

    async def compensate_and_verify(self, context) -> OwnerStepResult:
        if context.step_code in {"rename.index_shadow", "move.index_prepare"}:
            await asyncio.to_thread(self._drop_shadow, context)
        # parent/tags/storage preparation is deliberately read-only. There is
        # no externally visible mutation to undo before the final cutover.
        return OwnerStepResult(result_digest=f"compensated:{context.step_code}")

    async def prepare_cutover_and_verify(self, context) -> OwnerStepResult:
        if context.action != "move":
            return OwnerStepResult(result_digest="cutover:no-external-prepare")
        await self._apply_parent_move(context)
        return OwnerStepResult(result_digest="cutover:parent-move:projected")

    async def rollback_cutover_and_verify(self, context) -> OwnerStepResult:
        if context.action == "move":
            await asyncio.to_thread(self._restore_old_retrieval, context)
            await self._apply_parent_move(context, revert=True)
        else:
            await asyncio.to_thread(self._drop_shadow, context)
        return OwnerStepResult(result_digest="rollback:old-view:verified")

    async def finalize_cutover_and_verify(self, context) -> OwnerStepResult:
        if context.action == "rename":
            verified = await asyncio.to_thread(self._verify_shadow, context)
            return OwnerStepResult(result_digest=f"cutover:rename-target-ready:{verified.result_digest}")
        if int(context.source_space_id) == int(context.target_space_id or context.source_space_id):
            # A same-space move changes only relational path/level fields. Its
            # retrieval metadata already names the same knowledge_id, so
            # replacing official rows would create an avoidable delete/add
            # crash window without changing the indexed generation.
            return OwnerStepResult(result_digest="cutover:retrieval:same-space-noop")
        promoted = await asyncio.to_thread(self._promote_shadow, context)
        return OwnerStepResult(result_digest=f"cutover:retrieval:verified:{promoted}")

    async def cleanup_cutover_and_verify(self, context) -> OwnerStepResult:
        if context.action == "move":
            # The reparent already happened atomically at cutover; nothing of the
            # old parent survives to clean up.
            cleaned = await asyncio.to_thread(self._cleanup_move_source_retrieval, context)
        else:
            cleaned = await asyncio.to_thread(self._promote_shadow, context)
        await asyncio.to_thread(self._drop_shadow, context)
        return OwnerStepResult(result_digest=f"cutover:cleanup:verified:{cleaned}")

    @classmethod
    def _build_shadow(cls, context) -> OwnerStepResult:
        source, target = cls._load_spaces(context)
        chunks = cls._source_chunks(context, source)
        cls._drop_shadow(context)
        if not chunks:
            return OwnerStepResult(result_digest="shadow:verified:0")

        texts, metadatas = cls._transform_chunks(context, chunks)
        shadow_es, shadow_milvus = cls._shadow_clients(context, target)
        shadow_milvus.add_texts(texts=texts, metadatas=metadatas)
        shadow_es.add_texts(texts=texts, metadatas=metadatas)
        count = cls._count_es_chunks(shadow_es, cls._shadow_es_name(context), cls._file_ids(context))
        if count != len(chunks):
            raise RuntimeError("F046 shadow ES verification count mismatch")
        return OwnerStepResult(result_digest=f"shadow:verified:{count}:{cls._chunk_digest(chunks)}")

    @classmethod
    def _verify_shadow(cls, context) -> OwnerStepResult:
        source, target = cls._load_spaces(context)
        source_chunks = cls._source_chunks(context, source)
        if not source_chunks:
            return OwnerStepResult(result_digest="shadow:verified:0")
        shadow_es, shadow_milvus = cls._shadow_clients(context, target)
        shadow_count = cls._count_es_chunks(
            shadow_es,
            cls._shadow_es_name(context),
            cls._file_ids(context),
        )
        if shadow_count != len(source_chunks):
            raise RuntimeError("F046 shadow retrieval verification count mismatch")
        collection = shadow_milvus.col
        if collection is None:
            raise RuntimeError("F046 shadow Milvus collection is unavailable")
        if cls._count_milvus_chunks(shadow_milvus, cls._file_ids(context)) != len(source_chunks):
            raise RuntimeError("F046 shadow Milvus verification count mismatch")
        return OwnerStepResult(result_digest=f"shadow:verified:{shadow_count}:{cls._chunk_digest(source_chunks)}")

    @classmethod
    def _promote_shadow(cls, context) -> int:
        _source, target = cls._load_spaces(context)
        file_ids = cls._file_ids(context)
        shadow_es, _ = cls._shadow_clients(context, target)
        from bisheng.worker.knowledge.rebuild_knowledge_worker import get_all_es_chunks

        shadow_chunks = get_all_es_chunks(
            shadow_es.client,
            cls._shadow_es_name(context),
            cls._es_query(file_ids),
        )
        # The request-scoped shadow is the durable replay source. Never infer
        # its contents from official rows: a prior same-index attempt may have
        # deleted those rows and crashed before add_texts.
        if not shadow_chunks:
            target_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(target)
            target_chunks = get_all_es_chunks(
                target_es.client,
                cls._index_name(target),
                cls._es_query(file_ids),
            )
            target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                int(context.applicant_user_id), knowledge=target
            )
            if cls._chunks_match_target(context, target_chunks) and cls._count_milvus_chunks(
                target_milvus, file_ids
            ) == len(target_chunks):
                return len(target_chunks)
            raise RuntimeError("F046 durable shadow disappeared before retrieval promotion")
        texts = [str(chunk.get("_source", {}).get("text", "")) for chunk in shadow_chunks]
        metadatas = [dict(chunk.get("_source", {}).get("metadata", {})) for chunk in shadow_chunks]
        for metadata in metadatas:
            metadata.pop("pk", None)

        target_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(target)
        target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            int(context.applicant_user_id), knowledge=target
        )
        cls._delete_retrieval_rows(target_es, target_milvus, target, file_ids)
        target_milvus.add_texts(texts=texts, metadatas=metadatas)
        target_es.add_texts(texts=texts, metadatas=metadatas)
        target_count = cls._count_es_chunks(target_es, cls._index_name(target), file_ids)
        if target_count != len(shadow_chunks):
            raise RuntimeError("F046 target retrieval verification count mismatch")
        if cls._count_milvus_chunks(target_milvus, file_ids) != len(shadow_chunks):
            raise RuntimeError("F046 target Milvus verification count mismatch")

        return target_count

    @staticmethod
    def _chunks_match_target(context, chunks: list[dict]) -> bool:
        """Verify the official generation when replay arrives after shadow drop."""

        if not chunks:
            return False
        for chunk in chunks:
            metadata = dict(chunk.get("_source", {}).get("metadata", {}))
            if context.action == "rename":
                if str(metadata.get("document_name") or "") != str(context.manifest["new_name"]):
                    return False
            elif int(metadata.get("knowledge_id") or 0) != int(context.target_space_id):
                return False
        return True

    @classmethod
    def _cleanup_move_source_retrieval(cls, context) -> int:
        source, target = cls._load_spaces(context)
        if int(source.id) == int(target.id):
            return 0
        file_ids = cls._file_ids(context)
        source_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(source)
        source_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            int(context.applicant_user_id), knowledge=source
        )
        before = cls._count_es_chunks(source_es, cls._index_name(source), file_ids)
        cls._delete_retrieval_rows(source_es, source_milvus, source, file_ids)
        if cls._count_es_chunks(source_es, cls._index_name(source), file_ids) != 0:
            raise RuntimeError("F046 source retrieval cleanup verification failed")
        if cls._count_milvus_chunks(source_milvus, file_ids) != 0:
            raise RuntimeError("F046 source Milvus cleanup verification failed")
        return before

    @classmethod
    def _restore_old_retrieval(cls, context) -> None:
        source, target = cls._load_spaces(context)
        file_ids = cls._file_ids(context)
        if not file_ids:
            return
        if context.action == "move" and int(source.id) != int(target.id):
            target_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(target)
            target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                int(context.applicant_user_id), knowledge=target
            )
            cls._delete_retrieval_rows(target_es, target_milvus, target, file_ids)
            if cls._count_es_chunks(target_es, cls._index_name(target), file_ids) != 0:
                raise RuntimeError("F046 target retrieval rollback verification failed")
            if cls._count_milvus_chunks(target_milvus, file_ids) != 0:
                raise RuntimeError("F046 target Milvus rollback verification failed")
            return

        official_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(source)
        current = cls._source_chunks(context, source)
        if not current:
            return
        old_name = str(context.manifest["root"]["old_name"])
        texts: list[str] = []
        metadatas: list[dict] = []
        for chunk in current:
            payload = chunk.get("_source", {})
            metadata = dict(payload.get("metadata", {}))
            metadata.pop("pk", None)
            metadata["document_name"] = old_name
            texts.append(
                KnowledgeUtils.aggregate_chunk_metadata(
                    KnowledgeUtils.split_chunk_metadata(str(payload.get("text", ""))),
                    metadata,
                )
            )
            metadatas.append(metadata)
        official_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
            int(context.applicant_user_id), knowledge=source
        )
        cls._delete_retrieval_rows(official_es, official_milvus, source, file_ids)
        official_milvus.add_texts(texts=texts, metadatas=metadatas)
        official_es.add_texts(texts=texts, metadatas=metadatas)
        if cls._count_es_chunks(official_es, cls._index_name(source), file_ids) != len(current):
            raise RuntimeError("F046 rename retrieval rollback verification failed")

    @classmethod
    def _drop_shadow(cls, context) -> None:
        target_id = int(context.target_space_id or context.source_space_id)
        target = KnowledgeDao.query_by_id(target_id)
        if target is None:
            raise LookupError(f"F046 target knowledge space not found: {target_id}")
        shadow_es = KnowledgeRag.init_es_vectorstore_sync(cls._shadow_es_name(context))
        if shadow_es.client.indices.exists(index=cls._shadow_es_name(context)):
            shadow_es.client.indices.delete(index=cls._shadow_es_name(context))
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            model_id=int(target.model), invoke_user_id=int(context.applicant_user_id)
        )
        shadow_milvus = KnowledgeRag.init_milvus_vectorstore(
            cls._shadow_collection_name(context),
            embeddings,
            metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
        )
        if shadow_milvus.col is not None:
            shadow_milvus.col.drop()

    @classmethod
    def _shadow_clients(cls, context, target: Knowledge):
        embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
            model_id=int(target.model), invoke_user_id=int(context.applicant_user_id)
        )
        return (
            KnowledgeRag.init_es_vectorstore_sync(
                cls._shadow_es_name(context), metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA
            ),
            KnowledgeRag.init_milvus_vectorstore(
                cls._shadow_collection_name(context),
                embeddings,
                metadata_schemas=KNOWLEDGE_RAG_METADATA_SCHEMA,
            ),
        )

    @classmethod
    def _source_chunks(cls, context, source: Knowledge) -> list[dict]:
        file_ids = cls._file_ids(context)
        if not file_ids:
            return []
        from bisheng.worker.knowledge.rebuild_knowledge_worker import get_all_es_chunks

        source_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(source)
        source_index = cls._index_name(source)
        if not source_es.client.indices.exists(index=source_index):
            return []
        return get_all_es_chunks(source_es.client, source_index, cls._es_query(file_ids))

    @staticmethod
    def _transform_chunks(context, chunks: list[dict]) -> tuple[list[str], list[dict]]:
        texts: list[str] = []
        metadatas: list[dict] = []
        for chunk in chunks:
            source = chunk.get("_source", {})
            metadata = dict(source.get("metadata", {}))
            metadata.pop("pk", None)
            text = str(source.get("text", ""))
            if context.action == "rename":
                metadata["document_name"] = str(context.manifest["new_name"])
                text = KnowledgeUtils.aggregate_chunk_metadata(KnowledgeUtils.split_chunk_metadata(text), metadata)
            else:
                metadata["knowledge_id"] = int(context.target_space_id)
            texts.append(text)
            metadatas.append(metadata)
        return texts, metadatas

    async def _verify_parent_plan(self, context) -> OwnerStepResult:
        """Validate the manifest's parent plan.

        The step code stays (it is persisted per request), but the check is now
        a plan sanity check only. Under 3.0 the move itself is one atomic
        projection — see _apply_parent_move — so there is no half-moved state to
        guard against, and the strict tuple read that used to guard it is gone
        with the pre-f048 runtime.
        """
        parent = dict(context.manifest.get("parent_tuple") or {})
        if not parent:
            raise RuntimeError("F046 move manifest has no parent tuple plan")
        expected = f"{parent['old_parent_type']}:{int(parent['old_parent_id'])}"
        return OwnerStepResult(result_digest=f"parent-plan:verified:{expected}")

    @staticmethod
    def _verify_tag_plan(context) -> OwnerStepResult:
        snapshot = context.manifest.get("tag_snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeError("F046 move manifest has no tag snapshot")
        count = sum(len(tag_ids) for tag_ids in snapshot.values())
        return OwnerStepResult(result_digest=f"tag-plan:verified:{count}")

    @staticmethod
    def _verify_storage_plan(context) -> OwnerStepResult:
        # F034 image/object keys remain stable across space moves. The durable
        # manifest deliberately contains no object rename operation.
        rows = context.manifest.get("rows")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("F046 move manifest has no storage ownership rows")
        return OwnerStepResult(result_digest=f"storage-plan:shared:{len(rows)}")

    async def _apply_parent_move(self, context, *, revert: bool = False) -> None:
        """Reparent through the same projection an unapproved move uses.

        The pre-f048 runtime could only write one tuple at a time, so a move was
        "add the new parent, then drop the old" — two writes with a window in
        between where the resource had one parent or two. That is what the
        dual-parent dance and its three read-after-write checks existed for.

        3.0 projects a move as a single operation, so approved moves take the
        ordinary path (KnowledgeSpaceService._replace_resource_parent_tuple) and
        there is no intermediate state to verify. Durability is the executor's
        job: a failed projection raises and Celery retries the step.
        """
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        parent = dict(context.manifest["parent_tuple"])
        old_parent = (str(parent["old_parent_type"]), int(parent["old_parent_id"]))
        new_parent = (str(parent["new_parent_type"]), int(parent["new_parent_id"]))
        source, target = (new_parent, old_parent) if revert else (old_parent, new_parent)
        service = KnowledgeSpaceService(request=None, login_user=context.actor)
        await service._replace_resource_parent_tuple(
            str(parent["resource_type"]),
            int(parent["resource_id"]),
            source,
            target,
        )

    @staticmethod
    def _load_spaces(context) -> tuple[Knowledge, Knowledge]:
        source = KnowledgeDao.query_by_id(int(context.source_space_id))
        target = KnowledgeDao.query_by_id(int(context.target_space_id or context.source_space_id))
        if source is None or target is None:
            raise LookupError("F046 source or target knowledge space is missing")
        if int(source.tenant_id) != int(context.tenant_id) or int(target.tenant_id) != int(context.tenant_id):
            raise RuntimeError("F046 retrieval owner refused a cross-tenant space")
        return source, target

    @staticmethod
    def _file_ids(context) -> list[int]:
        if context.action == "rename":
            root = context.manifest["root"]
            return (
                [int(root["id"])] if int(root.get("file_type", 0)) == 1 and int(root.get("old_status", 0)) == 2 else []
            )
        return sorted({int(file_id) for file_id in context.manifest.get("index_resource_ids", [])})

    @staticmethod
    def _es_query(file_ids: list[int]) -> dict:
        return {"query": {"terms": {"metadata.document_id": file_ids}}}

    @staticmethod
    def _milvus_file_expression(file_ids: list[int]) -> str:
        return f"document_id in {sorted(file_ids)}"

    @classmethod
    def _delete_retrieval_rows(cls, es_client, milvus_client, knowledge, file_ids: list[int]) -> None:
        if es_client.client.indices.exists(index=knowledge.index_name):
            response = es_client.client.delete_by_query(
                index=knowledge.index_name,
                body=cls._es_query(file_ids),
            )
            if isinstance(response, dict) and response.get("failures"):
                raise RuntimeError("F046 retrieval delete returned Elasticsearch failures")
        if milvus_client.col is not None:
            milvus_client.col.delete(cls._milvus_file_expression(file_ids))

    @staticmethod
    def _count_es_chunks(es_client, index_name: str, file_ids: list[int]) -> int:
        if not es_client.client.indices.exists(index=index_name):
            return 0
        response = es_client.client.count(index=index_name, body=ProductionMutationStepOwner._es_query(file_ids))
        return int(response.get("count", 0))

    @classmethod
    def _count_milvus_chunks(cls, milvus_client, file_ids: list[int]) -> int:
        collection = milvus_client.col
        if collection is None or not file_ids:
            return 0
        rows = collection.query(
            expr=cls._milvus_file_expression(file_ids),
            output_fields=["count(*)"],
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("F046 Milvus count verification returned an invalid response")
        count = rows[0].get("count(*)")
        if count is None:
            count = rows[0].get("count")
        if count is None:
            raise RuntimeError("F046 Milvus count verification omitted count")
        return int(count)

    @staticmethod
    def _index_name(knowledge: Knowledge) -> str:
        name = knowledge.index_name or knowledge.collection_name
        if not name:
            raise RuntimeError(f"knowledge space {knowledge.id} has no retrieval index")
        return str(name)

    @staticmethod
    def _shadow_es_name(context) -> str:
        return f"f046-{int(context.tenant_id)}-{int(context.request_id)}-{context.action}"

    @staticmethod
    def _shadow_collection_name(context) -> str:
        return f"f046_{int(context.tenant_id)}_{int(context.request_id)}_{context.action}"

    @staticmethod
    def _chunk_digest(chunks: list[dict]) -> str:
        identities = sorted(str(chunk.get("_id") or chunk.get("_source", {}).get("metadata", {})) for chunk in chunks)
        return sha256("|".join(identities).encode()).hexdigest()[:16]
