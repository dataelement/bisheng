"""Current, locked knowledge facts for the reference target Owner.

The caller owns the transaction. Source reads are candidate evidence only;
the reference writer subsequently locks/CAS-checks the source root and set.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlmodel import select

from bisheng.common.errcode.knowledge import ResourceReferenceConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.resource_reference.application.contracts import DeletionEvidence, SourceKey, TargetKey, TargetType
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


def original_statement(source, keys):
    return (
        select(BusinessResourceReference)
        .where(
            BusinessResourceReference.source_type == source.source_type.value,
            BusinessResourceReference.source_id == source.source_id,
            BusinessResourceReference.source_version == source.source_version,
            or_(
                *(
                    and_(
                        BusinessResourceReference.target_type == key.target_type.value,
                        BusinessResourceReference.target_id == key.target_id,
                    )
                    for key in keys
                )
            ),
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
        {column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows if row is not None
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
    def _business_statement(model, ids, *, lock):
        statement = (
            select(model).where(model.id.in_(sorted(ids))).order_by(model.id).execution_options(populate_existing=True)
        )
        return statement.with_for_update() if lock else statement

    @staticmethod
    def _tombstone_statement(key, owner):
        # The exact owner came from a real row, an original source binding, or
        # the trusted owner-query scope. It is never inferred for missing binds.
        return (
            select(ResourceReferenceTombstone)
            .where(
                ResourceReferenceTombstone.target_type == key.target_type.value,
                ResourceReferenceTombstone.target_id == key.target_id,
                ResourceReferenceTombstone.target_tenant_id == owner,
                ResourceReferenceTombstone.tenant_id == owner,
            )
            .execution_options(populate_existing=True)
        )

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
    def _facts(key, tenant_id, operation, spaces, files, candidate_owners, originals):
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
        if row is not None and row.tenant_id != tenant_id:
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
            originals = (
                list(session.execute(original_statement(source_key, keys)).scalars()) if source_key and keys else []
            )
            candidates = (
                list(session.execute(self._business_statement(KnowledgeFile, file_ids, lock=False)).scalars())
                if file_ids
                else []
            )
            candidate_owners, space_ids = self._plan(keys, candidates, originals)
            spaces = (
                {
                    row.id: row
                    for row in session.execute(self._business_statement(Knowledge, space_ids, lock=True)).scalars()
                }
                if space_ids
                else {}
            )
            files = (
                {
                    row.id: row
                    for row in session.execute(self._business_statement(KnowledgeFile, file_ids, lock=True)).scalars()
                }
                if file_ids
                else {}
            )
        result = []
        for key in keys:
            original, row, parent, space_id, owner = self._facts(
                key, tenant_id, operation, spaces, files, candidate_owners, originals
            )
            with bypass_tenant_filter():
                direct = session.execute(self._tombstone_statement(key, owner)).scalar_one_or_none() if owner else None
                ancestor = (
                    session.execute(
                        self._tombstone_statement(TargetKey("knowledge_space", space_id), owner)
                    ).scalar_one_or_none()
                    if owner and space_id and key.target_type == TargetType.KNOWLEDGE_FILE
                    else None
                )
            result.append(
                KnowledgeTargetObservation(
                    key,
                    row is not None,
                    owner,
                    space_id,
                    revision(row, parent, direct, ancestor),
                    original,
                    self._deletion(direct),
                    self._deletion(ancestor),
                )
            )
        return tuple(result)

    async def alock_targets(self, session, target_keys, source_key, operation):
        tenant_id, keys = current_tenant(source_key, operation), self._keys(target_keys)
        file_ids = {int(key.target_id) for key in keys if key.target_type == TargetType.KNOWLEDGE_FILE}
        with strict_tenant_filter():
            originals = (
                list((await session.execute(original_statement(source_key, keys))).scalars())
                if source_key and keys
                else []
            )
            candidates = (
                list((await session.execute(self._business_statement(KnowledgeFile, file_ids, lock=False))).scalars())
                if file_ids
                else []
            )
            candidate_owners, space_ids = self._plan(keys, candidates, originals)
            spaces = (
                {
                    row.id: row
                    for row in (
                        await session.execute(self._business_statement(Knowledge, space_ids, lock=True))
                    ).scalars()
                }
                if space_ids
                else {}
            )
            files = (
                {
                    row.id: row
                    for row in (
                        await session.execute(self._business_statement(KnowledgeFile, file_ids, lock=True))
                    ).scalars()
                }
                if file_ids
                else {}
            )
        result = []
        for key in keys:
            original, row, parent, space_id, owner = self._facts(
                key, tenant_id, operation, spaces, files, candidate_owners, originals
            )
            with bypass_tenant_filter():
                direct = (
                    (await session.execute(self._tombstone_statement(key, owner))).scalar_one_or_none()
                    if owner
                    else None
                )
                ancestor = (
                    (
                        await session.execute(self._tombstone_statement(TargetKey("knowledge_space", space_id), owner))
                    ).scalar_one_or_none()
                    if owner and space_id and key.target_type == TargetType.KNOWLEDGE_FILE
                    else None
                )
            result.append(
                KnowledgeTargetObservation(
                    key,
                    row is not None,
                    owner,
                    space_id,
                    revision(row, parent, direct, ancestor),
                    original,
                    self._deletion(direct),
                    self._deletion(ancestor),
                )
            )
        return tuple(result)
