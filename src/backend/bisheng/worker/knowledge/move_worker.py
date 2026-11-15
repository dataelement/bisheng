"""F034 — cross-space retrieval-data migration worker.

When a file is moved to another knowledge space, ``move_items`` flips the DB
ownership synchronously and dispatches this task per file. The task moves the
file's *retrieval data* (Milvus vectors + ES chunks) from the source space's
collection/index into the target space's, re-embedding via the target space's
own model (``add_texts`` — handles differing embedding models), then deletes the
source-space copies and settles the status.

The legacy entry below retains its callers. ``apply_move_index_item`` is the
bounded replacement/checkpoint port for the later F118 Move Owner/J1 assembly.
Object lifetimes belong to that business operation and deletion manifests;
the original image-directory name alone does not imply deletion of its keys.
"""

import hashlib
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass, replace
from inspect import isawaitable
from typing import Protocol

from loguru import logger

from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, ResourceReferenceInvalidError
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from bisheng.worker.knowledge.rebuild_knowledge_worker import get_all_es_chunks
from bisheng.worker.main import bisheng_celery


@dataclass(frozen=True, slots=True)
class MoveMetadataPolicy:
    retained_fields: tuple[str, ...] = ()
    removed_fields: tuple[str, ...] = ()

    def __post_init__(self):
        for fields in (self.retained_fields, self.removed_fields):
            if (
                not isinstance(fields, tuple)
                or any(not isinstance(value, str) or not value or len(value) > 255 for value in fields)
                or len(set(fields)) != len(fields)
            ):
                raise ResourceReferenceInvalidError(reason="move_index_policy_invalid")
        if set(self.retained_fields) & set(self.removed_fields):
            raise ResourceReferenceInvalidError(reason="move_index_policy_invalid")


@dataclass(frozen=True, slots=True)
class MoveIndexCheckpoint:
    schema_version: int
    operation_id: str
    file_id: int
    document_id: int
    version_id: int
    source_space_id: int
    destination_space_id: int
    source_model_config_revision: int
    source_index_generation: str | None
    destination_model_config_revision: int
    destination_index_generation: str | None
    source_index_digest: str
    destination_index_digest: str
    metadata_policy_digest: str
    step: str
    source_count: int
    source_digest: str
    target_milvus_count: int
    target_es_count: int
    target_payload_digest: str


class MoveCheckpointPort(Protocol):
    async def aload(self) -> MoveIndexCheckpoint | None: ...
    async def asave(self, checkpoint: MoveIndexCheckpoint) -> None: ...


@dataclass(frozen=True, slots=True)
class MoveIndexResult:
    file_id: int
    source_count: int
    milvus_count: int
    es_count: int
    source_digest: str
    target_payload_digest: str


def _invalid(reason):
    raise ResourceReferenceInvalidError(reason=f"move_index_{reason}")


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class _Multiset:
    def __init__(self):
        self.values = []

    def add(self, value):
        self.values.append(_digest(value))

    @property
    def count(self):
        return len(self.values)

    def digest(self):
        # One fixed-size hash per record, including repeated identical bodies.
        return hashlib.sha256("".join(sorted(self.values)).encode()).hexdigest()


async def _guard(guard):
    value = guard()
    if not isawaitable(value) or await value is not None:
        _invalid("async_guard_required")


def _body(value):
    return getattr(value, "body", value)


def _scope(operation_id, target, source, destination, invoke_user_id, policy):
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or len(operation_id) > 64
        or not isinstance(target, ResourceVersionTarget)
        or not isinstance(policy, MoveMetadataPolicy)
        or not callable(getattr(policy, "__post_init__", None))
    ):
        _invalid("scope_required")
    policy.__post_init__()
    if type(invoke_user_id) is not int or invoke_user_id <= 0:
        _invalid("actor_required")
    for row in (source, destination):
        if (
            not isinstance(row, Knowledge)
            or row.type != 3
            or any(type(value) is not int or value <= 0 for value in (row.id, row.tenant_id))
            or type(row.model_config_revision) is not int
            or row.model_config_revision < 0
            or any(not isinstance(name, str) or not name.strip() for name in (row.index_name, row.collection_name))
        ):
            _invalid("space_required")
        if row.index_generation is not None and (
            not isinstance(row.index_generation, str) or not row.index_generation or len(row.index_generation) > 64
        ):
            _invalid("generation_invalid")
    if (
        source.tenant_id != destination.tenant_id
        or source.id == destination.id
        or source.index_name == destination.index_name
        or source.collection_name == destination.collection_name
    ):
        _invalid("distinct_same_tenant_spaces_required")
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        **target.model_dump(),
        "source_space_id": source.id,
        "destination_space_id": destination.id,
        "source_model_config_revision": source.model_config_revision,
        "source_index_generation": source.index_generation,
        "destination_model_config_revision": destination.model_config_revision,
        "destination_index_generation": destination.index_generation,
        "source_index_digest": _digest([source.index_name, source.collection_name]),
        "destination_index_digest": _digest([destination.index_name, destination.collection_name]),
        "metadata_policy_digest": _digest(
            {"retained": sorted(policy.retained_fields), "removed": sorted(policy.removed_fields)}
        ),
    }


