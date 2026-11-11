"""Native per-version metadata indexing; SQL completion belongs to the Owner."""

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from inspect import isawaitable

from loguru import logger

from bisheng.common.constants.vectorstore_metadata import KNOWLEDGE_RAG_METADATA_SCHEMA
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeFileFailedError, ResourceReferenceInvalidError
from bisheng.core.ai import FakeEmbeddings
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum


@dataclass(frozen=True, slots=True)
class MetadataIndexResult:
    file_id: int
    milvus_count: int
    es_count: int


async def _checkpoint(guard):
    result = guard()
    if not isawaitable(result):
        raise ResourceReferenceInvalidError(reason="metadata_index_guard_required")
    if await result is not None:
        raise ResourceReferenceInvalidError(reason="metadata_index_guard_required")


def _replacements(affected_fields, after_values):
    if (
        not isinstance(affected_fields, tuple)
        or not affected_fields
        or any(not isinstance(value, str) or not value for value in affected_fields)
        or (after_values is not None and not isinstance(after_values, dict))
    ):
        raise ResourceReferenceInvalidError(reason="metadata_index_snapshot_invalid")
    fields = tuple(dict.fromkeys(affected_fields))
    replacements = {}
    for name in fields:
        if after_values is not None and name in after_values:
            value = after_values[name]
            if not isinstance(value, dict) or "field_value" not in value:
                raise ResourceReferenceInvalidError(reason="metadata_index_snapshot_invalid")
            replacements[name] = deepcopy(value["field_value"])
    return fields, replacements


def _updated_record(record, fields, replacements):
    if not isinstance(record, dict) or any(
        name not in record or record[name] is None for name in ("pk", "vector", "text")
    ):
        raise ValueError("metadata index record lacks its primary/vector/text fields")
    result = deepcopy(record)
    current = result.get("user_metadata")
    if current is not None and not isinstance(current, dict):
        raise ValueError("metadata index record has invalid user metadata")
    if current is not None or replacements:
        current = {} if current is None else current
        for name in fields:
            current.pop(name, None)
        current.update(deepcopy(replacements))
        result["user_metadata"] = current
    return result


def _es_count(response):
    body = getattr(response, "body", response)
    required = {"total", "updated", "deleted", "noops", "version_conflicts", "timed_out", "failures"}
    if not isinstance(body, Mapping) or not required.issubset(body):
        raise ValueError("metadata ES update returned incomplete statistics")
    if (
        type(body["timed_out"]) is not bool
        or body["timed_out"]
        or not isinstance(body["failures"], list)
        or body["failures"]
    ):
        raise ValueError("metadata ES update did not complete")
    counts = ("total", "updated", "deleted", "noops", "version_conflicts")
    if any(type(body[key]) is not int or body[key] < 0 for key in counts):
        raise ValueError("metadata ES update returned invalid counts")
    if body["deleted"] or body["version_conflicts"] or body["total"] != body["updated"] + body["noops"]:
        raise ValueError("metadata ES update returned partial results")
    return body["updated"]


async def apply_metadata_index_item(
    *,
    knowledge: Knowledge,
    invoke_user_id: int,
    file_id: int,
    affected_fields: tuple[str, ...],
    after_values: dict | None,
    guard: Callable[[], Awaitable[None]],
) -> MetadataIndexResult:
    if not callable(guard):
        raise ResourceReferenceInvalidError(reason="metadata_index_guard_required")
    if (
        not isinstance(knowledge, Knowledge)
        or knowledge.type != KnowledgeTypeEnum.SPACE.value
        or type(file_id) is not int
        or file_id <= 0
        or type(invoke_user_id) is not int
        or invoke_user_id <= 0
        or any(
            not isinstance(name, str) or not name.strip() for name in (knowledge.collection_name, knowledge.index_name)
        )
    ):
        raise ResourceReferenceInvalidError(reason="metadata_index_owner_scope_required")
    fields, replacements = _replacements(affected_fields, after_values)
    expected = {
        "expected_model_config_revision": knowledge.model_config_revision,
        "expected_index_generation": knowledge.index_generation,
        "metadata_schemas": KNOWLEDGE_RAG_METADATA_SCHEMA,
    }
    try:
        await _checkpoint(guard)
        vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id, knowledge=knowledge, embeddings=FakeEmbeddings(), **expected
        )
        collection = vector.col
        if collection is None:
            raise ValueError("metadata physical collection does not exist")
        output_fields = [value.name for value in collection.schema.fields]
        if not {"pk", "vector", "text"}.issubset(output_fields):
            raise ValueError("metadata physical collection schema is incomplete")
        await _checkpoint(guard)
        iterator = collection.query_iterator(
            batch_size=1000, limit=-1, expr=f"document_id == {file_id}", output_fields=output_fields
        )
        milvus_count, primary_error = 0, None
        try:
            while True:
                await _checkpoint(guard)
                records = iterator.next()
                if not isinstance(records, list):
                    raise ValueError("metadata iterator returned an invalid batch")
                if not records:
                    break
                batch = [_updated_record(record, fields, replacements) for record in records]
                await _checkpoint(guard)
                result = collection.upsert(data=batch)
                count = getattr(result, "upsert_count", None)
                if type(count) is not int or count != len(batch):
                    raise ValueError("metadata Milvus upsert returned incomplete statistics")
                milvus_count += count
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                iterator.close()
            except Exception:
                if primary_error is None:
                    raise
                # Cleanup is best effort when a primary failure already stops
                # processing; keep that failure and its original cause intact.
                logger.opt(exception=True).warning("metadata iterator cleanup failed for file_id={}", file_id)
        await _checkpoint(guard)
        es = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=knowledge, **expected)
        primary_error = None
        try:
            await _checkpoint(guard)
            response = await es.client.update_by_query(
                index=knowledge.index_name,
                refresh=True,
                body={
                    "query": {"term": {"metadata.document_id": file_id}},
                    "script": {
                        "lang": "painless",
                        "source": (
                            "if (ctx._source.metadata.user_metadata != null) { "
                            "for (def field : params.affected_fields) { ctx._source.metadata.user_metadata.remove(field); } } "
                            "if (!params.replacements.isEmpty()) { "
                            "if (ctx._source.metadata.user_metadata == null) { ctx._source.metadata.user_metadata = [:]; } "
                            "for (def entry : params.replacements.entrySet()) { "
                            "ctx._source.metadata.user_metadata[entry.getKey()] = entry.getValue(); } }"
                        ),
                        "params": {"affected_fields": list(fields), "replacements": deepcopy(replacements)},
                    },
                },
            )
            count = _es_count(response)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                await es.client.close()
            except Exception:
                if primary_error is None:
                    raise
                # This client is owned by this invocation. A failed cleanup
                # must not replace the primary IO/guard failure during unwind.
                logger.opt(exception=True).warning("metadata ES cleanup failed for file_id={}", file_id)
        await _checkpoint(guard)
        return MetadataIndexResult(file_id, milvus_count, count)
    except BaseErrorCode:
        raise
    except Exception as error:
        raise KnowledgeFileFailedError(exception="metadata_index_update_failed") from error
