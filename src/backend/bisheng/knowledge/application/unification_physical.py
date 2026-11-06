"""Read existing physical M2 facts; never initialize RAG/model resources."""

import asyncio
import re
from collections.abc import Mapping
from contextlib import asynccontextmanager
from copy import deepcopy

from elasticsearch import AsyncElasticsearch
from loguru import logger
from pymilvus import DataType, MilvusClient

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.config.settings import VectorStores
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.application.unification_inventory_codec import InventoryRecord, digest, record_from_values
from bisheng.knowledge.application.unification_minio import validate_object_key

_OBJECTS = {
    "original": "object_name",
    "preview": "preview_file_object_name",
    "bbox": "bbox_object_name",
    "thumbnail": "thumbnails",
    "html_snapshot": "html_snapshot_object_name",
}


def _invalid(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_physical_{reason}")


def _body(value):
    return getattr(value, "body", value)


def _count(value):
    if type(value) is str and re.fullmatch(r"0|[1-9][0-9]*", value):
        value = int(value)
    if type(value) is not int or value < 0:
        _invalid("count_invalid")
    return value


def _es_compatible(mapping, count):
    if not isinstance(mapping, Mapping):
        return False
    properties = mapping.get("properties", {})
    if not isinstance(properties, Mapping):
        return False
    metadata = properties.get("metadata", {})
    if not isinstance(metadata, Mapping) or metadata.get("enabled") is False:
        return False
    fields = metadata.get("properties", {})
    if not isinstance(fields, Mapping):
        return False
    for name in ("document_id", "knowledge_id"):
        field = fields.get(name)
        if field is None:
            if count or mapping.get("dynamic") in (False, "false", "strict"):
                return False
        elif not isinstance(field, Mapping) or field.get("type") not in {"long", "integer"}:
            return False
    text = properties.get("text")
    return (text is None and count == 0) or (isinstance(text, Mapping) and text.get("type") in {"text", "keyword"})


def _milvus_compatible(schema):
    fields = schema.get("fields")
    if not isinstance(fields, list) or any(not isinstance(item, dict) for item in fields):
        return False
    by_name = {item.get("name"): item.get("type") for item in fields}
    if len(by_name) != len(fields):
        return False
    return (
        by_name.get("document_id") in {DataType.INT64, DataType.INT32}
        and by_name.get("knowledge_id") in {DataType.INT64, DataType.INT32}
        and by_name.get("text") == DataType.VARCHAR
    )


class PhysicalInventoryReader:
    def __init__(self, *, es_client, milvus_client, storage, owns_clients=False):
        if (
            not callable(getattr(storage, "astat_object", None))
            or not callable(getattr(milvus_client, "has_collection", None))
            or not callable(getattr(es_client, "count", None))
        ):
            _invalid("native_clients_required")
        self._es, self._milvus, self._storage = es_client, milvus_client, storage
        self._owns_clients, self._closed = owns_clients, False

    @classmethod
    @asynccontextmanager
    async def aopen(cls, config: VectorStores, *, storage):
        if not isinstance(config, VectorStores):
            _invalid("configuration_required")
        es, mv = None, None
        try:
            es = AsyncElasticsearch(hosts=config.elasticsearch.elasticsearch_url, **config.elasticsearch.ssl_verify)
            arguments = deepcopy(config.milvus.connection_args or {})
            if arguments.get("host") and arguments.get("port"):
                arguments["uri"] = f"http://{arguments.pop('host')}:{arguments.pop('port')}"
            mv = await asyncio.to_thread(MilvusClient, **arguments)
            reader = cls(es_client=es, milvus_client=mv, storage=storage, owns_clients=True)
        except Exception as error:
            await cls._close_clients(es, mv, primary=error)
            raise KnowledgeOperationPlanConflictError(reason="migration_physical_initialize_failed") from error
        primary = None
        try:
            yield reader
        except BaseException as error:
            primary = error
            raise
        finally:
            reader._closed = True
            await cls._close_clients(es, mv, primary=primary)

    @staticmethod
    async def _close_clients(es, mv, *, primary=None):
        errors = []
        if es is not None:
            try:
                await es.close()
            except Exception as error:
                errors.append(error)
        if mv is not None:
            try:
                await asyncio.to_thread(mv.close)
            except Exception as error:
                errors.append(error)
        if errors:
            if primary is None:
                raise KnowledgeOperationPlanConflictError(reason="migration_physical_close_failed") from errors[0]
            logger.warning("M2 physical clients failed to close after a primary error")

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        if self._owns_clients:
            await self._close_clients(self._es, self._milvus)

    def _scope(self, expected=None):
        tenant = get_current_tenant_id()
        if (
            self._closed
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
            or (expected is not None and tenant != expected)
        ):
            _invalid("concrete_tenant_required")
        return tenant

    @staticmethod
    def _requests(records, kind, tenant):
        if type(records) is not tuple or len(records) > 199:
            _invalid("bounded_requests_required")
        result, seen = [], set()
        for record in records:
            if type(record) is not InventoryRecord or record.record_type != kind:
                _invalid("request_type_invalid")
            data = record.data
            if data["tenant_id"] != tenant or data["id"] in seen:
                _invalid("request_identity_invalid")
            seen.add(data["id"])
            if kind == "resource" and data["type"] not in (0, 3):
                _invalid("unified_resource_required")
            result.append(data)
        return result

    async def _index(self, row, tenant):
        index, collection = row["index_name"], row["collection_name"]
        es_exists, mv_exists, mapping_hash, schema_hash, es_count, mv_count = False, False, None, None, None, None
        compatible = True
        self._scope(tenant)
        if index:
            es_exists = _body(await self._es.indices.exists(index=index))
            if type(es_exists) is not bool:
                _invalid("existence_invalid")
            if es_exists:
                self._scope(tenant)
                mappings = _body(await self._es.indices.get_mapping(index=index))
                if not isinstance(mappings, Mapping) or set(mappings) != {index}:
                    _invalid("es_identity_changed")
                mapping = mappings[index].get("mappings")
                mapping_hash = digest(mapping)
                self._scope(tenant)
                counts = _body(await self._es.count(index=index))
                if (
                    not isinstance(counts, Mapping)
                    or not isinstance(counts.get("_shards"), Mapping)
                    or type(counts["_shards"].get("failed")) is not int
                    or counts["_shards"]["failed"] != 0
                ):
                    _invalid("es_count_incomplete")
                es_count = _count(counts.get("count"))
                compatible = _es_compatible(mapping, es_count)
        self._scope(tenant)
        if collection:
            mv_exists = await asyncio.to_thread(self._milvus.has_collection, collection_name=collection)
            if type(mv_exists) is not bool:
                _invalid("existence_invalid")
            if mv_exists:
                self._scope(tenant)
                schema = await asyncio.to_thread(self._milvus.describe_collection, collection_name=collection)
                if not isinstance(schema, Mapping) or schema.get("collection_name") != collection:
                    _invalid("milvus_identity_changed")
                schema_hash = digest(schema)
                self._scope(tenant)
                stats = await asyncio.to_thread(self._milvus.get_collection_stats, collection_name=collection)
                if not isinstance(stats, Mapping):
                    _invalid("milvus_count_invalid")
                mv_count = _count(stats.get("row_count"))
                compatible = compatible and _milvus_compatible(schema)
        return record_from_values(
            "physical_index",
            tenant_id=tenant,
            space_id=row["id"],
            index_name=index,
            collection_name=collection,
            es_exists=es_exists,
            milvus_exists=mv_exists,
            es_mapping_digest=mapping_hash,
            milvus_schema_digest=schema_hash,
            es_count=es_count,
            milvus_count=mv_count,
            identifier_compatible=compatible,
        )

    async def aiter_facts(self, *, resource_requests=(), object_requests=()):
        tenant = self._scope()
        resources = self._requests(resource_requests, "resource", tenant)
        files = self._requests(object_requests, "file", tenant)
        objects = []
        for row in files:
            for kind, field in _OBJECTS.items():
                key = row[field]
                if key not in (None, ""):
                    validate_object_key(key)
                    objects.append((row, kind, key))
        try:
            for row in resources:
                fact = await self._index(row, tenant)
                self._scope(tenant)
                yield fact
            semaphore = asyncio.Semaphore(16)
            keys = tuple(dict.fromkeys(key for _, _, key in objects))

            async def stat(key):
                async with semaphore:
                    self._scope(tenant)
                    return await self._storage.astat_object(key)

            results = await asyncio.gather(*(stat(key) for key in keys), return_exceptions=True)
            for value in results:
                if isinstance(value, BaseException):
                    raise value
            stats = dict(zip(keys, results, strict=True))
            for row, kind, key in objects:
                self._scope(tenant)
                value = stats[key]
                if (
                    type(value) is not dict
                    or set(value) != {"exists", "size", "etag"}
                    or type(value["exists"]) is not bool
                    or (value["exists"] and (type(value["size"]) is not int or value["size"] < 0))
                    or (not value["exists"] and (value["size"] is not None or value["etag"] is not None))
                ):
                    _invalid("object_stat_invalid")
                yield record_from_values(
                    "physical_object",
                    tenant_id=tenant,
                    space_id=row["knowledge_id"],
                    file_id=row["id"],
                    object_kind=kind,
                    object_key=key,
                    **value,
                )
        except KnowledgeOperationPlanConflictError:
            raise
        except Exception as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_physical_read_failed") from error
