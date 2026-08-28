"""F1 shared-space storage adapter tests (naming / routing / fingerprint /
filter rendering / create+delete routing guards / reader).

No live Milvus/ES: pymilvus Collection and es clients are fakes/mocks. The
switch-off invariant ("enabled=False or no routing row -> zero behaviour
change") is asserted throughout.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bisheng.core.config.settings import KnowledgeSpaceSharedStorageConf
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.retrieval_scope import (
    BackendQueryFilter,
    CanonicalGenerationConstraint,
)
from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentDeleteRequest,
    MembershipUpdateRequest,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
    KnowledgeSpaceSharedStorageRouting,
)
from bisheng.knowledge.rag import shared_space_storage as sss
from bisheng.knowledge.rag.shared_space_storage import (
    SharedSpaceStorageReader,
    TenantRoutingSnapshot,
    build_milvus_membership_expr,
    build_shared_es_filter,
    resolve_space_shared_routing,
    shared_collection_name,
    shared_index_name,
)


def _conf(**overrides) -> KnowledgeSpaceSharedStorageConf:
    return KnowledgeSpaceSharedStorageConf(enabled=True, **overrides)


def _snapshot(
    tenant_id: int = 1,
    *,
    shared_enabled: bool = True,
    routing_version: int = 3,
    write_frozen: bool = False,
    index_name: str | None = "idx_space_shared_1",
) -> TenantRoutingSnapshot:
    return TenantRoutingSnapshot(
        tenant_id=tenant_id,
        shared_enabled=shared_enabled,
        routing_version=routing_version,
        write_frozen=write_frozen,
        collection_name="col_space_shared_1",
        index_name=index_name,
        embedding_model_id=7,
        schema_fingerprint="fp",
        migration_state="",
    )


class TestNaming:
    def test_shared_names_use_prefix_and_tenant(self):
        conf = _conf(collection_prefix="col_x", index_prefix="idx_x")
        assert shared_collection_name(42, conf) == "col_x_42"
        assert shared_index_name(42, conf) == "idx_x_42"


class TestSharedEsIndexSettings:
    def test_default_primary_shard_count_is_three(self):
        body = sss.build_shared_es_index_body(_conf())
        assert body["settings"]["number_of_shards"] == 3

    def test_configured_primary_shard_count_is_used(self):
        body = sss.build_shared_es_index_body(_conf(es_number_of_shards=6))
        assert body["settings"]["number_of_shards"] == 6

    @pytest.mark.parametrize("value", [0, 65])
    def test_primary_shard_count_outside_supported_range_is_rejected(self, value):
        with pytest.raises(ValueError):
            _conf(es_number_of_shards=value)


class TestResolveRouting:
    def test_switch_off_returns_none(self):
        provider = lambda tenant_id: _snapshot()  # noqa: E731
        assert (
            resolve_space_shared_routing(
                1, KnowledgeTypeEnum.SPACE.value, conf=KnowledgeSpaceSharedStorageConf(),
                routing_provider=provider,
            )
            is None
        )

    def test_non_space_type_returns_none(self):
        assert (
            resolve_space_shared_routing(
                1, KnowledgeTypeEnum.NORMAL.value, conf=_conf(), routing_provider=lambda t: _snapshot()
            )
            is None
        )

    def test_no_routing_row_returns_none(self):
        assert resolve_space_shared_routing(1, KnowledgeTypeEnum.SPACE.value, conf=_conf(), routing_provider=lambda t: None) is None

    def test_space_tenant_enabled_returns_snapshot(self):
        snapshot = resolve_space_shared_routing(
            1, KnowledgeTypeEnum.SPACE.value, conf=_conf(), routing_provider=lambda t: _snapshot()
        )
        assert snapshot is not None and snapshot.routing_version == 3

    def test_snapshot_from_row_roundtrip(self):
        row = KnowledgeSpaceSharedStorageRouting(
            tenant_id=5, shared_enabled=True, routing_version=9, write_frozen=True
        )
        snap = TenantRoutingSnapshot.from_row(row)
        assert (snap.tenant_id, snap.shared_enabled, snap.routing_version, snap.write_frozen) == (5, True, 9, True)


class TestMembershipFilter:
    def test_single_space_uses_array_contains(self):
        expr = build_milvus_membership_expr(1, [11])
        assert expr == "tenant_id == 1 and ARRAY_CONTAINS(knowledge_ids, 11)"

    def test_multi_space_uses_array_contains_any(self):
        expr = build_milvus_membership_expr(1, [11, 12, 13])
        assert expr == (
            "tenant_id == 1 and ARRAY_CONTAINS_ANY(knowledge_ids, [11, 12, 13])"
        )

    def test_empty_spaces_rejected(self):
        with pytest.raises(ValueError):
            build_milvus_membership_expr(1, [])

    def test_es_filter_terms(self):
        filter_ = BackendQueryFilter(
            tenant_id=1, requested_space_ids=(11, 12), routing_version=1
        )
        clauses = build_shared_es_filter(filter_)
        assert {"term": {"metadata.tenant_id": 1}} in clauses
        assert {"terms": {"metadata.knowledge_ids": [11, 12]}} in clauses


class _FakeEntity:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeHit:
    def __init__(self, data, score):
        self.entity = _FakeEntity(data)
        self.distance = score


class TestSharedSpaceStorageReader:
    def _reader(self, *, routing_version: int = 3, enabled: bool = True):
        conf = _conf() if enabled else KnowledgeSpaceSharedStorageConf()
        collection = SimpleNamespace(
            search=lambda **kw: [[_FakeHit(
                {
                    "canonical_document_id": 10,
                    "canonical_version_id": 100,
                    "content_generation": 4,
                    "membership_generation": 5,
                    "chunk_index": 0,
                    "text": "hello",
                },
                0.42,
            )]]
        )
        es_client = SimpleNamespace(
            search=lambda **kw: {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.5,
                            "_source": {
                                "text": "hello",
                                "metadata": {
                                    "canonical_document_id": 10,
                                    "canonical_version_id": 100,
                                    "content_generation": 4,
                                    "membership_generation": 5,
                                    "chunk_index": 0,
                                },
                            },
                        }
                    ]
                }
            }
        )
        return SharedSpaceStorageReader(
            tenant_id=1,
            collection=collection,
            es_client=es_client,
            expected_routing_version=routing_version,
            conf=conf,
            routing_provider=lambda t: _snapshot(),
        )

    async def test_milvus_search_renders_membership_expr(self):
        reader = self._reader()
        filter_ = BackendQueryFilter(
            tenant_id=1, requested_space_ids=(11,), routing_version=3
        )
        hits = await reader.search_milvus(filter_, vector=[0.1] * 4, limit=5)
        assert len(hits) == 1
        assert hits[0].canonical_document_id == 10
        assert hits[0].score == pytest.approx(0.42)
        assert hits[0].content_generation == 4

    async def test_es_search_returns_canonical_hits(self):
        reader = self._reader()
        filter_ = BackendQueryFilter(
            tenant_id=1, requested_space_ids=(11, 12), routing_version=3
        )
        hits = await reader.search_es(filter_, query_text="hello", limit=5)
        assert hits[0].canonical_version_id == 100
        assert hits[0].score == pytest.approx(1.5)

    async def test_es_routing_only_used_for_canonical_document_queries(self):
        calls = []
        reader = self._reader()
        reader.conf = _conf(es_routing_enabled=True)
        reader.es_client.search = lambda **kwargs: (
            calls.append(kwargs) or {"hits": {"hits": []}}
        )

        await reader.search_es(
            BackendQueryFilter(
                tenant_id=1,
                requested_space_ids=(11,),
                routing_version=3,
            ),
            query_text="hello",
            limit=5,
        )
        await reader.search_es(
            BackendQueryFilter(
                tenant_id=1,
                requested_space_ids=(11,),
                routing_version=3,
                canonical_document_ids=(10, 11),
            ),
            query_text="hello",
            limit=5,
        )

        assert "routing" not in calls[0]
        assert calls[1]["routing"] == "1-10,1-11"


class TestESQueryRendering:
    _reader = TestSharedSpaceStorageReader._reader

    def test_older_generation_uses_range_query(self):
        writer = object.__new__(sss.MilvusEsSharedSpaceStorageWriter)
        query = writer._es_doc_query(
            tenant_id=1,
            canonical_document_id=10,
            content_generation=3,
            generation_lt=True,
        )
        assert {
            "range": {"metadata.content_generation": {"lt": 3}}
        } in query["bool"]["filter"]

    async def test_routing_version_mismatch_fails_closed(self):
        reader = self._reader(routing_version=2)
        filter_ = BackendQueryFilter(
            tenant_id=1, requested_space_ids=(11,), routing_version=3
        )
        with pytest.raises(SharedStorageContractError) as exc:
            await reader.search_milvus(filter_, vector=[0.1] * 4, limit=5)
        assert exc.value.code == SharedStorageErrorCode.ROUTING_VERSION_MISMATCH

    async def test_reads_available_during_write_freeze(self):
        conf = _conf()
        reader = SharedSpaceStorageReader(
            tenant_id=1,
            collection=SimpleNamespace(search=lambda **kw: []),
            es_client=SimpleNamespace(),
            expected_routing_version=3,
            conf=conf,
            routing_provider=lambda t: _snapshot(write_frozen=True),
        )
        filter_ = BackendQueryFilter(tenant_id=1, requested_space_ids=(11,), routing_version=3)
        assert await reader.search_milvus(filter_, vector=[0.1] * 4, limit=5) == []

    def test_full_expr_adds_canonical_narrowing(self):
        filter_ = BackendQueryFilter(
            tenant_id=1,
            requested_space_ids=(11,),
            routing_version=3,
            canonical_document_ids=(10, 11),
        )
        expr = SharedSpaceStorageReader._full_expr(filter_)
        assert "ARRAY_CONTAINS(knowledge_ids, 11)" in expr
        assert "canonical_document_id in [10, 11]" in expr

    def test_generation_constraints_are_pushed_to_both_backends(self):
        constraint = CanonicalGenerationConstraint(
            canonical_document_id=10,
            canonical_version_id=100,
            content_generation=4,
            membership_generation=5,
        )
        filter_ = BackendQueryFilter(
            tenant_id=1,
            requested_space_ids=(11,),
            routing_version=3,
            generation_constraints=(constraint,),
        )

        expr = SharedSpaceStorageReader._full_expr(filter_)
        es_filter = SharedSpaceStorageReader._es_bool_filter(filter_)

        assert "content_generation == 4" in expr
        assert "membership_generation == 5" in expr
        generation_bool = es_filter[-1]["bool"]
        assert generation_bool["minimum_should_match"] == 1
        terms = generation_bool["should"][0]["bool"]["filter"]
        assert {"term": {"metadata.content_generation": 4}} in terms
        assert {"term": {"metadata.membership_generation": 5}} in terms


class TestSchemaFingerprint:
    def test_fingerprint_stable_for_same_spec(self):
        spec_a = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
            metric_type="L2",
            index_params={"index_type": "HNSW"},
            knowledge_ids_max_capacity=4096,
        )
        spec_b = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
            metric_type="L2",
            index_params={"index_type": "HNSW"},
            knowledge_ids_max_capacity=4096,
        )
        assert spec_a.fingerprint() == spec_b.fingerprint()

    def test_fingerprint_changes_on_dimension(self):
        base = dict(embedding_model_id=7, dimension=1024, metric_type="L2",
                    index_params={"index_type": "HNSW"}, knowledge_ids_max_capacity=4096)
        other = sss.SharedStoreSchemaSpec(dimension=768, **{k: v for k, v in base.items() if k != "dimension"})
        assert sss.SharedStoreSchemaSpec(**base).fingerprint() != other.fingerprint()


class TestMembershipRewrite:
    async def test_retry_converges_duplicate_canonical_chunks(self):
        writer = object.__new__(sss.MilvusEsSharedSpaceStorageWriter)
        writer.tenant_id = 1
        writer.schema_spec = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
        )
        asserted_models = []
        writer._assert_writable = lambda **kwargs: (
            asserted_models.append(kwargs.get("embedding_model_id")) or _snapshot()
        )
        writer._check_membership_limits = lambda _ids: None
        writer._conf = lambda: _conf()
        writer.es_client = SimpleNamespace(
            indices=SimpleNamespace(refresh=lambda **_kwargs: None)
        )
        calls = []

        async def milvus(method, *args, **kwargs):
            calls.append((method, args, kwargs))
            if method == "query":
                return [
                    {
                        "pk": 1,
                        "canonical_version_id": 9,
                        "content_generation": 2,
                        "membership_generation": 1,
                        "chunk_index": 0,
                        "knowledge_ids": [10],
                    },
                    {
                        "pk": 2,
                        "canonical_version_id": 9,
                        "content_generation": 2,
                        "membership_generation": 2,
                        "chunk_index": 0,
                        "knowledge_ids": [10],
                    },
                    {
                        "pk": 3,
                        "canonical_version_id": 9,
                        "content_generation": 2,
                        "membership_generation": 2,
                        "chunk_index": 1,
                        "knowledge_ids": [10],
                    },
                ]
            return None

        async def es(method, *args, **kwargs):
            calls.append((f"es:{method}", args, kwargs))

        writer._run_milvus = milvus
        writer._run_es = es

        await writer.update_membership(
            MembershipUpdateRequest(
                tenant_id=1,
                canonical_document_id=8,
                knowledge_ids=(10, 20),
                membership_generation=3,
                content_generation=2,
            )
        )

        insert = next(call for call in calls if call[0] == "insert")
        delete_call = next(call for call in calls if call[0] == "delete")
        assert len(insert[1][0]) == 2
        assert {row["chunk_index"] for row in insert[1][0]} == {0, 1}
        assert delete_call[2]["expr"] == "pk in [1, 2, 3]"
        assert asserted_models == [7]

    async def test_delete_validates_bound_embedding_model(self):
        async def noop(*_args, **_kwargs):
            return None

        writer = object.__new__(sss.MilvusEsSharedSpaceStorageWriter)
        writer.tenant_id = 1
        writer.schema_spec = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
        )
        asserted_models = []
        writer._assert_writable = lambda **kwargs: (
            asserted_models.append(kwargs.get("embedding_model_id")) or _snapshot()
        )
        writer._run_milvus = noop
        writer._run_es = noop

        await writer.delete_content(
            ContentDeleteRequest(tenant_id=1, canonical_document_id=8)
        )

        assert asserted_models == [7]


class TestSharedCollectionBootstrap:
    def test_created_collection_is_loaded_before_copy_queries(self):
        spec = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
            knowledge_ids_max_capacity=4096,
        )
        calls = []

        class FakeCollection:
            description = spec.description_payload()

            def set_properties(self, properties):
                calls.append(("set_properties", properties))

            def create_index(self, field_name, index_body):
                calls.append(("create_index", field_name, index_body))

            def load(self):
                calls.append(("load",))

        result = sss.bootstrap_shared_collection(
            spec,
            tenant_id=1,
            collection_factory=lambda name, schema, description, alias: FakeCollection(),
        )

        assert result.created is True
        assert ("load",) in calls

    def test_existing_collection_is_loaded_before_copy_queries(self):
        spec = sss.SharedStoreSchemaSpec(
            embedding_model_id=7,
            dimension=1024,
            knowledge_ids_max_capacity=4096,
        )
        calls = []
        collection = SimpleNamespace(
            name="col_space_shared_1",
            description=spec.description_payload(),
            load=lambda: calls.append(("load",)),
        )

        with (
            patch.object(sss, "_ensure_shared_milvus_connection", return_value="alias"),
            patch.object(sss.utility, "has_collection", return_value=True),
            patch.object(sss, "Collection", return_value=collection),
        ):
            result = sss.bootstrap_shared_collection(spec, tenant_id=1)

        assert result.created is False
        assert calls == [("load",)]


class TestCreateDeleteRoutingGuards:
    def test_create_space_uses_shared_names_when_routed(self):
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        knowledge = SimpleNamespace(
            type=KnowledgeTypeEnum.SPACE.value,
            index_name=None,
            collection_name=None,
            tenant_id=1,
        )
        login_user = SimpleNamespace(user_id="u1", tenant_id=1)
        with patch(
            "bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf",
            return_value=_conf(),
        ), patch(
            "bisheng.knowledge.rag.shared_space_storage.load_tenant_routing_snapshot",
            return_value=_snapshot(),
        ), patch(
            "bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao"
        ) as dao_cls, patch.object(KnowledgeService, "create_knowledge_hook"):
            dao_cls.insert_one.return_value = knowledge
            KnowledgeService.create_knowledge_base(None, login_user, knowledge, skip_hook=True)
        assert knowledge.collection_name == "col_space_shared_1"
        assert knowledge.index_name == "idx_space_shared_1"

    def test_create_space_keeps_legacy_names_when_switch_off(self):
        from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

        knowledge = SimpleNamespace(
            type=KnowledgeTypeEnum.SPACE.value,
            index_name=None,
            collection_name=None,
            tenant_id=1,
        )
        login_user = SimpleNamespace(user_id="u1", tenant_id=1)
        with patch(
            "bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf",
            return_value=KnowledgeSpaceSharedStorageConf(),
        ), patch.object(KnowledgeService, "create_knowledge_hook"):
            with patch("bisheng.knowledge.domain.services.knowledge_service.KnowledgeDao"):
                KnowledgeService.create_knowledge_base(None, login_user, knowledge, skip_hook=True)
        assert knowledge.collection_name is not None
        assert knowledge.collection_name != "col_space_shared_1"

    def test_delete_skips_shared_store_when_routed(self):
        from bisheng.api.services import knowledge_imp

        knowledge = SimpleNamespace(
            id=33,
            type=KnowledgeTypeEnum.SPACE.value,
            tenant_id=1,
            collection_name="col_space_shared_1",
            index_name="idx_space_shared_1",
        )
        with patch(
            "bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf",
            return_value=_conf(),
        ), patch(
            "bisheng.knowledge.rag.shared_space_storage.load_tenant_routing_snapshot",
            return_value=_snapshot(),
        ), patch.object(knowledge_imp, "KnowledgeRag") as rag:
            knowledge_imp.delete_vector_files([1, 2], knowledge)
            rag.init_knowledge_milvus_vectorstore_sync.assert_not_called()

        with patch(
            "bisheng.knowledge.rag.shared_space_storage.get_shared_storage_conf",
            return_value=KnowledgeSpaceSharedStorageConf(),
        ), patch.object(knowledge_imp, "KnowledgeRag") as rag:
            knowledge_imp.delete_vector_files([1, 2], knowledge)
            rag.init_knowledge_milvus_vectorstore_sync.assert_called_once()
