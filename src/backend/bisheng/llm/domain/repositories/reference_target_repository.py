"""Locked model/server facts and the existing Root-default sharing policy.

Only repositories execute SQL. No DAO opens a second session and neither
entry point commits. Auxiliary defaults contribute locks, never bindings.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlmodel import select

from bisheng.common.errcode.knowledge import (
    ReferenceCoverageNotReadyError,
    ResourceReferenceConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfig
from bisheng.llm.domain.schemas import AssistantLLMConfig, EvaluationLLMConfig, KnowledgeLLMConfig, WorkbenchModelConfig
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    SourceKey,
    TargetKey,
    TargetType,
    TransactionIdentity,
)
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone

DEFAULT_SCHEMAS = {
    "knowledge_llm": KnowledgeLLMConfig,
    "assistant_llm": AssistantLLMConfig,
    "evaluation_llm": EvaluationLLMConfig,
    "workflow_llm": EvaluationLLMConfig,
    "linsight_llm": WorkbenchModelConfig,
}


def _tenant(source_key, operation):
    value = _resolve_tenant_id()
    if is_tenant_filter_bypassed() or type(value) is not int or value <= 0:
        raise ResourceReferenceInvalidError(reason="reference_target_tenant_required")
    if (
        (operation == "bind" and (not isinstance(source_key, SourceKey) or source_key.tenant_id != value))
        or (operation == "owner_query" and source_key is not None)
        or operation not in {"bind", "owner_query"}
    ):
        raise ResourceReferenceInvalidError(reason="source_tenant_mismatch")
    return value


def _revision(*rows):
    payload = [
        {column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows if row is not None
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _original(rows, key):
    matches = [row for row in rows if row.target_id == key.target_id]
    if not matches:
        return None
    if (
        len(
            {
                (
                    row.target_tenant_id,
                    row.target_space_id,
                    row.legacy_invalid_reason,
                    row.legacy_run_id,
                    row.legacy_evidence_key,
                )
                for row in matches
            }
        )
        != 1
    ):
        raise ResourceReferenceInvalidError(reason="reference_original_evidence_conflict")
    return matches[0]


@dataclass(frozen=True)
class ModelTargetObservation:
    key: TargetKey
    exists: bool
    target_tenant_id: int | None
    model_server_id: str | None
    target_revision: str
    original: BusinessResourceReference | None
    deletion: DeletionEvidence | None


class ModelReferenceTargetRepository:
    def __init__(self):
        # Private, transaction-bound proof stored on the caller's session. No
        # process-global registry or session-retaining cache is introduced.
        self._sharing_proof_key = object()

    @staticmethod
    def _business_statement(model, ids, owners, *, lock):
        statement = (
            select(model)
            .where(model.id.in_(sorted(ids)), model.tenant_id.in_(owners))
            .order_by(model.id)
            .execution_options(populate_existing=True)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _topology_statement(tenant_id, *, lock):
        statement = (
            select(Tenant)
            .where(Tenant.id.in_([ROOT_TENANT_ID, tenant_id]))
            .order_by(Tenant.id)
            .execution_options(populate_existing=True)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _config_statement(tenant_id, *, lock):
        statement = (
            select(TenantSystemModelConfig)
            .where(
                TenantSystemModelConfig.tenant_id.in_([ROOT_TENANT_ID, tenant_id]),
                TenantSystemModelConfig.key.in_(tuple(DEFAULT_SCHEMAS)),
            )
            .order_by(TenantSystemModelConfig.tenant_id, TenantSystemModelConfig.key)
            .execution_options(populate_existing=True)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _child(topology, tenant_id):
        root, child = topology.get(ROOT_TENANT_ID), topology.get(tenant_id)
        return bool(
            root
            and child
            and root.status == "active"
            and child.status == "active"
            and child.id != ROOT_TENANT_ID
            and child.parent_tenant_id == ROOT_TENANT_ID
        )

    @classmethod
    def _inherited_ids(cls, topology, configs, tenant_id):
        if not cls._child(topology, tenant_id) or not topology[ROOT_TENANT_ID].share_default_to_children:
            return frozenset()
        by_key = {(row.tenant_id, row.key): row.value for row in configs}
        raw_ids = []
        for key, schema in DEFAULT_SCHEMAS.items():
            if by_key.get((tenant_id, key)) or not by_key.get((ROOT_TENANT_ID, key)):
                continue
            config = schema.model_validate_json(by_key[ROOT_TENANT_ID, key])
            if isinstance(config, KnowledgeLLMConfig):
                raw_ids.extend(
                    getattr(config, name)
                    for name in (
                        "embedding_model_id",
                        "source_model_id",
                        "extract_title_model_id",
                        "qa_similar_model_id",
                        "asr_model_id",
                    )
                )
            elif isinstance(config, AssistantLLMConfig):
                raw_ids.extend(item.model_id for item in (config.llm_list or ()))
                raw_ids.append(config.auto_llm.model_id if config.auto_llm else None)
            elif isinstance(config, EvaluationLLMConfig):
                raw_ids.append(config.model_id)
            else:
                raw_ids.extend(item.id for item in (config.models or ()))
                raw_ids.extend((config.linsight_default_model_id, config.chat_default_model_id))
                raw_ids.extend(
                    getattr(config, name).id
                    for name in ("embedding_model", "asr_model", "tts_model", "chat_title_llm", "image_read_model")
                    if getattr(config, name) is not None
                )
        return frozenset(
            int(value)
            for value in raw_ids
            if not isinstance(value, bool)
            and isinstance(value, (str, int))
            and str(value).isascii()
            and str(value).isdecimal()
            and int(value) > 0
        )

    @staticmethod
    def _original_statement(source, keys):
        return (
            select(BusinessResourceReference)
            .where(
                BusinessResourceReference.source_type == source.source_type.value,
                BusinessResourceReference.source_id == source.source_id,
                BusinessResourceReference.source_version == source.source_version,
                BusinessResourceReference.target_type == TargetType.MODEL.value,
                BusinessResourceReference.target_id.in_([key.target_id for key in keys]),
            )
            .execution_options(populate_existing=True)
        )

    def _lock_plan(self, target_keys, source_key, operation):
        tenant_id = _tenant(source_key, operation)
        if not isinstance(target_keys, tuple) or any(
            not isinstance(key, TargetKey) or key.target_type != TargetType.MODEL for key in target_keys
        ):
            raise ResourceReferenceInvalidError(reason="model_reference_target_type_invalid")
        keys = tuple(sorted(set(target_keys), key=lambda key: key.lock_order_key))
        originals = yield (self._original_statement(source_key, keys) if source_key and keys else None), False
        # None statements are skipped by the sync/async drivers.
        originals = originals if source_key and keys else []
        ids = {int(key.target_id) for key in keys}
        owners = (tenant_id, ROOT_TENANT_ID) if operation == "bind" else (tenant_id,)
        candidates = yield self._business_statement(LLMModel, ids, owners, lock=False), True
        needs_sharing = any(row.tenant_id != tenant_id for row in candidates)
        candidate_topology, candidate_configs = {}, []
        if needs_sharing:
            candidate_topology = {row.id: row for row in (yield self._topology_statement(tenant_id, lock=False), True)}
            candidate_configs = yield self._config_statement(tenant_id, lock=False), True
        inherited_ids = self._inherited_ids(candidate_topology, candidate_configs, tenant_id)
        all_ids = ids | inherited_ids
        all_candidates = yield self._business_statement(LLMModel, all_ids, owners, lock=False), True
        mapping = {row.id: row.server_id for row in all_candidates}
        server_ids = {value for value in mapping.values() if type(value) is int and value > 0}
        servers = {
            row.id: row for row in (yield self._business_statement(LLMServer, server_ids, owners, lock=True), True)
        }
        models = {row.id: row for row in (yield self._business_statement(LLMModel, all_ids, owners, lock=True), True)}
        if {row.id: row.server_id for row in models.values()} != mapping:
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
        inherited_servers = frozenset()
        topology = {}
        if needs_sharing:
            topology = {row.id: row for row in (yield self._topology_statement(tenant_id, lock=True), True)}
            configs = yield self._config_statement(tenant_id, lock=True), True
            if self._inherited_ids(topology, configs, tenant_id) != inherited_ids:
                raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
            inherited_servers = frozenset(
                row.server_id
                for row in models.values()
                if row.id in inherited_ids
                and row.tenant_id == ROOT_TENANT_ID
                and row.server_id in servers
                and servers[row.server_id].tenant_id == ROOT_TENANT_ID
            )
        result = []
        for key in keys:
            row, original = models.get(int(key.target_id)), _original(originals, key)
            server = servers.get(row.server_id) if row else None
            if row is not None and (
                server is None
                or server.tenant_id != row.tenant_id
                or (
                    row.tenant_id != tenant_id
                    and (row.tenant_id != ROOT_TENANT_ID or not self._child(topology, tenant_id))
                )
            ):
                raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
            owner = (
                row.tenant_id
                if row
                else original.target_tenant_id
                if original
                else (tenant_id if operation == "owner_query" else None)
            )
            tombstone = None
            if owner is not None:
                tombstones = yield (
                    select(ResourceReferenceTombstone)
                    .where(
                        ResourceReferenceTombstone.target_type == TargetType.MODEL.value,
                        ResourceReferenceTombstone.target_id == key.target_id,
                        ResourceReferenceTombstone.target_tenant_id == owner,
                        ResourceReferenceTombstone.tenant_id == owner,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True),
                    True,
                )
                tombstone = tombstones[0] if tombstones else None
            deletion = DeletionEvidence(tombstone.operation_id, key, owner, tombstone.stage) if tombstone else None
            result.append(
                ModelTargetObservation(
                    key,
                    row is not None,
                    owner,
                    str(row.server_id) if row else None,
                    _revision(row, server, tombstone),
                    original,
                    deletion,
                )
            )
        return tuple(result), tenant_id, inherited_servers

    @staticmethod
    def _read(session, statement, cross_scope):
        if statement is None:
            return []
        with bypass_tenant_filter() if cross_scope else strict_tenant_filter():
            return list(session.execute(statement).scalars())

    @staticmethod
    async def _aread(session, statement, cross_scope):
        if statement is None:
            return []
        with bypass_tenant_filter() if cross_scope else strict_tenant_filter():
            return list((await session.execute(statement)).scalars())

    def _remember(self, session, result):
        observations, tenant_id, inherited_servers = result
        session.info[self._sharing_proof_key] = (
            TransactionIdentity.capture(session).transaction,
            tenant_id,
            inherited_servers,
        )
        return observations

    def lock_targets(self, session, target_keys, source_key, operation):
        plan, value = self._lock_plan(target_keys, source_key, operation), None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                return self._remember(session, done.value)
            value = self._read(session, statement, cross_scope)

    async def alock_targets(self, session, target_keys, source_key, operation):
        plan, value = self._lock_plan(target_keys, source_key, operation), None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                return self._remember(session, done.value)
            value = await self._aread(session, statement, cross_scope)

    def get_inherited_default_server_ids(self, session, tenant_id):
        proof = session.info.get(self._sharing_proof_key)
        if (
            proof is None
            or proof[:2] != (TransactionIdentity.capture(session).transaction, tenant_id)
            or _resolve_tenant_id() != tenant_id
        ):
            raise ReferenceCoverageNotReadyError(reason="model_reference_share_plan_unavailable")
        return proof[2]

    async def aget_inherited_default_server_ids(self, session, tenant_id):
        # Pure consumption of this transaction's already locked SQL proof.
        return self.get_inherited_default_server_ids(session, tenant_id)
