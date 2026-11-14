"""Read-only full-source admission before consuming a business model slot."""

import json
from dataclasses import dataclass

from bisheng.common.errcode.knowledge import (
    KnowledgeNoEmbeddingError,
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.knowledge.application.reference_read_identity import KnowledgeModelReadIdentityPort
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_contracts import SourceReadRequest, SourceReferenceReadResult
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

_SLOTS = frozenset({"model", "model_transition.pending_model_id"})


@dataclass(frozen=True, slots=True)
class AdmittedKnowledgeModel:
    read: SourceReferenceReadResult
    model_id: int
    slot_key: str
    knowledge_id: int
    tenant_id: int
    operation_id: str | None
    model_config_revision: int
    index_generation: str | None


class KnowledgeModelReadRuntime:
    def __init__(self, core, identity_port, repository=None):
        if (
            not isinstance(core, ReferenceSourceReadRuntime)
            or not isinstance(identity_port, KnowledgeModelReadIdentityPort)
            or core.verifier._identity_port is not identity_port
        ):
            raise TypeError("Knowledge model reads require one actual Core and its same private identity port")
        self.core = core
        self.identity_port = identity_port
        self.repository = repository if repository is not None else KnowledgeModelReferenceRepository()

    @staticmethod
    def _result(read, slot_key, expected_operation_id, expected_model_config_revision, expected_index_generation):
        if slot_key not in _SLOTS:
            raise ResourceReferenceInvalidError(reason="knowledge_model_business_slot_required")
        row = json.loads(read.snapshot.payload_json)["knowledge"]
        transition = row["model_transition"]
        operation = transition["operation_id"] if transition is not None else None
        if (
            (expected_operation_id is not None and operation != expected_operation_id)
            or (
                expected_model_config_revision is not None
                and row["model_config_revision"] != expected_model_config_revision
            )
            or (expected_index_generation is not None and row["index_generation"] != expected_index_generation)
        ):
            raise KnowledgeOperationPlanConflictError(reason="knowledge_model_operation_obsolete")
        selected = next((item for item in read.snapshot.references if item.slot_key == slot_key), None)
        if selected is None:
            if slot_key == "model":
                raise KnowledgeNoEmbeddingError()
            raise ResourceReferenceInvalidError(reason="knowledge_model_business_slot_missing")
        return AdmittedKnowledgeModel(
            read,
            int(selected.target.target_id),
            slot_key,
            row["id"],
            row["tenant_id"],
            operation,
            row["model_config_revision"],
            row["index_generation"],
        )

    def require(
        self,
        knowledge_id,
        login_user=None,
        session=None,
        slot_key="model",
        *,
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
    ):
        if session is None:
            with get_sync_db_session() as active:
                return self.require(
                    knowledge_id,
                    login_user,
                    active,
                    slot_key,
                    expected_operation_id=expected_operation_id,
                    expected_model_config_revision=expected_model_config_revision,
                    expected_index_generation=expected_index_generation,
                )
        identity = self.identity_port.issue(session, knowledge_id, login_user=login_user)
        scope = self.core.verifier.issue_scope(
            session, SourceReadRequest(SourceType.KNOWLEDGE, str(knowledge_id), "current"), identity
        )
        read = self.core.require_source_valid(session, scope, identity)
        return self._result(
            read, slot_key, expected_operation_id, expected_model_config_revision, expected_index_generation
        )

    async def arequire(
        self,
        knowledge_id,
        login_user=None,
        session=None,
        slot_key="model",
        *,
        expected_operation_id=None,
        expected_model_config_revision=None,
        expected_index_generation=None,
    ):
        if session is None:
            async with get_async_db_session() as active:
                return await self.arequire(
                    knowledge_id,
                    login_user,
                    active,
                    slot_key,
                    expected_operation_id=expected_operation_id,
                    expected_model_config_revision=expected_model_config_revision,
                    expected_index_generation=expected_index_generation,
                )
        identity = await self.identity_port.aissue(session, knowledge_id, login_user=login_user)
        scope = await self.core.verifier.aissue_scope(
            session, SourceReadRequest(SourceType.KNOWLEDGE, str(knowledge_id), "current"), identity
        )
        read = await self.core.arequire_source_valid(session, scope, identity)
        return self._result(
            read, slot_key, expected_operation_id, expected_model_config_revision, expected_index_generation
        )


_runtime: KnowledgeModelReadRuntime | None = None


def configure_knowledge_model_read_runtime(runtime: KnowledgeModelReadRuntime | None):
    global _runtime
    if runtime is not None and not isinstance(runtime, KnowledgeModelReadRuntime):
        raise TypeError("Knowledge model reads require an explicitly assembled runtime")
    _runtime = runtime


def get_knowledge_model_read_runtime_sync() -> KnowledgeModelReadRuntime:
    if _runtime is None:
        raise ReferenceCoverageNotReadyError(reason="knowledge_model_read_runtime_unconfigured")
    return _runtime


async def get_knowledge_model_read_runtime() -> KnowledgeModelReadRuntime:
    return get_knowledge_model_read_runtime_sync()
