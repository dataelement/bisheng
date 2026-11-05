"""Reference-index SQL operations participating in the caller's transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from weakref import WeakSet

from sqlalchemy import and_, false, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, is_tenant_filter_bypassed, strict_tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.resource_reference.application.contracts import (
    ROOT_GUARD_VERSION,
    ReferenceSpec,
    SourceKey,
    SourceType,
    TargetKey,
    TargetLockReceipt,
    TargetType,
    TransactionIdentity,
    reference_set_digest,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class OwnerTargetScope:
    transaction: TransactionIdentity
    owner_tenant_id: int
    targets: tuple[TargetKey, ...]
    _receipts: tuple[TargetLockReceipt, ...] = field(repr=False)
    _authority: object = field(repr=False)


def _invalid(reason: str) -> ResourceReferenceInvalidError:
    return ResourceReferenceInvalidError(reason=reason)


class ReferenceRepository:
    def __init__(self, *, verifier: ReferenceTargetVerifier | None = None):
        if verifier is not None and not isinstance(verifier, ReferenceTargetVerifier):
            raise TypeError("target query authority requires a ReferenceTargetVerifier")
        self.verifier = verifier
        self._scope_authority = object()
        self._issued_scopes: WeakSet[OwnerTargetScope] = WeakSet()

    @staticmethod
    def current_tenant_id() -> int:
        if is_tenant_filter_bypassed():
            raise _invalid("source_tenant_filter_bypassed")
        tenant_id = _resolve_tenant_id()
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise _invalid("source_tenant_context_missing")
        return tenant_id

    @classmethod
    def assert_source_tenant(cls, key: SourceKey) -> None:
        if cls.current_tenant_id() != key.tenant_id:
            raise _invalid("source_tenant_mismatch")

    @staticmethod
    def _source_query(model, key: SourceKey, *, root: bool = False, for_update: bool = False):
        statement = select(model).where(
            model.source_type == key.source_type.value,
            model.source_id == key.source_id,
            model.source_version == (ROOT_GUARD_VERSION if root else key.source_version),
        )
        if for_update:
            statement = statement.with_for_update()
        return statement.execution_options(populate_existing=True)

    def get_source_set(self, session: Session, key: SourceKey, *, for_update: bool = False):
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            return session.execute(
                self._source_query(BusinessReferenceSet, key, for_update=for_update)
            ).scalar_one_or_none()

    async def aget_source_set(self, session: AsyncSession, key: SourceKey, *, for_update: bool = False):
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            result = await session.execute(self._source_query(BusinessReferenceSet, key, for_update=for_update))
            return result.scalar_one_or_none()

    def get_root_guard(self, session: Session, key: SourceKey, *, for_update: bool = False):
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            return session.execute(
                self._source_query(BusinessReferenceSet, key, root=True, for_update=for_update)
            ).scalar_one_or_none()

    async def aget_root_guard(self, session: AsyncSession, key: SourceKey, *, for_update: bool = False):
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            result = await session.execute(
                self._source_query(BusinessReferenceSet, key, root=True, for_update=for_update)
            )
            return result.scalar_one_or_none()

    @staticmethod
    def _root_source_exists_query(key: SourceKey, *, for_update: bool):
        statement = (
            select(BusinessReferenceSet.id)
            .where(
                BusinessReferenceSet.source_type == key.source_type.value,
                BusinessReferenceSet.source_id == key.source_id,
                BusinessReferenceSet.record_kind == "source",
            )
            .limit(1)
        )
        return statement.with_for_update() if for_update else statement

    def has_source_sets_for_root(self, session: Session, key: SourceKey, *, for_update: bool = False) -> bool:
        """Bounded existence check for this exact tenant/type/business root."""
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            return session.execute(self._root_source_exists_query(key, for_update=for_update)).first() is not None

    async def ahas_source_sets_for_root(
        self, session: AsyncSession, key: SourceKey, *, for_update: bool = False
    ) -> bool:
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            result = await session.execute(self._root_source_exists_query(key, for_update=for_update))
            return result.first() is not None

    def list_source_references(
        self, session: Session, key: SourceKey, *, for_update: bool = False
    ) -> tuple[BusinessResourceReference, ...]:
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            return tuple(
                session.execute(self._source_query(BusinessResourceReference, key, for_update=for_update))
                .scalars()
                .all()
            )

    async def alist_source_references(
        self, session: AsyncSession, key: SourceKey, *, for_update: bool = False
    ) -> tuple[BusinessResourceReference, ...]:
        self.assert_source_tenant(key)
        with strict_tenant_filter():
            result = await session.execute(self._source_query(BusinessResourceReference, key, for_update=for_update))
            return tuple(result.scalars().all())

    def list_source_sets(self, session: Session, *, source_type: str) -> tuple[BusinessReferenceSet, ...]:
        self.current_tenant_id()
        with strict_tenant_filter():
            return tuple(session.execute(self._sets_query(source_type)).scalars().all())

    async def alist_source_sets(self, session: AsyncSession, *, source_type: str) -> tuple[BusinessReferenceSet, ...]:
        self.current_tenant_id()
        with strict_tenant_filter():
            return tuple((await session.execute(self._sets_query(source_type))).scalars().all())

    @staticmethod
    def _sets_query(source_type):
        return select(BusinessReferenceSet).where(
            BusinessReferenceSet.source_type == SourceType(source_type).value,
            BusinessReferenceSet.record_kind == "source",
        )

    @staticmethod
    def _check_revision(current, expected_revision: int | None, new_revision: int, *, root: bool = False):
        if isinstance(new_revision, bool) or not isinstance(new_revision, int) or new_revision < 0:
            raise _invalid("source_revision_conflict")
        if current is None:
            if expected_revision != (0 if root else None):
                raise _invalid("root_revision_conflict" if root else "source_revision_conflict")
            if root and new_revision <= 0:
                raise _invalid("root_revision_conflict")
        elif (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or current.source_revision != expected_revision
            or new_revision <= expected_revision
        ):
            raise _invalid("root_revision_conflict" if root else "source_revision_conflict")

    @staticmethod
    def _revision_update(current, key, expected_revision, **values):
        # Tenant events do not intercept bulk UPDATE. All identity predicates
        # are required even when the caller already holds the business root.
        return (
            update(BusinessReferenceSet)
            .where(
                BusinessReferenceSet.id == current.id,
                BusinessReferenceSet.tenant_id == key.tenant_id,
                BusinessReferenceSet.source_type == key.source_type.value,
                BusinessReferenceSet.source_id == key.source_id,
                BusinessReferenceSet.source_version == current.source_version,
                BusinessReferenceSet.source_revision == expected_revision,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def _new_guard(key, revision):
        return BusinessReferenceSet(
            tenant_id=key.tenant_id,
            source_type=key.source_type.value,
            source_id=key.source_id,
            source_version=ROOT_GUARD_VERSION,
            record_kind="root_guard",
            source_revision=revision,
            extractor_version="root-guard-v1",
            digest=reference_set_digest(()),
            effective=False,
            ready=False,
        )

    def advance_root_guard(self, session: Session, key: SourceKey, *, expected_revision: int, new_revision: int) -> int:
        current = self.get_root_guard(session, key, for_update=True)
        if current is None and self.has_source_sets_for_root(session, key, for_update=True):
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_missing")
        self._check_revision(current, expected_revision, new_revision, root=True)
        if current is None:
            session.add(self._new_guard(key, new_revision))
        else:
            result = session.execute(
                self._revision_update(current, key, expected_revision, source_revision=new_revision)
            )
            if result.rowcount != 1:
                raise _invalid("root_revision_conflict")
            session.expire(current)
        session.flush()
        return new_revision

    async def aadvance_root_guard(
        self, session: AsyncSession, key: SourceKey, *, expected_revision: int, new_revision: int
    ) -> int:
        current = await self.aget_root_guard(session, key, for_update=True)
        if current is None and await self.ahas_source_sets_for_root(session, key, for_update=True):
            raise ReferenceCoverageNotReadyError(reason="source_root_guard_missing")
        self._check_revision(current, expected_revision, new_revision, root=True)
        if current is None:
            session.add(self._new_guard(key, new_revision))
        else:
            result = await session.execute(
                self._revision_update(current, key, expected_revision, source_revision=new_revision)
            )
            if result.rowcount != 1:
                raise _invalid("root_revision_conflict")
            session.expire(current)
        await session.flush()
        return new_revision

    def _prepare_set(self, key, references, new_revision, extractor_version, digest, effective):
        self.assert_source_tenant(key)
        if not extractor_version or len(extractor_version) > 64:
            raise _invalid("extractor_version_invalid")
        if not isinstance(effective, bool) or (not effective and references):
            raise _invalid("ineffective_source_has_references")
        indexed = {}
        for row in references:
            if (row.tenant_id, row.source_type, row.source_id, row.source_version, row.source_revision) != (
                key.tenant_id,
                key.source_type.value,
                key.source_id,
                key.source_version,
                new_revision,
            ):
                raise _invalid("reference_row_source_mismatch")
            identity = (row.slot_key, row.target_type, row.target_id)
            if identity in indexed:
                raise _invalid("duplicate_reference_identity")
            indexed[identity] = row
        specs = tuple(ReferenceSpec(row.slot_key, TargetKey(row.target_type, row.target_id)) for row in references)
        if digest != reference_set_digest(specs):
            raise _invalid("source_digest_mismatch")
        return indexed, {
            "source_revision": new_revision,
            "extractor_version": extractor_version,
            "digest": digest,
            "effective": effective,
            "ready": True,
        }

    @staticmethod
    def _change_rows(old, new):
        previous = {(row.slot_key, row.target_type, row.target_id): row for row in old}
        removed = tuple(row for identity, row in previous.items() if identity not in new)
        added = tuple(row for identity, row in new.items() if identity not in previous)
        for identity in previous.keys() & new.keys():
            existing, incoming = previous[identity], new[identity]
            for name in (
                "source_revision",
                "target_tenant_id",
                "target_space_id",
                "legacy_invalid_reason",
                "legacy_run_id",
                "legacy_evidence_key",
            ):
                setattr(existing, name, getattr(incoming, name))
        return removed, added

    def replace_source_set(
        self,
        session: Session,
        key: SourceKey,
        *,
        expected_revision: int | None,
        new_revision: int,
        references: tuple[BusinessResourceReference, ...],
        extractor_version: str,
        digest: str,
        effective: bool,
    ) -> None:
        indexed, values = self._prepare_set(key, references, new_revision, extractor_version, digest, effective)
        current = self.get_source_set(session, key, for_update=True)
        self._check_revision(current, expected_revision, new_revision)
        old = self.list_source_references(session, key)
        if current is None:
            session.add(
                BusinessReferenceSet(
                    tenant_id=key.tenant_id,
                    source_type=key.source_type.value,
                    source_id=key.source_id,
                    source_version=key.source_version,
                    **values,
                )
            )
        else:
            result = session.execute(self._revision_update(current, key, expected_revision, **values))
            if result.rowcount != 1:
                raise _invalid("source_revision_conflict")
            session.expire(current)
        removed, added = self._change_rows(old, indexed)
        for row in removed:
            session.delete(row)
        session.add_all(added)
        session.flush()

    async def areplace_source_set(
        self,
        session: AsyncSession,
        key: SourceKey,
        *,
        expected_revision: int | None,
        new_revision: int,
        references: tuple[BusinessResourceReference, ...],
        extractor_version: str,
        digest: str,
        effective: bool,
    ) -> None:
        indexed, values = self._prepare_set(key, references, new_revision, extractor_version, digest, effective)
        current = await self.aget_source_set(session, key, for_update=True)
        self._check_revision(current, expected_revision, new_revision)
        old = await self.alist_source_references(session, key)
        if current is None:
            session.add(
                BusinessReferenceSet(
                    tenant_id=key.tenant_id,
                    source_type=key.source_type.value,
                    source_id=key.source_id,
                    source_version=key.source_version,
                    **values,
                )
            )
        else:
            result = await session.execute(self._revision_update(current, key, expected_revision, **values))
            if result.rowcount != 1:
                raise _invalid("source_revision_conflict")
            session.expire(current)
        removed, added = self._change_rows(old, indexed)
        for row in removed:
            await session.delete(row)
        session.add_all(added)
        await session.flush()

    @staticmethod
    def _target_query(targets: tuple[TargetKey, ...], *, include_space_contents: bool = False):
        conditions = [
            and_(
                BusinessResourceReference.target_type == target.target_type.value,
                BusinessResourceReference.target_id == target.target_id,
            )
            for target in targets
        ]
        if include_space_contents:
            spaces = [target.target_id for target in targets if target.target_type == TargetType.KNOWLEDGE_SPACE]
            if spaces:
                conditions.append(BusinessResourceReference.target_space_id.in_(spaces))
        return (
            select(BusinessResourceReference)
            .where(or_(*conditions) if conditions else false())
            .order_by(BusinessResourceReference.id)
            .execution_options(populate_existing=True)
        )

    def list_inbound_targets(
        self, session: Session, targets: tuple[TargetKey, ...]
    ) -> tuple[BusinessResourceReference, ...]:
        self.current_tenant_id()
        if not targets:
            return ()
        with strict_tenant_filter():
            return tuple(session.execute(self._target_query(targets)).scalars().all())

    async def alist_inbound_targets(
        self, session: AsyncSession, targets: tuple[TargetKey, ...]
    ) -> tuple[BusinessResourceReference, ...]:
        self.current_tenant_id()
        if not targets:
            return ()
        with strict_tenant_filter():
            return tuple((await session.execute(self._target_query(targets))).scalars().all())

    def list_inbound_space(self, session: Session, space_id: str) -> tuple[BusinessResourceReference, ...]:
        self.current_tenant_id()
        with strict_tenant_filter():
            return tuple(
                session.execute(
                    self._target_query((TargetKey(TargetType.KNOWLEDGE_SPACE, space_id),), include_space_contents=True)
                )
                .scalars()
                .all()
            )

    async def alist_inbound_space(self, session: AsyncSession, space_id: str) -> tuple[BusinessResourceReference, ...]:
        self.current_tenant_id()
        with strict_tenant_filter():
            return tuple(
                (
                    await session.execute(
                        self._target_query(
                            (TargetKey(TargetType.KNOWLEDGE_SPACE, space_id),), include_space_contents=True
                        )
                    )
                )
                .scalars()
                .all()
            )

    def list_inbound_exact_files(self, session: Session, file_ids: tuple[str, ...]):
        return self.list_inbound_targets(session, tuple(TargetKey(TargetType.KNOWLEDGE_FILE, key) for key in file_ids))

    async def alist_inbound_exact_files(self, session: AsyncSession, file_ids: tuple[str, ...]):
        return await self.alist_inbound_targets(
            session, tuple(TargetKey(TargetType.KNOWLEDGE_FILE, key) for key in file_ids)
        )

    def target_owner_scope(
        self, session: Session | AsyncSession, receipts: tuple[TargetLockReceipt, ...]
    ) -> OwnerTargetScope:
        tenant_id = self.current_tenant_id()
        if self.verifier is None:
            raise _invalid("reference_target_verifier_missing")
        targets = self.verifier.validate_owner_receipts(session, receipts)
        if any(target.target_tenant_id != tenant_id for target in targets):
            raise _invalid("target_owner_scope_invalid")
        keys = tuple(sorted({target.key for target in targets}, key=lambda key: key.lock_order_key))
        scope = OwnerTargetScope(TransactionIdentity.capture(session), tenant_id, keys, receipts, self._scope_authority)
        self._issued_scopes.add(scope)
        return scope

    def _check_scope(self, session, scope):
        if (
            not isinstance(scope, OwnerTargetScope)
            or scope not in self._issued_scopes
            or not scope.targets
            or scope._authority is not self._scope_authority
            or scope.owner_tenant_id != self.current_tenant_id()
        ):
            raise _invalid("target_owner_scope_invalid")
        try:
            scope.transaction.assert_current(session)
        except (TypeError, ValueError) as exc:
            raise _invalid("target_owner_scope_expired") from exc
        if self.verifier is None:
            raise _invalid("reference_target_verifier_missing")
        verified = self.verifier.validate_owner_receipts(session, scope._receipts)
        if {target.key for target in verified} != set(scope.targets):
            raise _invalid("target_owner_scope_invalid")

    def list_inbound_for_owner(
        self, session: Session, scope: OwnerTargetScope, *, include_space_contents: bool = False
    ) -> tuple[BusinessResourceReference, ...]:
        self._check_scope(session, scope)
        with bypass_tenant_filter():
            return tuple(
                session.execute(
                    self._target_query(scope.targets, include_space_contents=include_space_contents).with_for_update()
                )
                .scalars()
                .all()
            )

    async def alist_inbound_for_owner(
        self, session: AsyncSession, scope: OwnerTargetScope, *, include_space_contents: bool = False
    ) -> tuple[BusinessResourceReference, ...]:
        self._check_scope(session, scope)
        with bypass_tenant_filter():
            return tuple(
                (
                    await session.execute(
                        self._target_query(
                            scope.targets, include_space_contents=include_space_contents
                        ).with_for_update()
                    )
                )
                .scalars()
                .all()
            )
