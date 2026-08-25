"""Shared SPACE storage adapter layer (F1, refactor spec sections 3.2/3.3/6.2).

This module implements the platform side of the tenant-shared Milvus
collection / ES index:

- naming helpers (``col_space_shared_{tenant_id}`` / ``idx_space_shared_{tenant_id}``);
- the schema fingerprint (embedding model / dimension / metric / index params
  / ARRAY capacity) recorded at bootstrap time and verified before every
  write - a mismatch fails closed with ``SCHEMA_FINGERPRINT_MISMATCH`` and is
  never auto-repaired;
- shared-collection bootstrap (admin path only - never on a normal request
  path) and shared ES index creation (mapping + alias, optional routing);
- the real ``SharedSpaceStorageWriter`` implementation of the frozen M0
  contract in :mod:`bisheng.knowledge.domain.contracts.shared_space_storage`.

Everything here is gated behind ``settings.knowledge_space_shared_storage.enabled``
plus the per-tenant routing table row (``shared_enabled``): with either off,
callers get ``SHARED_STORAGE_NOT_ENABLED`` / ``ROUTING_NOT_CONFIGURED`` and
existing behavior is untouched.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections
from pymilvus.orm import utility

from bisheng.common.constants.vectorstore_metadata import RagMetadataFieldSchema
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
)
from bisheng.knowledge.domain.contracts.metadata_schema import (
    SHARED_SPACE_CONTENT_METADATA_SCHEMA,
)
from bisheng.knowledge.domain.contracts.retrieval_scope import CanonicalChunkHit
from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentDeleteRequest,
    ContentUpsertRequest,
    MembershipUpdateRequest,
    SharedSpaceStorageWriter,
    validate_knowledge_ids,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
    KnowledgeSpaceSharedStorageRouting,
    KnowledgeSpaceSharedStorageRoutingDao,
)
from bisheng.knowledge.rag.elasticsearch_factory import generate_metadata_mappings
from bisheng.knowledge.rag.milvus_factory import build_array_field_kwargs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

#: marker written into the Milvus collection description identifying a
#: bisheng shared SPACE collection and carrying the schema fingerprint.
SHARED_STORE_KIND = "bisheng_space_shared"
SHARED_STORE_SCHEMA_VERSION = 1

SHARED_MILVUS_PK_FIELD = "pk"
SHARED_MILVUS_TEXT_FIELD = "text"
SHARED_MILVUS_VECTOR_FIELD = "vector"

_MILVUS_TYPE_MAP = {
    "text": DataType.VARCHAR,
    "boolean": DataType.BOOL,
    "int8": DataType.INT8,
    "int16": DataType.INT16,
    "int32": DataType.INT32,
    "int64": DataType.INT64,
    "float": DataType.FLOAT,
    "double": DataType.DOUBLE,
    "json": DataType.JSON,
}


def get_shared_storage_conf():
    """Return the ``knowledge_space_shared_storage`` settings block.

    Tolerant of test settings mocks that predate this field (returns a
    default-disabled block instead of raising).
    """
    from bisheng.common.services.config_service import settings

    conf = getattr(settings, "knowledge_space_shared_storage", None)
    if conf is None:
        from bisheng.core.config.settings import KnowledgeSpaceSharedStorageConf

        return KnowledgeSpaceSharedStorageConf()
    return conf


def shared_collection_name(tenant_id: int, conf=None) -> str:
    """``{collection_prefix}_{tenant_id}``, e.g. ``col_space_shared_1``."""
    conf = conf or get_shared_storage_conf()
    return f"{conf.collection_prefix}_{int(tenant_id)}"


def shared_index_name(tenant_id: int, conf=None) -> str:
    """``{index_prefix}_{tenant_id}``, e.g. ``idx_space_shared_1``."""
    conf = conf or get_shared_storage_conf()
    return f"{conf.index_prefix}_{int(tenant_id)}"


def shared_index_alias(tenant_id: int, conf=None) -> str:
    return f"{shared_index_name(tenant_id, conf)}_alias"


def es_routing_value(tenant_id: int, canonical_document_id: int) -> str:
    """Routing key for the shared ES index when routing is enabled."""
    return f"{int(tenant_id)}-{int(canonical_document_id)}"


# ---------------------------------------------------------------------------
# tenant routing snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantRoutingSnapshot:
    """Immutable view of one tenant's routing-table row."""

    tenant_id: int
    shared_enabled: bool
    routing_version: int
    write_frozen: bool
    collection_name: str | None
    index_name: str | None
    embedding_model_id: int | None
    schema_fingerprint: str | None
    migration_state: str | None

    @classmethod
    def from_row(cls, row: KnowledgeSpaceSharedStorageRouting) -> "TenantRoutingSnapshot":
        return cls(
            tenant_id=int(row.tenant_id),
            shared_enabled=bool(row.shared_enabled),
            routing_version=int(row.routing_version),
            write_frozen=bool(row.write_frozen),
            collection_name=row.collection_name,
            index_name=row.index_name,
            embedding_model_id=row.embedding_model_id,
            schema_fingerprint=row.schema_fingerprint,
            migration_state=row.migration_state,
        )


def load_tenant_routing_snapshot(tenant_id: int) -> TenantRoutingSnapshot | None:
    """Read the routing row for a tenant (no caching: the table is the single
    source of truth and gray-release staleness must be detectable, R16)."""
    row = KnowledgeSpaceSharedStorageRoutingDao.get_by_tenant(int(tenant_id))
    return TenantRoutingSnapshot.from_row(row) if row is not None else None