def _checkpoint(value, scope):
    if value is None:
        return None
    if (
        type(value) is not MoveIndexCheckpoint
        or any(
            type(getattr(value, key)) is not type(expected) or getattr(value, key) != expected
            for key, expected in scope.items()
        )
        or value.step not in {"move_target_verified", "move_source_cleaned"}
    ):
        _invalid("checkpoint_scope_changed")
    counts = (value.source_count, value.target_milvus_count, value.target_es_count)
    if any(type(count) is not int or count < 0 for count in counts) or len(set(counts)) != 1:
        _invalid("checkpoint_counts_invalid")
    if any(
        not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
        for digest in (value.source_digest, value.target_payload_digest)
    ):
        _invalid("checkpoint_digest_invalid")
    return value


def _es_hits(result):
    value = _body(result)
    if (
        not isinstance(value, Mapping)
        or value.get("timed_out") is not False
        or not isinstance(value.get("_shards"), Mapping)
        or type(value["_shards"].get("failed")) is not int
        or value["_shards"]["failed"] != 0
    ):
        raise ValueError("move ES page is incomplete")
    page = value.get("hits")
    if not isinstance(page, Mapping):
        raise ValueError("move ES page is invalid")
    hits, total = page.get("hits"), page.get("total")
    if (
        not isinstance(hits, list)
        or len(hits) > 1000
        or not isinstance(total, Mapping)
        or total.get("relation") != "eq"
        or type(total.get("value")) is not int
        or total["value"] < 0
    ):
        raise ValueError("move ES page is invalid")
    return value, hits, total["value"]


async def _es_pages(es, index, file_id, guard) -> AsyncIterator[list[dict]]:
    cursor, primary_error, total, observed = None, None, None, 0
    try:
        await _guard(guard)
        result = await es.client.search(
            index=index,
            body={"query": {"term": {"metadata.document_id": file_id}}},
            size=1000,
            scroll="1m",
            track_total_hits=True,
        )
        while True:
            value = _body(result)
            cursor = value.get("_scroll_id", cursor) if isinstance(value, Mapping) else cursor
            value, hits, page_total = _es_hits(result)
            if total is None:
                total = page_total
            observed += len(hits)
            if page_total != total or observed > total or (not hits and observed != total):
                raise ValueError("move ES scroll did not read its complete snapshot")
            if not hits:
                break
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("move ES page lacks its cursor")
            yield hits
            await _guard(guard)
            result = await es.client.scroll(scroll_id=cursor, scroll="1m")
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if cursor:
            try:
                await es.client.clear_scroll(scroll_id=cursor)
            except Exception:
                if primary_error is None:
                    raise
                logger.opt(exception=True).warning("Move source cursor cleanup failed")


async def _exists(es, index, guard):
    await _guard(guard)
    exists = _body(await es.client.indices.exists(index=index))
    if type(exists) is not bool:
        raise ValueError("move ES existence result is invalid")
    return exists


async def _refresh(es, index, guard):
    await _guard(guard)
    result = _body(await es.client.indices.refresh(index=index))
    if not isinstance(result, Mapping) or result.get("_shards", {}).get("failed") != 0:
        raise ValueError("move ES refresh did not complete")


def _fields(collection):
    if collection is None:
        raise ValueError("move physical collection is missing")
    names = [field.name for field in collection.schema.fields]
    if not {"pk", "vector", "text", "document_id", "knowledge_id"} <= set(names):
        raise ValueError("move collection schema is incomplete")
    return names


def _dimension(collection):
    dimension = next(field.params.get("dim") for field in collection.schema.fields if field.name == "vector")
    if type(dimension) is not int or dimension <= 0:
        raise ValueError("move collection vector dimension is invalid")
    return dimension


