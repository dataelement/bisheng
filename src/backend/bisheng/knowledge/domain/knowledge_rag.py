import json
from collections.abc import Sequence

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_elasticsearch import AsyncElasticsearchStore, ElasticsearchStore
from langchain_milvus import Milvus

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.knowledge import (
    KnowledgeEmbeddingUnavailableError,
    KnowledgeUnificationError,
    ResourceReferenceInvalidError,
)
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.ai import FakeEmbeddings
from bisheng.core.database import get_sync_db_session
from bisheng.knowledge.application.model_reference_read import (
    get_knowledge_model_read_runtime,
    get_knowledge_model_read_runtime_sync,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    KnowledgePermissionService,
)
from bisheng.knowledge.rag.elasticsearch_factory import ElasticsearchFactory
from bisheng.knowledge.rag.milvus_factory import MilvusFactory
from bisheng.llm.domain import LLMService
from bisheng.resource_reference.application.contracts import canonical_target_id
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.async_utils import run_async_safe

ROOT_TENANT_ID = 1


class KnowledgeRag:
    """initialize knowledge rag components"""

    # ── F017 AC-06: Milvus / ES fallback helpers ──────────────────

    @classmethod
    async def _aget_usable_knowledge(
        cls,
        user_name: str,
        knowledge_ids: list[int],
    ) -> list[Knowledge]:
        if not knowledge_ids:
            return []
        user_info = await UserDao.aget_user_by_username(user_name)
        if user_info is None:
            return []

        from bisheng.user.domain.services.auth import LoginUser

        login_user = await LoginUser.init_login_user(
            user_id=user_info.user_id,
            user_name=user_name,
        )
        rows = await KnowledgeDao.aget_list_by_ids(knowledge_ids)
        usable_ids = await cls.afilter_usable_knowledge_ids(login_user, [int(row.id) for row in rows])
        return [row for row in rows if int(row.id) in usable_ids]

    @classmethod
    async def afilter_usable_knowledge_ids(
        cls,
        login_user,
        knowledge_ids: Sequence[int],
    ) -> set[int]:
        """Which of ``knowledge_ids`` may ``login_user`` actually use?

        The one rule behind 用户知识库权限校验 for ordinary knowledge bases, shared
        by the workflow retrieval node and the assistant. The assistant had no
        rule here at all: it built a retriever straight off each bound knowledge
        id, so a user granted only the assistant still searched knowledge bases
        they had no access to. An absent identity resolves to nothing usable.
        """
        normalized = [int(knowledge_id) for knowledge_id in knowledge_ids]
        if not normalized or login_user is None:
            return set()
        action_map = await KnowledgePermissionService.get_knowledge_action_map_async(
            login_user,
            normalized,
            ["use"],
        )
        return {knowledge_id for knowledge_id in normalized if "use" in action_map.get(knowledge_id, set())}

    @classmethod
    def _get_usable_knowledge(
        cls,
        user_name: str,
        knowledge_ids: list[int],
    ) -> list[Knowledge]:
        return run_async_safe(
            cls._aget_usable_knowledge(user_name, knowledge_ids),
            timeout=60,
        )

    @classmethod
    async def aexpand_with_root_shared(
        cls,
        knowledge_ids: Sequence[int],
        *,
        leaf_tenant_id: int | None = None,
    ) -> list[int]:
        """Return ``knowledge_ids`` plus every Root-shared knowledge id the
        caller can see (``tenant_id=1 AND is_shared=1``).

        Used at the retrieval layer so a Child-tenant conversation can
        cross-search its own collections + the Root-shared knowledge the
        tenant has been granted via F017 FGA tuples. Call this *before*
        ``get_multi_knowledge_vectorstore_sync`` when the caller needs
        the "Child + Root-shared" union (spec §5.3 Milvus fallback).

        No-ops (returns the input unchanged) when:
          - ``leaf_tenant_id`` is Root (already sees every Root knowledge)
          - multi_tenant is disabled
          - there are no Root-shared knowledge rows matching

        Dedups by id; preserves the caller's order for the original ids
        and appends the new Root-shared ids at the tail.
        """
        base_ids = list(dict.fromkeys(int(k) for k in knowledge_ids))
        if leaf_tenant_id is None:
            try:
                from bisheng.core.context.tenant import get_current_tenant_id

                leaf_tenant_id = get_current_tenant_id()
            except Exception:
                leaf_tenant_id = None
        if leaf_tenant_id is None or leaf_tenant_id == ROOT_TENANT_ID:
            return base_ids

        try:
            from bisheng.common.services.config_service import settings

            if not getattr(getattr(settings, "multi_tenant", None), "enabled", False):
                return base_ids
        except Exception:
            return base_ids

        root_shared = await cls._afetch_root_shared_knowledge_ids()
        if not root_shared:
            return base_ids
        seen = set(base_ids)
        for kid in root_shared:
            if kid not in seen:
                seen.add(kid)
                base_ids.append(kid)
        return base_ids

    @classmethod
    async def _afetch_root_shared_knowledge_ids(cls) -> list[int]:
        """Fetch all Root knowledge ids that are currently shared
        (``is_shared=1``). Query the ``knowledge`` table directly with a
        bypass_tenant_filter so the ORM's auto-inject does not filter them
        out for a Child caller.
        """
        from sqlalchemy import text as sa_text

        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session

        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    sa_text("SELECT id FROM knowledge WHERE tenant_id = :t AND is_shared = 1").bindparams(
                        t=ROOT_TENANT_ID
                    )
                )
                rows = result.all()
        return [int(r[0]) if isinstance(r, tuple) else int(r) for r in rows]

    @classmethod
    async def _get_knowledge(
        cls,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
    ) -> Knowledge:
        if not knowledge:
            knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
            if not knowledge:
                raise NotFoundError.http_exception()
        return knowledge

    @classmethod
    def _get_knowledge_sync(
        cls,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
    ):
        if not knowledge:
            knowledge = KnowledgeDao.query_by_id(knowledge_id)
            if not knowledge:
                raise NotFoundError.http_exception()
        return knowledge

    @staticmethod
    def _resource_id(knowledge, knowledge_id):
        try:
            actual = canonical_target_id(knowledge.id if knowledge is not None else knowledge_id)
            if knowledge_id is not None and actual != canonical_target_id(knowledge_id):
                raise ValueError("conflicting Knowledge identities")
            return int(actual)
        except (AttributeError, TypeError, ValueError) as error:
            raise ResourceReferenceInvalidError(reason="knowledge_rag_resource_identity") from error

    @staticmethod
    def _current_knowledge(result, candidate):
        current = json.loads(result.read.snapshot.payload_json)["knowledge"]
        original = candidate.model_dump() if isinstance(candidate, Knowledge) else {}
        return Knowledge(**{**original, **current})

    @classmethod
    def _model_source_sync(cls, knowledge, knowledge_id=None, **scope):
        result = get_knowledge_model_read_runtime_sync().require(cls._resource_id(knowledge, knowledge_id), **scope)
        return cls._current_knowledge(result, knowledge), result.model_id

    @classmethod
    async def _model_source(cls, knowledge, knowledge_id=None, **scope):
        runtime = await get_knowledge_model_read_runtime()
        result = await runtime.arequire(cls._resource_id(knowledge, knowledge_id), **scope)
        return cls._current_knowledge(result, knowledge), result.model_id

    @staticmethod
    def _scope(
        login_user,
        reference_session,
        model_slot,
        expected_operation_id,
        expected_model_config_revision,
        expected_index_generation,
    ):
        return {
            "login_user": login_user,
            "session": reference_session,
            "slot_key": model_slot,
            "expected_operation_id": expected_operation_id,
            "expected_model_config_revision": expected_model_config_revision,
            "expected_index_generation": expected_index_generation,
        }

    @staticmethod
    async def _embedding(knowledge, model_id, invoke_user_id):
        try:
            return await LLMService.get_bisheng_knowledge_embedding(model_id=model_id, invoke_user_id=invoke_user_id)
        except KnowledgeUnificationError:
            raise
        except Exception as error:
            raise KnowledgeEmbeddingUnavailableError(
                knowledge_name=knowledge.name, knowledge_id=knowledge.id
            ) from error

    @staticmethod
    def _cleanup_knowledge(knowledge, deletion_job):
        if not isinstance(knowledge, Knowledge):
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_resource_required")
        try:
            KnowledgeModelReferenceRepository._tenant_id()
        except NoTenantContextError as error:
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_resource_required") from error
        knowledge_id = KnowledgeRag._resource_id(knowledge, None)
        with get_sync_db_session() as session:
            actual = KnowledgeModelReferenceRepository().load_cleanup_identity(
                session, knowledge_id, deletion_job=deletion_job
            )
        if any(
            getattr(knowledge, key) != actual.get(key)
            for key in ("id", "tenant_id", "type", "index_name", "collection_name")
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_index_changed")
        if not isinstance(actual.get("collection_name"), str) or not actual["collection_name"]:
            raise ResourceReferenceInvalidError(reason="knowledge_cleanup_index_required")
        # Cleanup consumes only the verified existing index identity; unrelated
        # processing/model JSON must not become a management deletion gate.
        return Knowledge(
            **{key: actual.get(key) for key in ("id", "tenant_id", "type", "name", "index_name", "collection_name")}
        )

    @classmethod
    def init_knowledge_milvus_cleanup_sync(cls, knowledge, *, deletion_job=None):
        actual = cls._cleanup_knowledge(knowledge, deletion_job)
        return cls.init_milvus_vectorstore(actual.collection_name, FakeEmbeddings())

    @classmethod
    def init_knowledge_es_cleanup_sync(cls, knowledge, *, deletion_job=None):
        actual = cls._cleanup_knowledge(knowledge, deletion_job)
        return cls.init_es_vectorstore_sync(actual.index_name or actual.collection_name)

    @classmethod
    async def init_knowledge_milvus_vectorstore(
        cls,
        invoke_user_id: int,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
        embeddings=None,
        *,
        login_user=None,
        reference_session=None,
        model_slot="model",
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
        **kwargs,
    ) -> Milvus:
        knowledge, model_id = await cls._model_source(
            knowledge,
            knowledge_id,
            **cls._scope(
                login_user,
                reference_session,
                model_slot,
                expected_operation_id,
                expected_model_config_revision,
                expected_index_generation,
            ),
        )
        if embeddings is None:
            embeddings = await cls._embedding(knowledge, model_id, invoke_user_id)
        return cls.init_milvus_vectorstore(knowledge.collection_name, embeddings, **kwargs)

    @classmethod
    def init_knowledge_milvus_vectorstore_sync(
        cls,
        invoke_user_id: int,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
        embeddings=None,
        *,
        login_user=None,
        reference_session=None,
        model_slot="model",
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
        **kwargs,
    ) -> Milvus:
        knowledge, model_id = cls._model_source_sync(
            knowledge,
            knowledge_id,
            **cls._scope(
                login_user,
                reference_session,
                model_slot,
                expected_operation_id,
                expected_model_config_revision,
                expected_index_generation,
            ),
        )
        if embeddings is None:
            embeddings = LLMService.get_bisheng_knowledge_embedding_sync(
                model_id=model_id, invoke_user_id=invoke_user_id
            )
        return cls.init_milvus_vectorstore(knowledge.collection_name, embeddings, **kwargs)

    @classmethod
    async def init_knowledge_es_vectorstore(
        cls,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
        *,
        login_user=None,
        reference_session=None,
        model_slot="model",
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
        **kwargs,
    ) -> AsyncElasticsearchStore:
        knowledge, _ = await cls._model_source(
            knowledge,
            knowledge_id,
            **cls._scope(
                login_user,
                reference_session,
                model_slot,
                expected_operation_id,
                expected_model_config_revision,
                expected_index_generation,
            ),
        )
        return cls.init_es_vectorstore(knowledge.index_name, **kwargs)

    @classmethod
    def init_knowledge_es_vectorstore_sync(
        cls,
        knowledge: Knowledge | None = None,
        knowledge_id: int | None = None,
        *,
        login_user=None,
        reference_session=None,
        model_slot="model",
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
        **kwargs,
    ) -> ElasticsearchStore:
        knowledge, _ = cls._model_source_sync(
            knowledge,
            knowledge_id,
            **cls._scope(
                login_user,
                reference_session,
                model_slot,
                expected_operation_id,
                expected_model_config_revision,
                expected_index_generation,
            ),
        )
        return cls.init_es_vectorstore_sync(knowledge.index_name, **kwargs)

    @classmethod
    def get_multi_knowledge_vectorstore_sync(
        cls,
        invoke_user_id: int,
        knowledge_ids: list[int],
        user_name: str | None = None,
        check_auth: bool = True,
        include_es: bool = True,
        include_milvus: bool = True,
        *,
        login_user=None,
    ) -> dict[int, dict[str, VectorStore | Knowledge]]:
        """get multiple knowledge vectorstore, including milvus and es
        return: {
            knowledge_id: {
                "knowledge": Knowledge
                "milvus": Milvus,
                "es": ElasticsearchStore,
            },
        }
        """
        if not include_es and not include_milvus:
            raise RuntimeError("at least one of include_es and include_milvus must be True")

        if check_auth:
            if not user_name:
                raise RuntimeError("knowledge check auth user_name must be provided")
            knowledge_list = cls._get_usable_knowledge(
                user_name,
                knowledge_ids,
            )
        else:
            knowledge_list = KnowledgeDao.get_list_by_ids(knowledge_ids)
        ret = {}
        for knowledge in knowledge_list:
            knowledge, model_id = cls._model_source_sync(knowledge, login_user=login_user)
            ret[knowledge.id] = {
                "knowledge": knowledge,
                "milvus": None,
                "es": None,
            }
            if include_milvus:
                embedding = LLMService.get_bisheng_knowledge_embedding_sync(
                    model_id=model_id, invoke_user_id=invoke_user_id
                )
                vectorstore = cls.init_milvus_vectorstore(knowledge.collection_name, embedding)
                ret[knowledge.id]["milvus"] = vectorstore
            if include_es:
                es_vectorstore = cls.init_es_vectorstore_sync(knowledge.index_name)
                ret[knowledge.id]["es"] = es_vectorstore
        return ret

    @classmethod
    async def get_multi_knowledge_vectorstore(
        cls,
        invoke_user_id: int,
        knowledge_ids: list[int],
        user_name: str | None = None,
        check_auth: bool = True,
        include_es: bool = True,
        include_milvus: bool = True,
        *,
        login_user=None,
    ) -> dict[int, dict[str, VectorStore | Knowledge]]:
        """get multiple knowledge vectorstore, including milvus and es
        return: {
            knowledge_id: {
                "knowledge": Knowledge
                "milvus": Milvus,
                "es": ElasticsearchStore,
            },
        }
        """

        if knowledge_ids is None or len(knowledge_ids) == 0:
            return {}

        if not include_es and not include_milvus:
            raise RuntimeError("at least one of include_es and include_milvus must be True")
        if check_auth:
            if not user_name:
                raise RuntimeError("knowledge check auth user_name must be provided")
            knowledge_list = await cls._aget_usable_knowledge(
                user_name,
                knowledge_ids,
            )
        else:
            knowledge_list = await KnowledgeDao.aget_list_by_ids(knowledge_ids)
        ret = {}
        for knowledge in knowledge_list:
            knowledge, model_id = await cls._model_source(knowledge, login_user=login_user)
            ret[knowledge.id] = {
                "knowledge": knowledge,
                "milvus": None,
                "es": None,
            }
            if include_milvus:
                embedding = await cls._embedding(knowledge, model_id, invoke_user_id)
                vectorstore = cls.init_milvus_vectorstore(knowledge.collection_name, embedding)
                ret[knowledge.id]["milvus"] = vectorstore
            if include_es:
                es_vectorstore = cls.init_es_vectorstore(knowledge.index_name)
                ret[knowledge.id]["es"] = es_vectorstore
        return ret

    @classmethod
    def init_milvus_vectorstore(cls, collection_name: str, embeddings: Embeddings, **kwargs) -> Milvus:
        """init milvus vectorstore by collection name and model id"""
        return MilvusFactory.init_vectorstore(collection_name, embeddings, **kwargs)

    @classmethod
    def init_es_vectorstore(cls, index_name: str, **kwargs) -> AsyncElasticsearchStore:
        """init es vectorstore by index name"""
        return ElasticsearchFactory.init_vectorstore(index_name, **kwargs)

    @classmethod
    def init_es_vectorstore_sync(cls, index_name: str, **kwargs) -> ElasticsearchStore:
        """init es vectorstore by index name"""
        return ElasticsearchFactory.init_vectorstore_sync(index_name, **kwargs)