def resolve_space_shared_routing(
    tenant_id: int,
    knowledge_type: int | None,
    *,
    conf=None,
    routing_provider: Callable[[int], TenantRoutingSnapshot | None] | None = None,
) -> TenantRoutingSnapshot | None:
    """Decide whether a knowledge base of ``knowledge_type`` in ``tenant_id``
    must be routed to the shared store.

    Returns the routing snapshot when **all** of these hold (otherwise None,
    which means "behave exactly like the old code"):

    - the global switch ``knowledge_space_shared_storage.enabled`` is on;
    - the knowledge type is SPACE;
    - the tenant has a routing row with ``shared_enabled=True``.
    """
    conf = conf or get_shared_storage_conf()
    if not conf.enabled:
        return None
    if knowledge_type is None or int(knowledge_type) != KnowledgeTypeEnum.SPACE.value:
        return None
    provider = routing_provider or load_tenant_routing_snapshot
    snapshot = provider(int(tenant_id))
    if snapshot is None or not snapshot.shared_enabled:
        return None
    return snapshot


def freeze_tenant_writes(tenant_id: int) -> bool:
    """F4: Set ``write_frozen=True`` on the tenant's routing row.

    Returns True when a row was updated. Idempotent — safe to call when
    already frozen. Callers must gate on ``migration_write_block_enabled``
    before calling (the guard in ``_require_not_write_frozen`` and the
    ``SharedSpaceStorageWriter`` both respect that config).
    """
    return KnowledgeSpaceSharedStorageRoutingDao.set_write_frozen(int(tenant_id), True)


def unfreeze_tenant_writes(tenant_id: int) -> bool:
    """F4: Clear ``write_frozen`` on the tenant's routing row.

    Returns True when a row was updated. Idempotent.
    """
    return KnowledgeSpaceSharedStorageRoutingDao.set_write_frozen(int(tenant_id), False)


def tenant_target_embedding_model_id(snapshot: TenantRoutingSnapshot) -> int:
    """The tenant-wide target embedding model (routing row wins, config is
    the fallback). Raises when neither is configured."""
    if snapshot.embedding_model_id is not None:
        return int(snapshot.embedding_model_id)
    conf = get_shared_storage_conf()
    if conf.tenant_embedding_model_id is not None:
        return int(conf.tenant_embedding_model_id)
    raise SharedStorageContractError(
        SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
        "tenant target embedding model is not configured "
        "(routing row embedding_model_id / settings tenant_embedding_model_id)",
        tenant_id=snapshot.tenant_id,
    )