def _valid_vector(value, dimension):
    return (
        isinstance(value, list)
        and len(value) == dimension
        and all(type(number) in (int, float) and math.isfinite(number) for number in value)
    )


async def _mv_digest(collection, file_id, guard):
    fields = _fields(collection)
    dimension = _dimension(collection)
    await _guard(guard)
    iterator = collection.query_iterator(
        batch_size=1000, limit=-1, expr=f"document_id == {file_id}", output_fields=fields
    )
    values, primary_error = _Multiset(), None
    try:
        while True:
            await _guard(guard)
            rows = iterator.next()
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("move Milvus page is invalid")
            if not rows:
                break
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or row.get("pk") is None
                    or not _valid_vector(row.get("vector"), dimension)
                ):
                    raise ValueError("move Milvus record lacks its primary/vector fields")
                values.add({key: row.get(key) for key in fields if key not in {"pk", "vector"}})
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            iterator.close()
        except Exception:
            if primary_error is None:
                raise
            logger.opt(exception=True).warning("Move Milvus iterator cleanup failed")
    return values


async def _es_digest(es, index, file_id, guard):
    values = _Multiset()
    async with aclosing(_es_pages(es, index, file_id, guard)) as pages:
        async for hits in pages:
            for hit in hits:
                values.add([hit["_id"], hit["_source"]])
    return values


async def _clear(es, index, collection, file_id, guard):
    if await _exists(es, index, guard):
        await _guard(guard)
        result = _body(
            await es.client.delete_by_query(
                index=index, body={"query": {"term": {"metadata.document_id": file_id}}}, refresh=True
            )
        )
        if (
            not isinstance(result, Mapping)
            or result.get("timed_out") is not False
            or result.get("failures") != []
            or any(
                type(result.get(key)) is not int or result[key] < 0 for key in ("total", "deleted", "version_conflicts")
            )
            or result["version_conflicts"]
            or result["total"] != result["deleted"]
        ):
            raise ValueError("move ES deletion did not complete")
        await _refresh(es, index, guard)
        if (await _es_digest(es, index, file_id, guard)).count:
            raise ValueError("move ES deletion left records")
    if collection is not None:
        await _guard(guard)
        collection.delete(f"document_id == {file_id}")
        await _guard(guard)
        collection.flush()
        if (await _mv_digest(collection, file_id, guard)).count:
            raise ValueError("move Milvus deletion left records")


async def _verify(es, knowledge, collection, file_id, guard):
    if not await _exists(es, knowledge.index_name, guard):
        raise ValueError("move target ES index is missing")
    await _refresh(es, knowledge.index_name, guard)
    milvus = await _mv_digest(collection, file_id, guard)
    elasticsearch = await _es_digest(es, knowledge.index_name, file_id, guard)
    return milvus, elasticsearch, _digest([milvus.digest(), elasticsearch.digest()])


