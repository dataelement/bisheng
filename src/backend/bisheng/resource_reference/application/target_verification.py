"""Issue transaction-bound authority only after calling registered Owners.

The registry is per explicitly constructed Verifier, never module-global.
Callers cannot turn an observation or an issuer object into a capability.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal
from weakref import ReferenceType, WeakKeyDictionary, ref

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.resource_reference.application.contracts import (
    ReferenceTargetOwnerPort,
    SourceKey,
    TargetKey,
    TargetLockReceipt,
    TargetType,
    TransactionIdentity,
    VerifiedReferenceTarget,
)


@dataclass(frozen=True, slots=True)
class _IssuedVerification:
    source_key: SourceKey | None
    operation: Literal["bind", "owner_query"]
    actor_tenant_id: int
    targets: tuple[TargetKey, ...]
    transaction: TransactionIdentity
    batch_id: object


def _invalid(reason: str) -> ResourceReferenceInvalidError:
    return ResourceReferenceInvalidError(reason=reason)


class ReferenceTargetVerifier:
    def __init__(self, owners: Mapping[TargetType, ReferenceTargetOwnerPort]):
        registered = {TargetType(kind): owner for kind, owner in owners.items()}
        if any(
            not callable(getattr(owner, "lock_and_verify", None))
            or not callable(getattr(owner, "alock_and_verify", None))
            for owner in registered.values()
        ):
            raise TypeError("registered target Owners must provide sync and async verification")
        self._owners = MappingProxyType(registered)
        self._issued: WeakKeyDictionary[TargetLockReceipt, tuple[ReferenceType, _IssuedVerification]] = (
            WeakKeyDictionary()
        )

    @staticmethod
    def _tenant_id() -> int:
        if is_tenant_filter_bypassed():
            raise _invalid("reference_verification_tenant_bypassed")
        value = _resolve_tenant_id()
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _invalid("reference_verification_tenant_missing")
        return value

    @staticmethod
    def _keys(target_keys) -> tuple[TargetKey, ...]:
        if not isinstance(target_keys, tuple) or any(not isinstance(key, TargetKey) for key in target_keys):
            raise _invalid("reference_target_keys_required")
        return tuple(sorted(set(target_keys), key=lambda key: key.lock_order_key))

    def _plan(self, session, source_key, target_keys, operation):
        tenant_id = self._tenant_id()
        if operation == "bind" and (not isinstance(source_key, SourceKey) or source_key.tenant_id != tenant_id):
            raise _invalid("source_tenant_mismatch")
        keys = self._keys(target_keys)
        if operation == "owner_query" and not keys:
            raise _invalid("reference_owner_query_empty")
        identity = TransactionIdentity.capture(session)
        groups = []
        for key in keys:
            owner = self._owners.get(key.target_type)
            if owner is None:
                raise _invalid("reference_target_owner_unregistered")
            group = next((group for group in groups if group[0] is owner), None)
            if group is None:
                groups.append((owner, [key]))
            else:
                group[1].append(key)
        return tenant_id, keys, identity, tuple((owner, tuple(group_keys)) for owner, group_keys in groups)

    def _check_owner_result(self, session, identity, owner, group_keys, source_key, operation, tenant_id, result):
        identity.assert_current(session)
        if (
            not isinstance(result, tuple)
            or len(result) != len(group_keys)
            or any(not isinstance(receipt, TargetLockReceipt) for receipt in result)
        ):
            raise _invalid("reference_owner_result_incomplete")
        if {receipt.target.key for receipt in result} != set(group_keys):
            raise _invalid("reference_owner_result_targets_changed")
        for receipt in result:
            if (
                receipt in self._issued
                or receipt.issuer is not owner
                or receipt.source_key != source_key
                or not isinstance(receipt.target, VerifiedReferenceTarget)
                or (operation == "owner_query" and receipt.target.target_tenant_id != tenant_id)
            ):
                raise _invalid("reference_owner_result_invalid")
            receipt.transaction.assert_current(session)

    def _register(self, source_key, operation, tenant_id, keys, identity, receipts):
        registration = _IssuedVerification(source_key, operation, tenant_id, keys, identity, object())
        for receipt in receipts:
            self._issued[receipt] = (ref(receipt), registration)
        return tuple(sorted(receipts, key=lambda receipt: receipt.target.key.lock_order_key))

    def _verify(self, session, source_key, target_keys, operation):
        tenant_id, keys, identity, groups = self._plan(session, source_key, target_keys, operation)
        receipts = []
        for owner, group_keys in groups:
            result = owner.lock_and_verify(session, group_keys, source_key, operation)
            self._check_owner_result(session, identity, owner, group_keys, source_key, operation, tenant_id, result)
            receipts.extend(result)
        identity.assert_current(session)
        return self._register(source_key, operation, tenant_id, keys, identity, receipts)

    async def _averify(self, session, source_key, target_keys, operation):
        tenant_id, keys, identity, groups = self._plan(session, source_key, target_keys, operation)
        receipts = []
        for owner, group_keys in groups:
            result = await owner.alock_and_verify(session, group_keys, source_key, operation)
            self._check_owner_result(session, identity, owner, group_keys, source_key, operation, tenant_id, result)
            receipts.extend(result)
        identity.assert_current(session)
        return self._register(source_key, operation, tenant_id, keys, identity, receipts)

    def verify_targets(self, session: Session, source_key: SourceKey, target_keys: tuple[TargetKey, ...]):
        return self._verify(session, source_key, target_keys, "bind")

    async def averify_targets(self, session: AsyncSession, source_key: SourceKey, target_keys: tuple[TargetKey, ...]):
        return await self._averify(session, source_key, target_keys, "bind")

    def _batch_plan(self, session, requests):
        if not isinstance(requests, tuple) or not requests:
            raise _invalid("reference_batch_sources_required")
        tenant_id = self._tenant_id()
        planned = []
        for item in requests:
            if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], SourceKey):
                raise _invalid("reference_batch_sources_required")
            source, targets = item
            if source.tenant_id != tenant_id:
                raise _invalid("source_tenant_mismatch")
            planned.append((source, self._keys(targets)))
        sources = tuple(source for source, _ in planned)
        if (
            len(set(sources)) != len(sources)
            or len({(key.tenant_id, key.source_type, key.source_id) for key in sources}) != 1
        ):
            raise _invalid("reference_batch_root_mismatch")
        planned.sort(key=lambda item: item[0].source_version)
        sources = tuple(source for source, _ in planned)
        union = self._keys(tuple(target for _, targets in planned for target in targets))
        _, _, identity, groups = self._plan(session, sources[0], union, "bind")
        return tuple(planned), sources, identity, groups

    def verify_batch_targets(self, session: Session, requests):
        """Lock each Owner's physical union once, then verify each real source."""
        planned, sources, identity, groups = self._batch_plan(session, requests)
        for owner, targets in groups:
            prelock = getattr(owner, "prelock_targets", None)
            if not callable(prelock):
                raise ReferenceCoverageNotReadyError(reason="reference_batch_prelock_unavailable")
            if prelock(session, targets, sources) is not None:
                raise _invalid("reference_prelock_must_not_issue_receipts")
            identity.assert_current(session)
        issued = {source: self._verify(session, source, targets, "bind") for source, targets in planned}
        identity.assert_current(session)
        return MappingProxyType(issued)

    async def averify_batch_targets(self, session: AsyncSession, requests):
        planned, sources, identity, groups = self._batch_plan(session, requests)
        for owner, targets in groups:
            prelock = getattr(owner, "aprelock_targets", None)
            if not callable(prelock):
                raise ReferenceCoverageNotReadyError(reason="reference_batch_prelock_unavailable")
            if await prelock(session, targets, sources) is not None:
                raise _invalid("reference_prelock_must_not_issue_receipts")
            identity.assert_current(session)
        issued = {}
        for source, targets in planned:
            issued[source] = await self._averify(session, source, targets, "bind")
        identity.assert_current(session)
        return MappingProxyType(issued)

    def verify_owner_targets(self, session: Session, target_keys: tuple[TargetKey, ...]):
        return self._verify(session, None, target_keys, "owner_query")

    async def averify_owner_targets(self, session: AsyncSession, target_keys: tuple[TargetKey, ...]):
        return await self._averify(session, None, target_keys, "owner_query")

    def _validate(self, session, source_key, receipts, keys, operation):
        tenant_id = self._tenant_id()
        TransactionIdentity.capture(session)
        if not isinstance(receipts, tuple) or len(receipts) != len(keys):
            raise _invalid("reference_receipt_set_incomplete")
        if not keys and operation == "bind":
            return ()
        if not keys or any(not isinstance(receipt, TargetLockReceipt) for receipt in receipts):
            raise _invalid("reference_receipt_not_issued")
        issued = [self._issued.get(receipt) for receipt in receipts]
        if any(item is None or item[0]() is not receipt for item, receipt in zip(issued, receipts, strict=True)):
            raise _invalid("reference_receipt_not_issued")
        registrations = [item[1] for item in issued]
        registration = registrations[0]
        if registration is None or any(item is not registration for item in registrations):
            raise _invalid("reference_receipt_not_issued")
        if (
            registration.source_key != source_key
            or registration.operation != operation
            or registration.actor_tenant_id != tenant_id
            or registration.targets != keys
            or {receipt.target.key for receipt in receipts} != set(keys)
        ):
            raise _invalid("reference_receipt_scope_mismatch")
        try:
            registration.transaction.assert_current(session)
            for receipt in receipts:
                receipt.transaction.assert_current(session)
        except (TypeError, ValueError) as exc:
            raise _invalid("reference_receipt_expired") from exc
        return tuple(receipt.target for receipt in receipts)

    def validate_binding_receipts(
        self, session, source_key, receipts, target_keys
    ) -> tuple[VerifiedReferenceTarget, ...]:
        if not isinstance(source_key, SourceKey) or source_key.tenant_id != self._tenant_id():
            raise _invalid("source_tenant_mismatch")
        return self._validate(session, source_key, receipts, self._keys(target_keys), "bind")

    def validate_owner_receipts(self, session, receipts) -> tuple[VerifiedReferenceTarget, ...]:
        if not isinstance(receipts, tuple) or any(not isinstance(receipt, TargetLockReceipt) for receipt in receipts):
            raise _invalid("reference_receipt_not_issued")
        keys = self._keys(tuple(receipt.target.key for receipt in receipts))
        return self._validate(session, None, receipts, keys, "owner_query")
