"""Locked model/server facts and the existing Root-default sharing policy.

Only repositories execute SQL. No DAO opens a second session and neither
entry point commits. Auxiliary defaults contribute locks, never bindings.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import and_, false, or_
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
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
    is_preserved_foreign_model_reference,
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
        self._prelock_key = object()

    @staticmethod
    def _sources(source_keys):
        if not isinstance(source_keys, tuple) or not source_keys:
            raise ResourceReferenceInvalidError(reason="reference_batch_sources_required")
        for key in source_keys:
            _tenant(key, "bind")
        if (
            len(set(source_keys)) != len(source_keys)
            or len({(key.tenant_id, key.source_type, key.source_id) for key in source_keys}) != 1
        ):
            raise ResourceReferenceInvalidError(reason="reference_batch_root_mismatch")
        return tuple(sorted(source_keys, key=lambda key: key.source_version))

    @staticmethod
    def _mixed_sources(source_keys):
        if not isinstance(source_keys, tuple) or not source_keys:
            raise ResourceReferenceInvalidError(reason="reference_mixed_sources_required")
        for key in source_keys:
            _tenant(key, "bind")
            if (
                key.source_type not in (SourceType.KNOWLEDGE, SourceType.MODEL_DEFAULT)
                or key.source_version != "current"
            ):
                raise ResourceReferenceInvalidError(reason="reference_mixed_source_scope_invalid")
        if len(set(source_keys)) != len(source_keys):
            raise ResourceReferenceInvalidError(reason="reference_mixed_source_duplicate")
        return tuple(sorted(source_keys, key=lambda key: (key.source_type.value, key.source_id, key.source_version)))

    def _prelock_proof(self, session, source_key, operation):
        proof = session.info.get(self._prelock_key)
        if operation != "bind" or proof is None or proof[0] is not TransactionIdentity.capture(session).transaction:
            return None
        if source_key not in proof[1]:
            roots = {(key.tenant_id, key.source_type, key.source_id) for key in proof[1]}
            if len(roots) > 1 or (source_key.tenant_id, source_key.source_type, source_key.source_id) in roots:
                raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
            return None
        return proof

    @staticmethod
    def _ids(column, ids):
        values = sorted(ids)
        return (
            or_(*(column.in_(values[start : start + 200]) for start in range(0, len(values), 200)))
            if values
            else false()
        )

    @staticmethod
    def _tombstone_statements(targets):
        # Tombstone's physical ID is VARCHAR. Sort the entire set in that
        # index's lexicographic order before batching, never numeric chunks.
        # Server/Model locks stay numeric; returned observations do too.
        ordered = sorted(targets, key=lambda item: (item[0].target_type.value, item[0].target_id, item[1]))
        for start in range(0, len(ordered), 200):
            groups = {}
            for key, owner in ordered[start : start + 200]:
                groups.setdefault((key.target_type.value, owner), []).append(key.target_id)
            yield (
                select(ResourceReferenceTombstone)
                .where(
                    or_(
                        *(
                            and_(
                                ResourceReferenceTombstone.target_type == kind,
                                ResourceReferenceTombstone.target_id.in_(ids),
                                ResourceReferenceTombstone.target_tenant_id == owner,
                                ResourceReferenceTombstone.tenant_id == owner,
                            )
                            for (kind, owner), ids in groups.items()
                        )
                    )
                )
                .order_by(
                    ResourceReferenceTombstone.target_type,
                    ResourceReferenceTombstone.target_id,
                    ResourceReferenceTombstone.target_tenant_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )

    @classmethod
    def _business_statement(cls, model, ids, owners, *, lock):
        statement = (
            select(model)
            .where(cls._ids(model.id, ids), model.tenant_id.in_(owners))
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
        return bool(root and child and child.id != ROOT_TENANT_ID and child.parent_tenant_id == ROOT_TENANT_ID)

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

    @classmethod
    def _original_statement(cls, source, keys):
        return (
            select(BusinessResourceReference)
            .where(
                BusinessResourceReference.source_type == source.source_type.value,
                BusinessResourceReference.source_id == source.source_id,
                BusinessResourceReference.source_version == source.source_version,
                BusinessResourceReference.target_type == TargetType.MODEL.value,
                cls._ids(BusinessResourceReference.target_id, {key.target_id for key in keys}),
            )
            .execution_options(populate_existing=True)
        )

    @classmethod
    def _binding_inherited_ids(cls, topology, configs, tenant_id, source_key, overridden_keys=frozenset()):
        # Eligibility must survive every own override in this mixed plan.
        # These keys come only from the transaction's original physical plan.
        excluded = set(overridden_keys)
        if source_key is not None and source_key.source_type == SourceType.MODEL_DEFAULT:
            excluded.add(source_key.source_id)
        if tenant_id != ROOT_TENANT_ID and excluded:
            configs = tuple(row for row in configs if not (row.tenant_id == ROOT_TENANT_ID and row.key in excluded))
        return cls._inherited_ids(topology, configs, tenant_id)

    def _lock_plan(self, target_keys, source_key, operation, *, session=None, prelock_sources=None, mixed=False):
        tenant_id = _tenant(source_key, operation)
        if not isinstance(target_keys, tuple) or any(
            not isinstance(key, TargetKey) or key.target_type != TargetType.MODEL for key in target_keys
        ):
            raise ResourceReferenceInvalidError(reason="model_reference_target_type_invalid")
        keys = tuple(sorted(set(target_keys), key=lambda key: key.lock_order_key))
        proof = self._prelock_proof(session, source_key, operation) if prelock_sources is None else None
        overridden_keys = (
            frozenset(key.source_id for key in prelock_sources if key.source_type == SourceType.MODEL_DEFAULT)
            if mixed
            else proof[6]
            if proof is not None
            else frozenset()
        )
        originals = []
        sources = prelock_sources if prelock_sources is not None else (source_key,) if source_key else ()
        for source in sources:
            if keys:
                originals.extend((yield self._original_statement(source, keys), False))
        ids = {int(key.target_id) for key in keys}
        owners = (tenant_id, ROOT_TENANT_ID) if operation == "bind" else (tenant_id,)
        if operation == "bind":
            preserved_owners = set()
            for row in originals:
                if row.target_tenant_id not in (*owners, None):
                    if not any(
                        is_preserved_foreign_model_reference(
                            row, source_key=source, target=key, target_tenant_id=row.target_tenant_id
                        )
                        for source in sources
                        for key in keys
                    ):
                        raise ResourceReferenceInvalidError(reason="model_reference_target_unavailable")
                    preserved_owners.add(row.target_tenant_id)
            owners = tuple(sorted(set(owners) | preserved_owners))
        candidates = yield self._business_statement(LLMModel, ids, owners, lock=False), True
        needs_sharing = any(row.tenant_id != tenant_id for row in candidates)
        candidate_topology, candidate_configs = {}, []
        if needs_sharing:
            candidate_topology = {row.id: row for row in (yield self._topology_statement(tenant_id, lock=False), True)}
            candidate_configs = yield self._config_statement(tenant_id, lock=False), True
        inherited_ids = (
            frozenset().union(
                *(
                    self._binding_inherited_ids(
                        candidate_topology, candidate_configs, tenant_id, source, overridden_keys
                    )
                    for source in sources
                )
            )
            if prelock_sources is not None
            else self._binding_inherited_ids(
                candidate_topology, candidate_configs, tenant_id, source_key, overridden_keys
            )
        )
        all_ids = ids | inherited_ids
        all_candidates = yield self._business_statement(LLMModel, all_ids, owners, lock=False), True
        mapping = {row.id: row.server_id for row in all_candidates}
        server_ids = {value for value in mapping.values() if type(value) is int and value > 0}
        if proof is not None and (not set(keys) <= proof[2] or not all_ids <= proof[3] or not server_ids <= proof[4]):
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
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
            current_inherited = (
                frozenset().union(
                    *(
                        self._binding_inherited_ids(topology, configs, tenant_id, source, overridden_keys)
                        for source in sources
                    )
                )
                if prelock_sources is not None
                else self._binding_inherited_ids(topology, configs, tenant_id, source_key, overridden_keys)
            )
            if current_inherited != inherited_ids:
                raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
            inherited_servers = frozenset(
                row.server_id
                for row in models.values()
                if row.id in inherited_ids
                and row.tenant_id == ROOT_TENANT_ID
                and row.server_id in servers
                and servers[row.server_id].tenant_id == ROOT_TENANT_ID
            )
        elif mixed:
            # Default roots also need this actual policy topology. Lock it in
            # the target phase before any Knowledge root, even for own models;
            # an unrelated default JSON never becomes a sharing dependency.
            yield self._topology_statement(tenant_id, lock=True), True
        if prelock_sources is not None:
            # Union only physical target/owner locks. Never choose one source's
            # legacy evidence for another source/version and never issue facts.
            tombstones = {(key, models[int(key.target_id)].tenant_id) for key in keys if int(key.target_id) in models}
            tombstones.update(
                (TargetKey(row.target_type, row.target_id), row.target_tenant_id)
                for row in originals
                if row.target_tenant_id is not None
            )
            for statement in self._tombstone_statements(tombstones):
                yield statement, True
            return (
                (),
                tenant_id,
                inherited_servers,
                (
                    sources,
                    frozenset(keys),
                    frozenset(all_ids),
                    frozenset(server_ids),
                    frozenset(tombstones),
                    overridden_keys,
                ),
            )
        originals_by_target = {}
        for original in originals:
            originals_by_target.setdefault(original.target_id, []).append(original)
        facts = []
        for key in keys:
            row, original = models.get(int(key.target_id)), _original(originals_by_target.get(key.target_id, ()), key)
            server = servers.get(row.server_id) if row else None
            if row is not None and (
                server is None
                or server.tenant_id != row.tenant_id
                or (
                    row.tenant_id != tenant_id
                    and (row.tenant_id != ROOT_TENANT_ID or not self._child(topology, tenant_id))
                    and not is_preserved_foreign_model_reference(
                        original, source_key=source_key, target=key, target_tenant_id=row.tenant_id
                    )
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
            if owner is not None:
                if proof is not None and (key, owner) not in proof[5]:
                    raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
            facts.append((key, row, original, server, owner))
        tombstones = {}
        for statement in self._tombstone_statements(
            {(key, owner) for key, _, _, _, owner in facts if owner is not None}
        ):
            for tombstone in (yield statement, True):
                tombstones[(TargetKey(tombstone.target_type, tombstone.target_id), tombstone.target_tenant_id)] = (
                    tombstone
                )
        result = []
        for key, row, original, server, owner in facts:
            tombstone = tombstones.get((key, owner))
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
        observations, tenant_id, inherited_servers = result[:3]
        if len(result) == 4:
            session.info[self._prelock_key] = (TransactionIdentity.capture(session).transaction, *result[3])
        session.info[self._sharing_proof_key] = (
            TransactionIdentity.capture(session).transaction,
            tenant_id,
            inherited_servers,
        )
        return observations

    def _drive(self, session, plan):
        value = None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                return self._remember(session, done.value)
            value = self._read(session, statement, cross_scope)

    async def _adrive(self, session, plan):
        value = None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                return self._remember(session, done.value)
            value = await self._aread(session, statement, cross_scope)

    def lock_targets(self, session, target_keys, source_key, operation):
        return self._drive(session, self._lock_plan(target_keys, source_key, operation, session=session))

    async def alock_targets(self, session, target_keys, source_key, operation):
        return await self._adrive(session, self._lock_plan(target_keys, source_key, operation, session=session))

    def prelock_targets(self, session, target_keys, source_keys):
        sources = self._sources(source_keys)
        self._drive(session, self._lock_plan(target_keys, sources[0], "bind", session=session, prelock_sources=sources))

    async def aprelock_targets(self, session, target_keys, source_keys):
        sources = self._sources(source_keys)
        await self._adrive(
            session, self._lock_plan(target_keys, sources[0], "bind", session=session, prelock_sources=sources)
        )

    async def aprelock_mixed_targets(self, session, target_keys, source_keys):
        sources = self._mixed_sources(source_keys)
        await self._adrive(
            session,
            self._lock_plan(target_keys, sources[0], "bind", session=session, prelock_sources=sources, mixed=True),
        )

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