async def apply_move_index_item(
    *,
    operation_id: str,
    target: ResourceVersionTarget,
    source: Knowledge,
    destination: Knowledge,
    invoke_user_id: int,
    metadata_policy: MoveMetadataPolicy,
    guard: Callable[[], Awaitable[None]],
    checkpoints: MoveCheckpointPort,
) -> MoveIndexResult:
    scope = _scope(operation_id, target, source, destination, invoke_user_id, metadata_policy)
    if (
        not callable(guard)
        or not callable(getattr(checkpoints, "aload", None))
        or not callable(getattr(checkpoints, "asave", None))
    ):
        _invalid("ports_required")
    source, destination = source.model_copy(deep=True), destination.model_copy(deep=True)
    clients, primary_error = [], None
    try:
        await _guard(guard)
        checkpoint = _checkpoint(await checkpoints.aload(), scope)
        stores = []
        for knowledge in (source, destination):
            await _guard(guard)
            es = await KnowledgeRag.init_knowledge_es_vectorstore(
                knowledge=knowledge,
                expected_model_config_revision=knowledge.model_config_revision,
                expected_index_generation=knowledge.index_generation,
            )
            clients.append(es.client)
            stores.append(es)
        source_es, target_es = stores
        if not await _exists(target_es, destination.index_name, guard) or (
            checkpoint is None and not await _exists(source_es, source.index_name, guard)
        ):
            raise ValueError("move physical ES index is missing")
        await _guard(guard)
        vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id,
            knowledge=destination,
            **({"embeddings": FakeEmbeddings()} if checkpoint else {}),
            expected_model_config_revision=destination.model_config_revision,
            expected_index_generation=destination.index_generation,
        )
        fields = _fields(vector.col)
        dimension = _dimension(vector.col)
        if checkpoint is None:
            await _clear(target_es, destination.index_name, vector.col, target.file_id, guard)
            original, expected_mv, expected_es, seen = _Multiset(), _Multiset(), _Multiset(), set()
            async with aclosing(_es_pages(source_es, source.index_name, target.file_id, guard)) as pages:
                async for hits in pages:
                    texts, metadatas, ids = [], [], []
                    for hit in hits:
                        ident, payload = hit.get("_id"), hit.get("_source")
                        if (
                            not isinstance(ident, str)
                            or not ident
                            or ident in seen
                            or not isinstance(payload, dict)
                            or not isinstance(payload.get("text"), str)
                            or not isinstance(payload.get("metadata"), dict)
                        ):
                            raise ValueError("move source chunk is invalid")
                        seen.add(ident)
                        metadata = deepcopy(payload["metadata"])
                        if metadata.get("document_id") != target.file_id or metadata.get("knowledge_id") != source.id:
                            raise ValueError("move source chunk belongs to another resource")
                        original.add([ident, payload])
                        metadata.pop("pk", None)
                        metadata["knowledge_id"] = destination.id
                        if metadata.get("user_metadata") is not None:
                            if not isinstance(metadata["user_metadata"], dict):
                                raise ValueError("move source metadata is invalid")
                            for name in metadata_policy.removed_fields:
                                metadata["user_metadata"].pop(name, None)
                        texts.append(payload["text"])
                        metadatas.append(metadata)
                        ids.append(_digest([operation_id, target.file_id, target.version_id, ident]))
                        expected_mv.add(
                            {
                                "text": payload["text"],
                                **{name: metadata.get(name) for name in fields if name not in {"pk", "vector", "text"}},
                            }
                        )
                        expected_es.add([ids[-1], {"text": payload["text"], "metadata": metadata}])
                    await _guard(guard)
                    embeddings = await vector.embedding_func.aembed_documents(texts)
                    if (
                        not isinstance(embeddings, list)
                        or len(embeddings) != len(texts)
                        or any(not _valid_vector(value, dimension) for value in embeddings)
                    ):
                        raise ValueError("move target embeddings are incomplete")
                    rows = [
                        {
                            "text": text,
                            "vector": embedding,
                            **{name: metadata.get(name) for name in fields if name not in {"pk", "vector", "text"}},
                        }
                        for text, embedding, metadata in zip(texts, embeddings, metadatas, strict=True)
                    ]
                    await _guard(guard)
                    inserted = vector.col.insert(data=rows)
                    if type(getattr(inserted, "insert_count", None)) is not int or inserted.insert_count != len(rows):
                        raise ValueError("move Milvus insert did not complete")
                    await _guard(guard)
                    written = await target_es.aadd_texts(
                        texts=texts,
                        metadatas=metadatas,
                        ids=ids,
                        refresh_indices=True,
                        create_index_if_not_exists=False,
                    )
                    if written != ids:
                        raise ValueError("move ES write did not complete")
            await _guard(guard)
            vector.col.flush()
            mv, es, digest = await _verify(target_es, destination, vector.col, target.file_id, guard)
            if (
                mv.count != original.count
                or es.count != original.count
                or mv.digest() != expected_mv.digest()
                or es.digest() != expected_es.digest()
            ):
                raise ValueError("move target content did not match its source")
            checkpoint = MoveIndexCheckpoint(
                **scope,
                step="move_target_verified",
                source_count=original.count,
                source_digest=original.digest(),
                target_milvus_count=mv.count,
                target_es_count=es.count,
                target_payload_digest=digest,
            )
            await _guard(guard)
            if await checkpoints.asave(checkpoint) is not None:
                _invalid("durable_checkpoint_required")
        else:
            mv, es, digest = await _verify(target_es, destination, vector.col, target.file_id, guard)
            if (
                mv.count != checkpoint.target_milvus_count
                or es.count != checkpoint.target_es_count
                or digest != checkpoint.target_payload_digest
            ):
                raise ValueError("move verified target changed")
        await _guard(guard)
        source_vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id,
            knowledge=source,
            embeddings=FakeEmbeddings(),
            expected_model_config_revision=source.model_config_revision,
            expected_index_generation=source.index_generation,
        )
        await _clear(source_es, source.index_name, source_vector.col, target.file_id, guard)
        if checkpoint.step != "move_source_cleaned":
            checkpoint = replace(checkpoint, step="move_source_cleaned")
            await _guard(guard)
            if await checkpoints.asave(checkpoint) is not None:
                _invalid("durable_checkpoint_required")
        await _guard(guard)
        return MoveIndexResult(
            target.file_id,
            checkpoint.source_count,
            checkpoint.target_milvus_count,
            checkpoint.target_es_count,
            checkpoint.source_digest,
            checkpoint.target_payload_digest,
        )
    except BaseException as error:
        primary_error = error
        if isinstance(error, BaseErrorCode) or not isinstance(error, Exception):
            raise
        raise KnowledgeFileFailedError(exception="move_index_update_failed") from error
    finally:
        close_error = None
        for client in clients:
            try:
                await client.close()
            except Exception as error:
                if close_error is not None or primary_error is not None:
                    logger.opt(exception=True).warning("Move ES client cleanup failed")
                if close_error is None:
                    close_error = error
        if primary_error is None and close_error is not None:
            raise KnowledgeFileFailedError(exception="move_index_close_failed") from close_error