# ---------------------------------------------------------------------------
# schema fingerprint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SharedStoreSchemaSpec:
    """Everything that must be identical for all chunks in one shared
    collection (spec 3.2): embedding model identity, vector dimension,
    metric, index params and the ARRAY hard capacity."""

    embedding_model_id: int
    dimension: int
    metric_type: str = "L2"
    index_type: str = "HNSW"
    index_params: Mapping[str, Any] = field(
        default_factory=lambda: {"M": 8, "efConstruction": 64}
    )
    knowledge_ids_max_capacity: int = 4096

    def payload(self) -> dict[str, Any]:
        """Canonical, JSON-serialisable description used for hashing."""
        metadata_fields = [
            {
                "field_name": f.field_name,
                "field_type": f.field_type,
                "kwargs": {
                    k: (str(v) if isinstance(v, DataType) else v)
                    for k, v in sorted((f.kwargs or {}).items())
                },
            }
            for f in SHARED_SPACE_CONTENT_METADATA_SCHEMA
        ]
        # the ARRAY hard capacity is dictated by this spec, not by the frozen
        # schema constant, so normalise it here.
        for f in metadata_fields:
            if f["field_name"] == "knowledge_ids":
                f["kwargs"]["max_capacity"] = int(self.knowledge_ids_max_capacity)
        return {
            "kind": SHARED_STORE_KIND,
            "schema_version": SHARED_STORE_SCHEMA_VERSION,
            "embedding_model_id": int(self.embedding_model_id),
            "dimension": int(self.dimension),
            "metric_type": self.metric_type,
            "index_type": self.index_type,
            "index_params": dict(self.index_params),
            "knowledge_ids_max_capacity": int(self.knowledge_ids_max_capacity),
            "metadata_fields": metadata_fields,
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def description_payload(self) -> str:
        """The string stored as the Milvus collection description."""
        return json.dumps(
            {"kind": SHARED_STORE_KIND, "fingerprint": self.fingerprint()},
            sort_keys=True,
            ensure_ascii=False,
        )


def parse_collection_description_payload(description: str | None) -> dict[str, Any] | None:
    """Best-effort parse of a shared-store description payload.

    Returns None for anything that is not our JSON marker (e.g. a collection
    created by another tool, or an empty description).
    """
    if not description:
        return None
    try:
        payload = json.loads(description)
    except (TypeError, ValueError):
        return None
    if isinstance(payload, dict) and payload.get("kind") == SHARED_STORE_KIND:
        return payload
    return None


def verify_shared_collection_schema(
    collection: Collection,
    expected_fingerprint: str,
    *,
    tenant_id: int | None = None,
) -> None:
    """Fail closed when the existing collection was not created with the
    expected schema fingerprint. Never repairs / overwrites (spec 6.2)."""
    payload = parse_collection_description_payload(
        getattr(collection, "description", None)
    )
    if payload is None or payload.get("fingerprint") != expected_fingerprint:
        raise SharedStorageContractError(
            SharedStorageErrorCode.SCHEMA_FINGERPRINT_MISMATCH,
            f"shared collection {getattr(collection, 'name', '<unknown>')} schema "
            f"fingerprint mismatch: expected {expected_fingerprint}, found "
            f"{(payload or {}).get('fingerprint')}",
            tenant_id=tenant_id,
        )


# ---------------------------------------------------------------------------
# Milvus shared collection bootstrap (admin path only)
# ---------------------------------------------------------------------------


def _rag_field_to_pymilvus(
    schema: RagMetadataFieldSchema, spec: SharedStoreSchemaSpec
) -> FieldSchema:
    kwargs = dict(schema.kwargs or {})
    if schema.field_type.startswith("array_"):
        array_kwargs = build_array_field_kwargs(schema)
        if schema.field_name == "knowledge_ids":
            array_kwargs["max_capacity"] = int(spec.knowledge_ids_max_capacity)
        return FieldSchema(schema.field_name, DataType.ARRAY, **array_kwargs)
    dtype = _MILVUS_TYPE_MAP.get(schema.field_type)
    if dtype is None:
        raise ValueError(f"unsupported metadata field_type {schema.field_type!r}")
    return FieldSchema(schema.field_name, dtype, **kwargs)


def build_shared_field_schemas(spec: SharedStoreSchemaSpec) -> list[FieldSchema]:
    """Full field list of the shared collection (pk / text / vector + the
    frozen shared metadata schema)."""
    fields = [
        FieldSchema(
            SHARED_MILVUS_PK_FIELD,
            DataType.INT64,
            is_primary=True,
            auto_id=True,
        ),
        FieldSchema(SHARED_MILVUS_TEXT_FIELD, DataType.VARCHAR, max_length=65535),
        FieldSchema(
            SHARED_MILVUS_VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=int(spec.dimension)
        ),
    ]
    fields.extend(_rag_field_to_pymilvus(f, spec) for f in SHARED_SPACE_CONTENT_METADATA_SCHEMA)
    return fields


def _ensure_shared_milvus_connection(alias: str | None = None) -> str:
    """Connect to Milvus using the same connection handling as
    ``MilvusFactory`` and return the connection alias."""
    from bisheng.common.services.config_service import settings

    conf = settings.get_vectors_conf().milvus
    connection_args = conf.connection_args.copy()
    if connection_args.get("host") and connection_args.get("port"):
        uri = f"http://{connection_args.pop('host')}:{connection_args.pop('port')}"
        connection_args["uri"] = uri
    alias = alias or connection_args.get("alias") or "bisheng_space_shared"
    connection_args.setdefault("alias", alias)
    if not connections.has_connection(alias):
        connections.connect(**connection_args)
    return alias


@dataclass(frozen=True)
class SharedCollectionBootstrapResult:
    collection_name: str
    fingerprint: str
    created: bool


def bootstrap_shared_collection(
    spec: SharedStoreSchemaSpec,
    tenant_id: int,
    *,
    collection_name: str | None = None,
    connection_alias: str | None = None,
    collection_factory: Callable[[str, CollectionSchema, str, str], Collection] | None = None,
) -> SharedCollectionBootstrapResult:
    """Create (idempotently) the tenant shared Milvus collection.

    ADMIN PATH ONLY (F1.3): bootstrap is driven by the migration/admin
    commands, never from a normal request path. If the collection already
    exists its schema fingerprint is verified and a mismatch fails closed
    with ``SCHEMA_FINGERPRINT_MISMATCH`` - it is never dropped or rewritten.

    ``collection_factory(name, schema, description, alias)`` allows tests to
    substitute collection creation.
    """
    name = collection_name or shared_collection_name(tenant_id)
    fingerprint = spec.fingerprint()
    description = spec.description_payload()

    if collection_factory is None:
        alias = _ensure_shared_milvus_connection(connection_alias)
        if utility.has_collection(name, using=alias):
            existing = Collection(name, using=alias)
            verify_shared_collection_schema(existing, fingerprint, tenant_id=tenant_id)
            try:
                existing.load()
            except Exception:
                logger.exception("load shared collection %s failed", name)
                raise
            return SharedCollectionBootstrapResult(name, fingerprint, created=False)
        schema = CollectionSchema(
            build_shared_field_schemas(spec), description=description
        )
        collection = Collection(name, schema=schema, using=alias)
    else:
        schema = CollectionSchema(
            build_shared_field_schemas(spec), description=description
        )
        collection = collection_factory(
            name,
            schema,
            description,
            connection_alias or "",
        )

    # record the fingerprint in the collection description for write-time checks
    try:
        collection.set_properties({"description": description})
    except Exception:  # pragma: no cover - older servers / fakes
        logger.warning("could not set description property on shared collection %s", name)

    index_body = {
        "index_type": spec.index_type,
        "metric_type": spec.metric_type,
        "params": dict(spec.index_params),
    }
    try:
        collection.create_index(SHARED_MILVUS_VECTOR_FIELD, index_body)
    except Exception:  # pragma: no cover - already indexed
        logger.warning("create_index on shared collection %s failed (may exist)", name)
    try:
        collection.load()
    except Exception:
        logger.exception("load shared collection %s failed", name)
        raise

    return SharedCollectionBootstrapResult(name, fingerprint, created=True)


# ---------------------------------------------------------------------------
# ES shared index (F1.4)
# ---------------------------------------------------------------------------


def build_shared_es_index_body(conf=None) -> dict[str, Any]:
    """Index body for ``idx_space_shared_{tenant_id}``: text field plus the
    full shared metadata mapping (``metadata.knowledge_ids`` multi-value
    long and every field of spec 3.3)."""
    conf = conf or get_shared_storage_conf()
    metadata_mappings = generate_metadata_mappings(SHARED_SPACE_CONTENT_METADATA_SCHEMA)
    return {
        "settings": {"number_of_shards": int(conf.es_number_of_shards)},
        "mappings": {
            "properties": {
                SHARED_MILVUS_TEXT_FIELD: {"type": "text"},
                "metadata": {"properties": metadata_mappings},
            }
        }
    }


def ensure_shared_es_index(
    es_client: Any,
    tenant_id: int,
    *,
    index_name: str | None = None,
    conf=None,
    create_index: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Idempotently create the tenant shared ES index + alias.

    Routing is *not* baked into the mapping: whether query/index operations
    carry a routing key is controlled by ``es_routing_enabled`` at call time,
    so the PoC can flip it without reindexing.
    """
    conf = conf or get_shared_storage_conf()
    index_name = index_name or shared_index_name(tenant_id, conf)
    body = build_shared_es_index_body(conf)
    if create_index is not None:
        create_index(index_name, body)
    else:
        if not es_client.indices.exists(index=index_name):
            es_client.indices.create(index=index_name, body=body)
        es_client.indices.put_alias(index=index_name, name=f"{index_name}_alias")
    return index_name


# ---------------------------------------------------------------------------
# shared Milvus expressions (used by writer + reader)
# ---------------------------------------------------------------------------


def build_milvus_membership_expr(
    tenant_id: int, space_ids: Sequence[int]
) -> str:
    """Render the tenant + membership pre-filter (spec 3.6).

    Single space -> ``ARRAY_CONTAINS``; multiple spaces ->
    ``ARRAY_CONTAINS_ANY``. The tenant boundary is always present.
    """
    if not space_ids:
        raise ValueError("requested_space_ids must not be empty")
    expr = f"tenant_id == {int(tenant_id)}"
    ids = [int(s) for s in space_ids]
    if len(ids) == 1:
        expr += f" and ARRAY_CONTAINS(knowledge_ids, {ids[0]})"
    else:
        expr += f" and ARRAY_CONTAINS_ANY(knowledge_ids, [{', '.join(str(i) for i in ids)}])"
    return expr


def build_shared_es_filter(filter_: Any) -> list[dict[str, Any]]:
    """ES filter clauses mirroring the Milvus membership filter (spec 3.6)."""
    if not filter_.requested_space_ids:
        raise ValueError("requested_space_ids must not be empty")
    return [
        {"term": {"metadata.tenant_id": int(filter_.tenant_id)}},
        {"terms": {"metadata.knowledge_ids": [int(s) for s in filter_.requested_space_ids]}},
    ]


# ---------------------------------------------------------------------------
# the real SharedSpaceStorageWriter (F1.5)
# ---------------------------------------------------------------------------

_MILVUS_QUERY_BATCH = 16384


class MilvusEsSharedSpaceStorageWriter(SharedSpaceStorageWriter):
    """Real writer implementation of the frozen M0 contract.

    Semantics (contract docstrings are normative):

    - ``upsert_content``: writes the new ``content_generation`` first and
      deletes older generations of the same canonical version afterwards
      (Milvus ``auto_id=True`` makes ARRAY updates a rewrite). Before the
      insert it also removes leftovers of the *same* generation from a
      crashed earlier attempt, which keeps retries idempotent without ever
      leaving the document without content.
    - ``update_membership``: rewrites ``knowledge_ids`` (and
      ``membership_generation``) on all chunks of the document, preserving
      text/vector payloads - no re-embedding. An empty ``knowledge_ids``
      tuple is the tombstone signal: content is deleted, an empty array is
      never written. Stale membership generations are rejected (CAS).
    - ``delete_content``: idempotent delete by identity (version/generation
      may be None = whole document).

    Every method first validates the tenant routing snapshot: shared routing
    enabled, routing version unchanged (``expected_routing_version``),
    write not frozen, embedding model matching the tenant target and the
    collection schema fingerprint still the bootstrap fingerprint.
    """

    def __init__(
        self,
        *,
        tenant_id: int,
        collection: Collection,
        es_client: Any,
        expected_routing_version: int,
        schema_spec: SharedStoreSchemaSpec,
        conf=None,
        routing_provider: Callable[[int], TenantRoutingSnapshot | None] | None = None,
        embedding_model_validator: Callable[[int, TenantRoutingSnapshot], None] | None = None,
        migration_mode: bool = False,
    ) -> None:
        self.tenant_id = int(tenant_id)
        self.collection = collection
        self.es_client = es_client
        self.expected_routing_version = int(expected_routing_version)
        self.schema_spec = schema_spec
        self.conf = conf
        self._routing_provider = routing_provider or load_tenant_routing_snapshot
        self._embedding_model_validator = embedding_model_validator
        self._migration_mode = bool(migration_mode)

    # -- guards ---------------------------------------------------------------

    def _conf(self):
        return self.conf or get_shared_storage_conf()

    def _routing_snapshot(self) -> TenantRoutingSnapshot:
        conf = self._conf()
        if not conf.enabled:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED,
                "knowledge_space_shared_storage.enabled is off",
                tenant_id=self.tenant_id,
            )
        snapshot = self._routing_provider(self.tenant_id)
        if snapshot is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
                "no routing row for tenant",
                tenant_id=self.tenant_id,
            )
        return snapshot

    def _assert_writable(
        self, *, embedding_model_id: str | int | None = None
    ) -> TenantRoutingSnapshot:
        snapshot = self._routing_snapshot()
        if not snapshot.shared_enabled and not self._migration_mode:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED,
                "tenant is not routed to the shared store",
                tenant_id=self.tenant_id,
            )
        if int(snapshot.routing_version) != self.expected_routing_version:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_VERSION_MISMATCH,
                f"routing version moved from {self.expected_routing_version} "
                f"to {snapshot.routing_version} while the projection held its lease",
                tenant_id=self.tenant_id,
            )
        if (
            snapshot.write_frozen
            and self._conf().migration_write_block_enabled
            and not self._migration_mode
        ):
            raise SharedStorageContractError(
                SharedStorageErrorCode.TENANT_WRITE_FROZEN,
                "tenant SPACE writes are frozen for migration",
                tenant_id=self.tenant_id,
            )
        expected_fingerprint = snapshot.schema_fingerprint or self.schema_spec.fingerprint()
        verify_shared_collection_schema(
            self.collection, expected_fingerprint, tenant_id=self.tenant_id
        )
        self._check_embedding_model(embedding_model_id, snapshot)
        return snapshot

    def _check_embedding_model(
        self, embedding_model_id: str | int | None, snapshot: TenantRoutingSnapshot
    ) -> None:
        if self._embedding_model_validator is not None and embedding_model_id is not None:
            self._embedding_model_validator(int(str(embedding_model_id)), snapshot)
            return
        if embedding_model_id is None:
            return
        if snapshot.embedding_model_id is not None and int(str(embedding_model_id)) != int(
            snapshot.embedding_model_id
        ):
            raise SharedStorageContractError(
                SharedStorageErrorCode.EMBEDDING_MODEL_MISMATCH,
                f"embedding model {embedding_model_id} does not match tenant target "
                f"{snapshot.embedding_model_id}",
                tenant_id=self.tenant_id,
            )

    def _check_membership_limits(self, knowledge_ids: Sequence[int]) -> None:
        conf = self._conf()
        if len(knowledge_ids) > int(conf.knowledge_ids_max_capacity):
            raise SharedStorageContractError(
                SharedStorageErrorCode.MEMBERSHIP_CAPACITY_EXCEEDED,
                f"knowledge_ids length {len(knowledge_ids)} exceeds hard capacity "
                f"{conf.knowledge_ids_max_capacity}",
                tenant_id=self.tenant_id,
            )
        if len(knowledge_ids) > int(conf.knowledge_ids_soft_limit):
            # soft limit: warn only (spec 14.2)
            logger.warning(
                "shared_space membership soft limit exceeded: tenant=%s len=%d",
                self.tenant_id,
                len(knowledge_ids),
            )

    # -- helpers --------------------------------------------------------------

    def _es_index(self, snapshot: TenantRoutingSnapshot) -> str:
        return snapshot.index_name or shared_index_name(self.tenant_id, self._conf())

    def _milvus_call(self, method: str, *args, **kwargs):
        return getattr(self.collection, method)(*args, **kwargs)

    async def _run_milvus(self, method: str, *args, **kwargs):
        return await asyncio.to_thread(self._milvus_call, method, *args, **kwargs)

    async def _run_es(self, method: str, *args, **kwargs):
        client_method = getattr(self.es_client, method)
        return await asyncio.to_thread(client_method, *args, **kwargs)

    def _doc_expr(
        self,
        *,
        tenant_id: int,
        canonical_document_id: int,
        canonical_version_id: int | None = None,
        content_generation: int | None = None,
        generation_cmp: str | None = None,
    ) -> str:
        expr = (
            f"tenant_id == {int(tenant_id)} and "
            f"canonical_document_id == {int(canonical_document_id)}"
        )
        if canonical_version_id is not None:
            expr += f" and canonical_version_id == {int(canonical_version_id)}"
        if content_generation is not None:
            if generation_cmp not in (None, "=="):
                expr += f" and content_generation {generation_cmp} {int(content_generation)}"
            else:
                expr += f" and content_generation == {int(content_generation)}"
        return expr

    def _es_doc_query(
        self,
        *,
        tenant_id: int,
        canonical_document_id: int,
        canonical_version_id: int | None = None,
        content_generation: int | None = None,
        generation_lt: bool = False,
    ) -> dict[str, Any]:
        filters = [
            {"term": {"metadata.tenant_id": int(tenant_id)}},
            {"term": {"metadata.canonical_document_id": int(canonical_document_id)}},
        ]
        if canonical_version_id is not None:
            filters.append(
                {"term": {"metadata.canonical_version_id": int(canonical_version_id)}}
            )
        if content_generation is not None:
            if generation_lt:
                filters.append(
                    {
                        "range": {
                            "metadata.content_generation": {
                                "lt": int(content_generation)
                            }
                        }
                    }
                )
            else:
                filters.append(
                    {
                        "term": {
                            "metadata.content_generation": int(content_generation)
                        }
                    }
                )
        return {"bool": {"filter": filters}}

    # -- chunk rows ------------------------------------------------------------

    def _build_chunk_row(
        self,
        identity: Any,
        chunk: Any,
        knowledge_ids: Sequence[int],
        membership_generation: int,
    ) -> dict[str, Any]:
        metadata = dict(chunk.metadata or {})
        row: dict[str, Any] = {
            SHARED_MILVUS_TEXT_FIELD: chunk.text,
            "tenant_id": int(identity.tenant_id),
            "canonical_document_id": int(identity.canonical_document_id),
            "canonical_version_id": int(identity.canonical_version_id),
            "content_file_id": int(identity.content_file_id),
            "embedding_model_id": (
                str(identity.embedding_model_id)
                if identity.embedding_model_id is not None
                else None
            ),
            "chunk_index": int(chunk.chunk_index),
            "content_generation": int(identity.content_generation),
            "membership_generation": int(membership_generation),
            "knowledge_ids": [int(k) for k in knowledge_ids],
        }
        if chunk.vector is not None:
            row[SHARED_MILVUS_VECTOR_FIELD] = list(chunk.vector)
        # legacy scalar + display metadata carried over from chunk metadata
        row.setdefault("knowledge_id", int(knowledge_ids[0]) if knowledge_ids else None)
        for display_field in (
            "document_name",
            "abstract",
            "bbox",
            "page",
            "upload_time",
            "update_time",
            "uploader",
            "updater",
            "user_metadata",
        ):
            if display_field in metadata:
                row[display_field] = metadata[display_field]
        return row

    def _es_doc_id(self, identity: Any, chunk_index: int) -> str:
        return (
            f"{int(identity.tenant_id)}-{int(identity.canonical_document_id)}-"
            f"{int(identity.canonical_version_id)}-{int(identity.content_generation)}-"
            f"{int(chunk_index)}"
        )

    def _es_doc_source(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata_fields = {
            f.field_name
            for f in SHARED_SPACE_CONTENT_METADATA_SCHEMA
        }
        metadata = {k: v for k, v in row.items() if k in metadata_fields}
        source = {SHARED_MILVUS_TEXT_FIELD: row.get(SHARED_MILVUS_TEXT_FIELD)}
        source["metadata"] = metadata
        return source

    # -- contract implementation ----------------------------------------------

    async def upsert_content(self, request: ContentUpsertRequest) -> None:
        identity = request.identity
        if int(identity.tenant_id) != self.tenant_id:
            raise ValueError(
                f"writer is bound to tenant {self.tenant_id}, got "
                f"{identity.tenant_id}"
            )
        snapshot = self._assert_writable(
            embedding_model_id=identity.embedding_model_id
        )
        knowledge_ids = validate_knowledge_ids(request.knowledge_ids)
        self._check_membership_limits(knowledge_ids)

        # carry the membership generation forward so CAS on
        # update_membership keeps working across content rewrites
        membership_generation = await self._current_membership_generation(
            identity.tenant_id, identity.canonical_document_id
        )
        rows = [
            self._build_chunk_row(identity, chunk, knowledge_ids, membership_generation)
            for chunk in request.chunks
        ]

        same_gen_expr = self._doc_expr(
            tenant_id=identity.tenant_id,
            canonical_document_id=identity.canonical_document_id,
            canonical_version_id=identity.canonical_version_id,
            content_generation=identity.content_generation,
        )
        older_gen_expr = self._doc_expr(
            tenant_id=identity.tenant_id,
            canonical_document_id=identity.canonical_document_id,
            canonical_version_id=identity.canonical_version_id,
            content_generation=identity.content_generation,
            generation_cmp="<",
        )

        es_index = self._es_index(snapshot)
        es_routing_on = bool(self._conf().es_routing_enabled)

        # A completed retry must not delete the only durable copy before
        # rewriting it. Deterministic chunk indexes let us distinguish a
        # complete generation from a partial write left by a crashed attempt.
        existing = await self._run_milvus(
            "query",
            expr=same_gen_expr,
            output_fields=["chunk_index"],
            limit=_MILVUS_QUERY_BATCH,
        )
        expected_indexes = {int(row["chunk_index"]) for row in rows}
        existing_indexes = {
            int(row["chunk_index"])
            for row in existing
            if row.get("chunk_index") is not None
        }
        generation_complete = (
            len(existing) == len(rows) and existing_indexes == expected_indexes
        )
        if not generation_complete:
            await self._run_milvus("delete", expr=same_gen_expr)

        # 2) write the new generation (new first - a crash here can only
        #    duplicate, never lose content)
        if rows and not generation_complete:
            await self._run_milvus("insert", rows)
        for row in rows:
            es_kwargs: dict[str, Any] = {
                "index": es_index,
                "id": self._es_doc_id(identity, row["chunk_index"]),
                "document": self._es_doc_source(row),
            }
            if es_routing_on:
                es_kwargs["routing"] = es_routing_value(
                    identity.tenant_id, identity.canonical_document_id
                )
            await self._run_es("index", **es_kwargs)

        # 3) delete the old generation now that the new one is durable
        await self._run_milvus("delete", expr=older_gen_expr)
        await self._run_es(
            "delete_by_query",
            index=es_index,
            query=self._es_doc_query(
                tenant_id=identity.tenant_id,
                canonical_document_id=identity.canonical_document_id,
                canonical_version_id=identity.canonical_version_id,
                content_generation=identity.content_generation,
                generation_lt=True,
            ),
        )

    async def _current_membership_generation(
        self, tenant_id: int, canonical_document_id: int
    ) -> int:
        expr = (
            f"tenant_id == {int(tenant_id)} and "
            f"canonical_document_id == {int(canonical_document_id)}"
        )
        result = await self._run_milvus(
            "query",
            expr=expr,
            output_fields=["membership_generation"],
            limit=_MILVUS_QUERY_BATCH,
        )
        generations = [
            int(item.get("membership_generation") or 0)
            for item in (result or [])
        ]
        return max(generations) if generations else 0

    async def update_membership(self, request: MembershipUpdateRequest) -> None:
        if int(request.tenant_id) != self.tenant_id:
            raise ValueError(
                f"writer is bound to tenant {self.tenant_id}, got {request.tenant_id}"
            )
        snapshot = self._assert_writable()
        knowledge_ids = validate_knowledge_ids(request.knowledge_ids, allow_empty=True)

        if not knowledge_ids:
            # tombstone: the last active entry is gone - delete the content
            # projection, never write an empty array (nullable=false)
            doc_expr = self._doc_expr(
                tenant_id=request.tenant_id,
                canonical_document_id=request.canonical_document_id,
            )
            await self._run_milvus("delete", expr=doc_expr)
            await self._run_es(
                "delete_by_query",
                index=self._es_index(snapshot),
                query=self._es_doc_query(
                    tenant_id=request.tenant_id,
                    canonical_document_id=request.canonical_document_id,
                ),
            )
            return

        self._check_membership_limits(knowledge_ids)

        doc_expr = self._doc_expr(
            tenant_id=request.tenant_id,
            canonical_document_id=request.canonical_document_id,
            content_generation=request.content_generation,
        )
        existing = await self._run_milvus(
            "query", expr=doc_expr, output_fields=["*"], limit=_MILVUS_QUERY_BATCH
        )
        existing = list(existing or [])
        current_generation = max(
            (int(item.get("membership_generation") or 0) for item in existing),
            default=0,
        )
        if int(request.membership_generation) < current_generation:
            # stale generation - CAS reject (same semantics as the frozen fake)
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_VERSION_MISMATCH,
                f"stale membership generation {request.membership_generation} "
                f"< current {current_generation}",
                tenant_id=self.tenant_id,
            )
        if not existing:
            # content projection not written yet - membership will be applied
            # by the next upsert; nothing to rewrite
            return

        old_pks = [int(item[SHARED_MILVUS_PK_FIELD]) for item in existing]
        new_rows = []
        for item in existing:
            row = dict(item)
            row.pop(SHARED_MILVUS_PK_FIELD, None)
            row["knowledge_ids"] = [int(k) for k in knowledge_ids]
            row["membership_generation"] = int(request.membership_generation)
            new_rows.append(row)

        # write the rewritten rows first, then drop the old ones by pk
        await self._run_milvus("insert", new_rows)
        await self._run_milvus(
            "delete", expr=f"{SHARED_MILVUS_PK_FIELD} in {old_pks}"
        )

        script = {
            "source": (
                "ctx._source.metadata.knowledge_ids = params.knowledge_ids; "
                "ctx._source.metadata.membership_generation = params.membership_generation"
            ),
            "lang": "painless",
            "params": {
                "knowledge_ids": [int(k) for k in knowledge_ids],
                "membership_generation": int(request.membership_generation),
            },
        }
        es_index = self._es_index(snapshot)
        await asyncio.to_thread(self.es_client.indices.refresh, index=es_index)
        await self._run_es(
            "update_by_query",
            index=es_index,
            query=self._es_doc_query(
                tenant_id=request.tenant_id,
                canonical_document_id=request.canonical_document_id,
            ),
            script=script,
        )

    async def delete_content(self, request: ContentDeleteRequest) -> None:
        if int(request.tenant_id) != self.tenant_id:
            raise ValueError(
                f"writer is bound to tenant {self.tenant_id}, got {request.tenant_id}"
            )
        snapshot = self._assert_writable()
        expr = self._doc_expr(
            tenant_id=request.tenant_id,
            canonical_document_id=request.canonical_document_id,
            canonical_version_id=request.canonical_version_id,
            content_generation=request.content_generation,
        )
        await self._run_milvus("delete", expr=expr)
        await self._run_es(
            "delete_by_query",
            index=self._es_index(snapshot),
            query=self._es_doc_query(
                tenant_id=request.tenant_id,
                canonical_document_id=request.canonical_document_id,
                canonical_version_id=request.canonical_version_id,
                content_generation=request.content_generation,
            ),
        )


def build_shared_space_components_for_tenant(
    tenant_id: int,
    *,
    embedding_dimension: int | None = None,
    conf=None,
    routing_provider: Callable[[int], TenantRoutingSnapshot | None] | None = None,
) -> tuple[MilvusEsSharedSpaceStorageWriter, SharedSpaceStorageReader] | None:
    """Build the per-tenant writer+reader pair when the tenant is routed.

    Returns None when the tenant is not routed to the shared store (switch
    off / no row) so callers keep legacy behaviour. The shared collection
    must already exist - this factory never bootstraps (admin path only).

    ``embedding_dimension`` must be provided by the caller (the dimension of
    the tenant target embedding model); the spec derived from it must match
    the fingerprint stored in the routing row, otherwise the first write
    fails closed with ``SCHEMA_FINGERPRINT_MISMATCH``.
    """
    conf = conf or get_shared_storage_conf()
    if not conf.enabled:
        return None
    provider = routing_provider or load_tenant_routing_snapshot
    snapshot = provider(int(tenant_id))
    if snapshot is None or not snapshot.shared_enabled:
        return None
    if embedding_dimension is None and not snapshot.schema_fingerprint:
        raise SharedStorageContractError(
            SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
            "embedding_dimension of the tenant target model is required when "
            "the routing row carries no bootstrap fingerprint",
            tenant_id=int(tenant_id),
        )
    spec = SharedStoreSchemaSpec(
        embedding_model_id=snapshot.embedding_model_id or 0,
        # dimension is only used to recompute the fallback fingerprint; the
        # authoritative check is against the routing row's bootstrap
        # fingerprint, which the migration writes at switch time.
        dimension=int(embedding_dimension or 0),
        knowledge_ids_max_capacity=conf.knowledge_ids_max_capacity,
    )
    alias = _ensure_shared_milvus_connection()
    name = shared_collection_name(tenant_id, conf)
    if not utility.has_collection(name, using=alias):
        raise SharedStorageContractError(
            SharedStorageErrorCode.SCHEMA_FINGERPRINT_MISMATCH,
            f"shared collection {name} does not exist; run the admin "
            "bootstrap before routing the tenant",
            tenant_id=int(tenant_id),
        )
    collection = Collection(name, using=alias)
    expected_fingerprint = snapshot.schema_fingerprint or spec.fingerprint()
    verify_shared_collection_schema(collection, expected_fingerprint, tenant_id=int(tenant_id))

    from elasticsearch import Elasticsearch

    from bisheng.common.services.config_service import settings as bisheng_settings

    es_conf = bisheng_settings.get_vectors_conf().elasticsearch
    es_client = Elasticsearch(hosts=es_conf.elasticsearch_url, **es_conf.ssl_verify)

    writer = MilvusEsSharedSpaceStorageWriter(
        tenant_id=int(tenant_id),
        collection=collection,
        es_client=es_client,
        expected_routing_version=snapshot.routing_version,
        schema_spec=spec,
        conf=conf,
        routing_provider=provider,
    )
    reader = SharedSpaceStorageReader(
        tenant_id=int(tenant_id),
        collection=collection,
        es_client=es_client,
        expected_routing_version=snapshot.routing_version,
        conf=conf,
        routing_provider=provider,
    )
    return writer, reader


# ---------------------------------------------------------------------------
# the shared-store read client (F1, proposed reader contract pending review)
# ---------------------------------------------------------------------------

#: metadata fields returned to retrieval callers. Never includes raw chunk
#: payloads beyond what MappedEntryHit needs; callers must not forward
#: knowledge_ids arrays to clients (spec 8.1-8).
_READER_OUTPUT_FIELDS = [
    "canonical_document_id",
    "canonical_version_id",
    "chunk_index",
    "text",
]


class SharedSpaceStorageReader:
    """Read-only retrieval client for the tenant shared store.

    This is F1's proposed reader-side contract (to be promoted into
    ``domain/contracts`` after review): F3's resolver produces a
    ``BackendQueryFilter`` and this client renders it against Milvus (dense)
    and/or ES (BM25). Every read asserts the routing version (risk R16);
    reads stay available during a migration write freeze.

    Cross-backend score fusion / rerank is intentionally NOT done here - that
    stays with the B-layer retrievers (B1/B2) so the shared store stays a
    dumb, filterable store.
    """

    def __init__(
        self,
        *,
        tenant_id: int,
        collection: Collection,
        es_client: Any,
        expected_routing_version: int,
        conf=None,
        routing_provider: Callable[[int], TenantRoutingSnapshot | None] | None = None,
    ) -> None:
        self.tenant_id = int(tenant_id)
        self.collection = collection
        self.es_client = es_client
        self.expected_routing_version = int(expected_routing_version)
        self.conf = conf
        self._routing_provider = routing_provider or load_tenant_routing_snapshot

    def _assert_readable(self) -> TenantRoutingSnapshot:
        conf = self.conf or get_shared_storage_conf()
        if not conf.enabled:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED,
                "knowledge_space_shared_storage.enabled is off",
                tenant_id=self.tenant_id,
            )
        snapshot = self._routing_provider(self.tenant_id)
        if snapshot is None:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_NOT_CONFIGURED,
                "no routing row for tenant",
                tenant_id=self.tenant_id,
            )
        if not snapshot.shared_enabled:
            raise SharedStorageContractError(
                SharedStorageErrorCode.SHARED_STORAGE_NOT_ENABLED,
                "tenant is not routed to the shared store",
                tenant_id=self.tenant_id,
            )
        if int(snapshot.routing_version) != self.expected_routing_version:
            raise SharedStorageContractError(
                SharedStorageErrorCode.ROUTING_VERSION_MISMATCH,
                f"routing version moved from {self.expected_routing_version} "
                f"to {snapshot.routing_version}",
                tenant_id=self.tenant_id,
            )
        return snapshot

    @staticmethod
    def _full_expr(filter_: Any) -> str:
        """Membership pre-filter + optional canonical narrowing (spec 3.6)."""
        expr = build_milvus_membership_expr(filter_.tenant_id, filter_.requested_space_ids)
        if filter_.canonical_document_ids:
            ids = ", ".join(str(int(d)) for d in filter_.canonical_document_ids)
            expr += f" and canonical_document_id in [{ids}]"
        if filter_.canonical_version_ids:
            ids = ", ".join(str(int(v)) for v in filter_.canonical_version_ids)
            expr += f" and canonical_version_id in [{ids}]"
        return expr

    @staticmethod
    def _es_bool_filter(filter_: Any) -> list[dict[str, Any]]:
        clauses = build_shared_es_filter(filter_)
        if filter_.canonical_document_ids:
            clauses.append(
                {
                    "terms": {
                        "metadata.canonical_document_id": [
                            int(d) for d in filter_.canonical_document_ids
                        ]
                    }
                }
            )
        if filter_.canonical_version_ids:
            clauses.append(
                {
                    "terms": {
                        "metadata.canonical_version_id": [
                            int(v) for v in filter_.canonical_version_ids
                        ]
                    }
                }
            )
        return clauses

    @staticmethod
    def _to_hits(rows: Sequence[Any]) -> list[CanonicalChunkHit]:
        hits: list[CanonicalChunkHit] = []
        for row in rows:
            entity = getattr(row, "entity", row)
            get = entity.get if hasattr(entity, "get") else (lambda k, d=None: getattr(entity, k, d))
            hits.append(
                CanonicalChunkHit(
                    canonical_document_id=CanonicalDocumentId(int(get("canonical_document_id"))),
                    canonical_version_id=CanonicalVersionId(int(get("canonical_version_id"))),
                    chunk_index=int(get("chunk_index", 0) or 0),
                    score=float(getattr(row, "distance", getattr(row, "score", 0.0)) or 0.0),
                    text=get("text"),
                )
            )
        return hits

    async def search_milvus(
        self,
        filter_: Any,
        *,
        vector: Sequence[float],
        limit: int,
        search_params: Mapping[str, Any] | None = None,
    ) -> list[CanonicalChunkHit]:
        """Dense ANN search with membership pre-filter. Returns Top-K hits."""
        self._assert_readable()
        params = dict(search_params or {"metric_type": "L2", "params": {"ef": 64}})
        results = await asyncio.to_thread(
            self.collection.search,
            data=[list(vector)],
            anns_field=SHARED_MILVUS_VECTOR_FIELD,
            param=params,
            expr=self._full_expr(filter_),
            limit=int(limit),
            output_fields=list(_READER_OUTPUT_FIELDS),
        )
        rows = results[0] if results else []
        return self._to_hits(rows)

    async def search_es(
        self,
        filter_: Any,
        *,
        query_text: str,
        limit: int,
    ) -> list[CanonicalChunkHit]:
        """BM25 search on the shared index with membership pre-filter."""
        snapshot = self._assert_readable()
        body = {
            "size": int(limit),
            "query": {
                "bool": {
                    "must": [{"match": {"text": query_text}}],
                    "filter": self._es_bool_filter(filter_),
                }
            },
            "_source": ["metadata.canonical_document_id", "metadata.canonical_version_id", "metadata.chunk_index", "text"],
        }
        kwargs: dict[str, Any] = {"index": snapshot.index_name or shared_index_name(self.tenant_id), "body": body}
        if (
            (self.conf or get_shared_storage_conf()).es_routing_enabled
            and filter_.canonical_document_ids
        ):
            kwargs["routing"] = ",".join(
                es_routing_value(self.tenant_id, document_id)
                for document_id in filter_.canonical_document_ids
            )
        response = await asyncio.to_thread(self.es_client.search, **kwargs)
        hits: list[CanonicalChunkHit] = []
        for row in response.get("hits", {}).get("hits", []):
            source = row.get("_source", {})
            metadata = source.get("metadata", {})
            hits.append(
                CanonicalChunkHit(
                    canonical_document_id=CanonicalDocumentId(
                        int(metadata["canonical_document_id"])
                    ),
                    canonical_version_id=CanonicalVersionId(
                        int(metadata["canonical_version_id"])
                    ),
                    chunk_index=int(metadata.get("chunk_index", 0) or 0),
                    score=float(row.get("_score", 0.0) or 0.0),
                    text=source.get("text"),
                )
            )
        return hits


__all__ = [
    "MilvusEsSharedSpaceStorageWriter",
    "SharedCollectionBootstrapResult",
    "SharedSpaceStorageReader",
    "SharedStoreSchemaSpec",
    "SHARED_MILVUS_PK_FIELD",
    "SHARED_MILVUS_TEXT_FIELD",
    "SHARED_MILVUS_VECTOR_FIELD",
    "SHARED_STORE_KIND",
    "SHARED_STORE_SCHEMA_VERSION",
    "TenantRoutingSnapshot",
    "bootstrap_shared_collection",
    "build_milvus_membership_expr",
    "build_shared_es_filter",
    "build_shared_es_index_body",
    "build_shared_field_schemas",
    "build_shared_space_components_for_tenant",
    "ensure_shared_es_index",
    "es_routing_value",
    "get_shared_storage_conf",
    "load_tenant_routing_snapshot",
    "parse_collection_description_payload",
    "resolve_space_shared_routing",
    "shared_collection_name",
    "shared_index_alias",
    "shared_index_name",
    "tenant_target_embedding_model_id",
    "verify_shared_collection_schema",
]
