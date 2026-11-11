"""Current, locked knowledge facts for the reference target Owner.

The caller owns the transaction. Source reads are candidate evidence only;
the reference writer subsequently locks/CAS-checks the source root and set.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import load_only
from sqlmodel import select

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_delete_job import KnowledgeSpaceDeleteJob
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    SourceKey,
    TargetDeleteStage,
    TargetKey,
    TargetType,
    TransactionIdentity,
    is_preserved_foreign_space_reference,
)
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone


def current_tenant(source_key, operation):
    tenant_id = _resolve_tenant_id()
    if is_tenant_filter_bypassed() or type(tenant_id) is not int or tenant_id <= 0:
        raise ResourceReferenceInvalidError(reason="reference_target_tenant_required")
    if (
        (operation == "bind" and (not isinstance(source_key, SourceKey) or source_key.tenant_id != tenant_id))
        or (operation == "owner_query" and source_key is not None)
        or operation not in {"bind", "owner_query"}
    ):
        raise ResourceReferenceInvalidError(reason="source_tenant_mismatch")
    return tenant_id


def original_statements(source, keys):
    ordered = sorted(keys, key=lambda key: (key.target_type.value, key.target_id))
    model = BusinessResourceReference
    for start in range(0, len(ordered), 200):
        groups = {}
        for key in ordered[start : start + 200]:
            groups.setdefault(key.target_type.value, []).append(key.target_id)
        yield (
            select(model)
            .where(
                model.source_type == source.source_type.value,
                model.source_id == source.source_id,
                model.source_version == source.source_version,
                or_(*(and_(model.target_type == kind, model.target_id.in_(ids)) for kind, ids in groups.items())),
            )
            .execution_options(populate_existing=True)
        )


def original_for(rows, key):
    matches = [row for row in rows if (row.target_type, row.target_id) == (key.target_type.value, key.target_id)]
    if not matches:
        return None
    signatures = {
        (
            row.target_tenant_id,
            row.target_space_id,
            row.legacy_invalid_reason,
            row.legacy_run_id,
            row.legacy_evidence_key,
        )
        for row in matches
    }
    if len(signatures) != 1:
        raise ResourceReferenceInvalidError(reason="reference_original_evidence_conflict")
    return matches[0]


def revision(*rows):
    payload = [
        dict(row)
        if isinstance(row, Mapping)
        else {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in rows
        if row is not None
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True)
class KnowledgeTargetObservation:
    key: TargetKey
    exists: bool
    target_tenant_id: int | None
    target_space_id: str | None
    target_revision: str
    original: BusinessResourceReference | None
    deletion: DeletionEvidence | None
    ancestor_deletion: DeletionEvidence | None


class KnowledgeReferenceTargetRepository:
    def __init__(self):
        self._prelock_key = object()

    @staticmethod
    def _sources(source_keys):
        if not isinstance(source_keys, tuple) or not source_keys:
            raise ResourceReferenceInvalidError(reason="reference_batch_sources_required")
        for key in source_keys:
            current_tenant(key, "bind")
        if (
            len(set(source_keys)) != len(source_keys)
            or len({(key.tenant_id, key.source_type, key.source_id) for key in source_keys}) != 1
        ):
            raise ResourceReferenceInvalidError(reason="reference_batch_root_mismatch")
        return tuple(sorted(source_keys, key=lambda key: key.source_version))

    def _prelock_proof(self, session, source_key, operation):
        proof = session.info.get(self._prelock_key)
        if operation != "bind" or proof is None or proof[0] is not TransactionIdentity.capture(session).transaction:
            return None
        if (source_key.tenant_id, source_key.source_type, source_key.source_id) != (
            proof[1][0].tenant_id,
            proof[1][0].source_type,
            proof[1][0].source_id,
        ):
            return None
        if source_key not in proof[1]:
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
        return proof

    def _check_prelock(self, session, source_key, operation, keys, space_ids, file_ids):
        proof = self._prelock_proof(session, source_key, operation)
        if proof is not None and (not set(keys) <= proof[2] or not space_ids <= proof[3] or not file_ids <= proof[4]):
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")

    def _check_tombstone_prelock(self, session, source_key, operation, key, space_id, owner):
        proof = self._prelock_proof(session, source_key, operation)
        requested = {(key, owner)} if owner else set()
        if owner and space_id and key.target_type == TargetType.KNOWLEDGE_FILE:
            requested.add((TargetKey("knowledge_space", space_id), owner))
        if proof is not None and not requested <= proof[5]:
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")

    @staticmethod
    def _keys(target_keys):
        if not isinstance(target_keys, tuple) or any(
            not isinstance(key, TargetKey)
            or key.target_type not in {TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE}
            for key in target_keys
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_target_type_invalid")
        return tuple(sorted(set(target_keys), key=lambda key: key.lock_order_key))

    @staticmethod
    def _business_statements(model, ids, *, lock):
        ordered = sorted(ids)
        for start in range(0, len(ordered), 200):
            statement = (
                select(model)
                .where(model.id.in_(ordered[start : start + 200]))
                .order_by(model.id)
                .execution_options(populate_existing=True)
            )
            yield statement.with_for_update() if lock else statement

    @staticmethod
    def _space_lock_statements(space_ids, originals, sources, tenant):
        pairs = set()
        for row in originals:
            if row.target_tenant_id in (None, row.tenant_id):
                continue
            key = TargetKey(row.target_type, row.target_id)
            if not any(
                is_preserved_foreign_space_reference(
                    row, source_key=source, target=key, target_tenant_id=row.target_tenant_id
                )
                for source in sources
            ):
                raise ResourceReferenceInvalidError(reason="knowledge_reference_target_unavailable")
            pairs.add((int(row.target_id), row.target_tenant_id))
        ordered = sorted(space_ids)
        for start in range(0, len(ordered), 200):
            batch = ordered[start : start + 200]
            yield (
                select(Knowledge)
                .where(
                    or_(
                        and_(Knowledge.id.in_(batch), Knowledge.tenant_id == tenant),
                        *(
                            and_(Knowledge.id == ident, Knowledge.tenant_id == owner)
                            for ident, owner in sorted(pairs)
                            if ident in batch
                        ),
                    )
                )
                .order_by(Knowledge.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )

    @staticmethod
    def _tombstone_statements(entries):
        # Only complete facts from real rows, original bindings or the trusted
        # owner-query scope reach this producer; missing binds supply no owner.
        values = tuple(entries)
        if any(
            type(pair) is not tuple
            or len(pair) != 2
            or not isinstance(pair[0], TargetKey)
            or pair[0].target_type not in {TargetType.KNOWLEDGE_SPACE, TargetType.KNOWLEDGE_FILE}
            or type(pair[1]) is not int
            or pair[1] <= 0
            for pair in values
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_tombstone_facts_invalid")
        # The physical ID is VARCHAR: sort the complete set before slicing,
        # never numeric chunks. Business locks and observations remain numeric.
        ordered = sorted(set(values), key=lambda pair: (pair[0].target_type.value, pair[0].target_id, pair[1]))
        model = ResourceReferenceTombstone
        for start in range(0, len(ordered), 200):
            groups = {}
            for key, owner in ordered[start : start + 200]:
                groups.setdefault((key.target_type.value, owner), []).append(key.target_id)
            yield (
                select(model)
                .where(
                    or_(
                        *(
                            and_(
                                model.target_type == kind,
                                model.target_id.in_(ids),
                                model.target_tenant_id == owner,
                                model.tenant_id == owner,
                            )
                            for (kind, owner), ids in groups.items()
                        )
                    )
                )
                .order_by(model.target_type, model.target_id, model.target_tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )

    @staticmethod
    def _add_tombstones(rows, expected, found):
        for row in rows:
            if not isinstance(row, ResourceReferenceTombstone):
                raise ResourceReferenceInvalidError(reason="knowledge_reference_tombstone_result_invalid")
            try:
                entry = TargetKey(row.target_type, row.target_id), row.target_tenant_id
            except (TypeError, ValueError) as error:
                raise ResourceReferenceInvalidError(reason="knowledge_reference_tombstone_result_invalid") from error
            if entry not in expected or entry in found or row.tenant_id != entry[1]:
                raise ResourceReferenceInvalidError(reason="knowledge_reference_tombstone_result_invalid")
            found[entry] = row

    @staticmethod
    def _deletion(row):
        if row is None:
            return None
        return DeletionEvidence(
            row.operation_id, TargetKey(row.target_type, row.target_id), row.target_tenant_id, row.stage
        )

    @staticmethod
    def _plan(keys, candidates, originals):
        owners = {row.id: row.knowledge_id for row in candidates}
        space_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_SPACE}
        space_ids.update(owners.values())
        space_ids.update(int(row.target_space_id) for row in originals if row.target_space_id is not None)
        return owners, space_ids

    @staticmethod
    def _facts(key, tenant_id, operation, spaces, files, candidate_owners, originals, source_key=None):
        original = original_for(originals, key)
        row = (
            spaces.get(int(key.target_id))
            if key.target_type == TargetType.KNOWLEDGE_SPACE
            else files.get(int(key.target_id))
        )
        space_id = (
            key.target_id
            if key.target_type == TargetType.KNOWLEDGE_SPACE
            else (str(row.knowledge_id) if row is not None else original.target_space_id if original else None)
        )
        parent = spaces.get(int(space_id)) if space_id is not None else None
        if (
            row is not None
            and row.tenant_id != tenant_id
            and not (
                operation == "bind"
                and is_preserved_foreign_space_reference(
                    original, source_key=source_key, target=key, target_tenant_id=row.tenant_id
                )
            )
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_target_unavailable")
        if row is not None and key.target_type == TargetType.KNOWLEDGE_FILE:
            if row.knowledge_id != candidate_owners.get(row.id):
                raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
            if parent is None or parent.tenant_id != tenant_id or parent.type not in {0, 1, 3}:
                raise ResourceReferenceInvalidError(reason="knowledge_reference_parent_unavailable")
        if row is not None and key.target_type == TargetType.KNOWLEDGE_SPACE and row.type not in {0, 1, 3}:
            raise ResourceReferenceInvalidError(reason="knowledge_reference_target_unavailable")
        owner = (
            row.tenant_id
            if row is not None
            else original.target_tenant_id
            if original
            else (tenant_id if operation == "owner_query" else None)
        )
        return original, row, parent, space_id, owner

    def lock_targets(self, session, target_keys, source_key, operation):
        tenant_id, keys = current_tenant(source_key, operation), self._keys(target_keys)
        file_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE}
        with strict_tenant_filter():
            originals, candidates = [], []
            for statement in original_statements(source_key, keys) if source_key else ():
                originals.extend(session.execute(statement).scalars())
            for statement in self._business_statements(KnowledgeFile, file_ids, lock=False):
                candidates.extend(session.execute(statement).scalars())
            candidate_owners, space_ids = self._plan(keys, candidates, originals)
            self._check_prelock(session, source_key, operation, keys, space_ids, file_ids)
            spaces, files = {}, {}
            # Complete the numeric Root lock phase before starting File locks.
            for statement in self._space_lock_statements(
                space_ids, originals, (source_key,) if source_key else (), tenant_id
            ):
                with bypass_tenant_filter():
                    spaces.update((row.id, row) for row in session.execute(statement).scalars())
            for statement in self._business_statements(KnowledgeFile, file_ids, lock=True):
                files.update((row.id, row) for row in session.execute(statement).scalars())
        plan = self._tombstone_plan(
            session, keys, tenant_id, source_key, operation, spaces, files, candidate_owners, originals
        )
        value = None
        while True:
            try:
                statement = plan.send(value)
            except StopIteration as done:
                return done.value
            with bypass_tenant_filter():
                value = list(session.execute(statement).scalars())

    async def alock_targets(self, session, target_keys, source_key, operation):
        tenant_id, keys = current_tenant(source_key, operation), self._keys(target_keys)
        file_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE}
        with strict_tenant_filter():
            originals, candidates = [], []
            for statement in original_statements(source_key, keys) if source_key else ():
                originals.extend((await session.execute(statement)).scalars())
            for statement in self._business_statements(KnowledgeFile, file_ids, lock=False):
                candidates.extend((await session.execute(statement)).scalars())
            candidate_owners, space_ids = self._plan(keys, candidates, originals)
            self._check_prelock(session, source_key, operation, keys, space_ids, file_ids)
            spaces, files = {}, {}
            for statement in self._space_lock_statements(
                space_ids, originals, (source_key,) if source_key else (), tenant_id
            ):
                with bypass_tenant_filter():
                    spaces.update((row.id, row) for row in (await session.execute(statement)).scalars())
            for statement in self._business_statements(KnowledgeFile, file_ids, lock=True):
                files.update((row.id, row) for row in (await session.execute(statement)).scalars())
        plan = self._tombstone_plan(
            session, keys, tenant_id, source_key, operation, spaces, files, candidate_owners, originals
        )
        value = None
        while True:
            try:
                statement = plan.send(value)
            except StopIteration as done:
                return done.value
            with bypass_tenant_filter():
                value = list((await session.execute(statement)).scalars())

    def _tombstone_plan(
        self, session, keys, tenant_id, source_key, operation, spaces, files, candidate_owners, originals
    ):
        planned, entries = [], set()
        by_key = {}
        for original in originals:
            by_key.setdefault((original.target_type, original.target_id), []).append(original)
        for key in keys:
            original, row, parent, space_id, owner = self._facts(
                key,
                tenant_id,
                operation,
                spaces,
                files,
                candidate_owners,
                by_key.get((key.target_type.value, key.target_id), ()),
                source_key,
            )
            self._check_tombstone_prelock(session, source_key, operation, key, space_id, owner)
            planned.append((key, original, row, parent, space_id, owner))
            if owner:
                entries.add((key, owner))
                if space_id and key.target_type == TargetType.KNOWLEDGE_FILE:
                    entries.add((TargetKey("knowledge_space", space_id), owner))
        clearing = {}
        space_ids = sorted(ident for ident, row in spaces.items() if row.type == 3)
        job = KnowledgeSpaceDeleteJob
        names = ("id", "tenant_id", "space_id", "operation_type", "business_phase", "state")
        for start in range(0, len(space_ids), 200):
            query = (
                select(job)
                .options(load_only(*(getattr(job, name) for name in names), raiseload=True))
                .where(
                    job.tenant_id == tenant_id,
                    job.space_id.in_(space_ids[start : start + 200]),
                    job.operation_type == "knowledge_space_clear",
                    job.state != "SUCCEEDED",
                )
                .order_by(job.space_id, job.id)
            )
            for active in (yield query):
                if active.space_id in clearing or active.business_phase not in {"prepared", "finalized"}:
                    raise ResourceReferenceInvalidError(reason="knowledge_clear_execution_inconsistent")
                clearing[active.space_id] = {name: getattr(active, name) for name in names}
        found = {}
        for statement in self._tombstone_statements(entries):
            self._add_tombstones((yield statement), entries, found)
        result = []
        for key, original, row, parent, space_id, owner in planned:
            direct = found.get((key, owner))
            ancestor = (
                found.get((TargetKey("knowledge_space", space_id), owner))
                if owner and space_id and key.target_type == TargetType.KNOWLEDGE_FILE
                else None
            )
            pending = clearing.get(int(space_id)) if space_id is not None else None
            transient = (
                None
                if pending is None
                else DeletionEvidence(
                    pending["id"],
                    TargetKey(TargetType.KNOWLEDGE_SPACE, space_id),
                    pending["tenant_id"],
                    TargetDeleteStage.DELETING,
                )
            )
            if transient is not None:
                existing = direct if key.target_type == TargetType.KNOWLEDGE_SPACE else ancestor
                if existing is not None:
                    raise ResourceReferenceInvalidError(reason="knowledge_clear_tombstone_conflict")
            result.append(
                KnowledgeTargetObservation(
                    key,
                    row is not None,
                    owner,
                    space_id,
                    revision(row, parent, direct, ancestor, pending),
                    original,
                    transient
                    if key.target_type == TargetType.KNOWLEDGE_SPACE and transient
                    else self._deletion(direct),
                    transient
                    if key.target_type == TargetType.KNOWLEDGE_FILE and transient
                    else self._deletion(ancestor),
                )
            )
        return tuple(result)

    def _physical_plan(self, target_keys, source_keys):
        keys, sources = self._keys(target_keys), self._sources(source_keys)
        originals = []
        wanted = {(key.target_type.value, key.target_id) for key in keys}
        model, root = BusinessResourceReference, sources[0]
        # Each selected version is read in exactly one version group. PK seek
        # consumes raw pages, including pages with no selected target at all.
        for start in range(0, len(sources), 200) if keys else ():
            versions, after = [source.source_version for source in sources[start : start + 200]], 0
            while True:
                rows = yield (
                    (
                        select(model)
                        .where(
                            model.source_type == root.source_type.value,
                            model.source_id == root.source_id,
                            model.source_version.in_(versions),
                            model.target_type.in_((TargetType.KNOWLEDGE_SPACE.value, TargetType.KNOWLEDGE_FILE.value)),
                            model.id > after,
                        )
                        .order_by(model.id)
                        .limit(200)
                        .execution_options(populate_existing=True)
                    ),
                    False,
                )
                originals.extend(row for row in rows if (row.target_type, row.target_id) in wanted)
                if len(rows) < 200:
                    break
                after = rows[-1].id
        file_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE}
        candidates = []
        for statement in self._business_statements(KnowledgeFile, file_ids, lock=False):
            candidates.extend((yield statement, False))
        candidate_owners, space_ids = self._plan(keys, candidates, originals)
        spaces, files = [], []
        for statement in self._space_lock_statements(space_ids, originals, sources, sources[0].tenant_id):
            spaces.extend((yield statement, True))
        for statement in self._business_statements(KnowledgeFile, file_ids, lock=True):
            files.extend((yield statement, False))
        if {row.id: row.knowledge_id for row in files} != candidate_owners:
            raise ResourceReferenceConflictError(reason="reference_lock_plan_changed")
        tombstones = {(TargetKey("knowledge_space", str(row.id)), row.tenant_id) for row in spaces}
        for row in files:
            tombstones.add((TargetKey("knowledge_file", str(row.id)), row.tenant_id))
            tombstones.add((TargetKey("knowledge_space", str(row.knowledge_id)), row.tenant_id))
        for original in originals:
            if original.target_tenant_id is not None:
                tombstones.add((TargetKey(original.target_type, original.target_id), original.target_tenant_id))
                if original.target_type == TargetType.KNOWLEDGE_FILE.value and original.target_space_id is not None:
                    tombstones.add((TargetKey("knowledge_space", original.target_space_id), original.target_tenant_id))
        found = {}
        for statement in self._tombstone_statements(tombstones):
            self._add_tombstones((yield statement, True), tombstones, found)
        return sources, frozenset(keys), frozenset(space_ids), frozenset(file_ids), frozenset(tombstones)

    def prelock_targets(self, session, target_keys, source_keys):
        plan, value = self._physical_plan(target_keys, source_keys), None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                session.info[self._prelock_key] = (TransactionIdentity.capture(session).transaction, *done.value)
                return
            with bypass_tenant_filter() if cross_scope else strict_tenant_filter():
                value = list(session.execute(statement).scalars())

    async def aprelock_targets(self, session, target_keys, source_keys):
        plan, value = self._physical_plan(target_keys, source_keys), None
        while True:
            try:
                statement, cross_scope = plan.send(value)
            except StopIteration as done:
                session.info[self._prelock_key] = (TransactionIdentity.capture(session).transaction, *done.value)
                return
            with bypass_tenant_filter() if cross_scope else strict_tenant_filter():
                value = list((await session.execute(statement)).scalars())