@bisheng_celery.task(acks_late=True)
def migrate_file_vectors(file_id: int, source_space_id: int):
    """Move one file's retrieval data from ``source_space_id`` to its current space."""
    trace_id_var.set(f"migrate_file_vectors_{file_id}")
    logger.info("migrate_file_vectors start file_id={} source_space_id={}", file_id, source_space_id)

    db_file = KnowledgeFileDao.query_by_id_sync(file_id)
    if not db_file:
        logger.warning("migrate_file_vectors: file_id={} not found", file_id)
        return

    target_space = KnowledgeDao.query_by_id(db_file.knowledge_id)
    source_space = KnowledgeDao.query_by_id(source_space_id)
    if not target_space or not source_space:
        KnowledgeFileDao.update_file_status(
            [file_id], KnowledgeFileStatus.FAILED, "migrate: source/target space missing"
        )
        return
    if source_space.id == target_space.id:
        # Not actually cross-space (already settled by a prior run); just finalize.
        if db_file.status == KnowledgeFileStatus.REBUILDING.value:
            KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.SUCCESS)
        return

    try:
        _migrate_one_file(db_file, source_space, target_space)
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.SUCCESS)
        logger.info("migrate_file_vectors done file_id={} -> space={}", file_id, target_space.id)
    except BaseErrorCode as e:
        KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.FAILED, e.to_json_str())
    except Exception as e:
        logger.exception("migrate_file_vectors failed file_id={}: {}", file_id, str(e))
        KnowledgeFileDao.update_file_status(
            [file_id], KnowledgeFileStatus.FAILED, ServerError(exception=e).to_json_str()
        )


def _migrate_one_file(db_file: KnowledgeFile, source_space: Knowledge, target_space: Knowledge):
    source_index = source_space.index_name or source_space.collection_name
    source_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(source_space)
    query = {"query": {"match": {"metadata.document_id": db_file.id}}}
    chunks = get_all_es_chunks(source_es.client, source_index, query)

    if not chunks:
        # Nothing in the source (parse never finished, or a prior run already
        # migrated and deleted). Idempotent no-op — caller finalizes the status.
        logger.info("migrate_file_vectors: no source chunks for file_id={}, nothing to move", db_file.id)
        return

    texts: list[str] = []
    metadatas: list[dict] = []
    for chunk in chunks:
        src = chunk.get("_source", {})
        text = src.get("text", "")
        metadata = dict(src.get("metadata", {}))
        metadata.pop("pk", None)  # Milvus-internal; let add_texts assign fresh pks
        metadata["knowledge_id"] = target_space.id
        texts.append(text)
        metadatas.append(metadata)

    # Write into the target space (re-embeds with the target space's model).
    target_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=target_space)
    target_es = KnowledgeRag.init_knowledge_es_vectorstore_sync(target_space)
    target_milvus.add_texts(texts=texts, metadatas=metadatas)
    target_es.add_texts(texts=texts, metadatas=metadatas)

    # Delete the source-space copies (idempotent by document_id == file_id).
    source_es.client.delete_by_query(index=source_index, body=query)
    source_milvus = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(db_file.user_id, knowledge=source_space)
    if getattr(source_milvus, "col", None):
        try:
            source_milvus.col.delete(f"document_id == {db_file.id}")
        except Exception as e:  # best-effort: ES already moved; stale Milvus rows are filtered by knowledge_id
            logger.warning("migrate_file_vectors: source Milvus delete failed file_id={}: {}", db_file.id, str(e))
