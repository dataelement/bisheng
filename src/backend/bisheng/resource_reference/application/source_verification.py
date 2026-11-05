"""Issue exact-source read authority after calling registered business Owners.

Scopes and target plans are private, transaction-bound objects. Neither a DTO
nor a caller-supplied target observation can mint a root revalidation plan.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.resource_reference.application.contracts import SourceType, TargetKey, TargetType, TransactionIdentity
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    ReadIdentityFacts,
    ReferenceTargetReadFact,
    SourceReadRequest,
    TransientTargetRequest,
)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class SourceOwnerReadScope:
    snapshot: AuthorizedSourceSnapshot = field(repr=False)
    purpose: str
    _nonce: object = field(default_factory=object, repr=False)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class TransientTargetReadScope:
    snapshot: AuthorizedTransientSnapshot = field(repr=False)
    purpose: str = "preview"
    _nonce: object = field(default_factory=object, repr=False)


@dataclass
class _Registration:
    owner: object
    request: SourceReadRequest | TransientTargetRequest
    snapshot: AuthorizedSourceSnapshot | AuthorizedTransientSnapshot
    identity: object
    facts: ReadIdentityFacts
    transaction: TransactionIdentity
    nonce: object
    target_plan: tuple[ReferenceTargetReadFact, ...] | None = None


def _invalid(reason="reference_read_scope_invalid"):
    return ResourceReferenceInvalidError(reason=reason)


class SourceReadVerifier:
    def __init__(self, owners: Mapping, identity_port):
        registered = {SourceType(kind): owner for kind, owner in owners.items()}
        if not callable(getattr(identity_port, "acapture", None)) or any(
            not callable(getattr(owner, method, None))
            for owner in registered.values()
            for method in ("aresolve_source", "arevalidate_source")
        ):
            raise TypeError("source reads require real SourceOwner and identity ports")
        self._owners = MappingProxyType(registered)
        self._identity_port = identity_port
        self._issued = WeakKeyDictionary()
        self._target_owners = None

    async def _identity(self, identity):
        tenant = _resolve_tenant_id()
        if identity is None or is_tenant_filter_bypassed() or type(tenant) is not int or tenant <= 0:
            raise _invalid()
        facts = await self._identity_port.acapture(identity)
        if not isinstance(facts, ReadIdentityFacts) or facts.request_tenant_id != tenant:
            raise _invalid()
        return ReadIdentityFacts(tenant, deepcopy(facts.fingerprint))

    @staticmethod
    def _transaction(session):
        try:
            return TransactionIdentity.capture(session)
        except (TypeError, ValueError) as exc:
            raise _invalid() from exc

    @staticmethod
    def _source_result(request, snapshot):
        if (
            not isinstance(snapshot, AuthorizedSourceSnapshot)
            or snapshot.source_key.source_type != request.source_type
            or snapshot.source_key.source_id != request.source_id
            or (request.source_version is not None and snapshot.source_key.source_version != request.source_version)
        ):
            raise _invalid("reference_source_owner_result_invalid")

    @staticmethod
    def _transient_result(request, snapshot):
        if not isinstance(snapshot, AuthorizedTransientSnapshot) or (
            snapshot.resource_type,
            snapshot.resource_id,
            snapshot.payload_json,
        ) != (request.resource_type, request.resource_id, request.payload_json):
            raise _invalid("reference_source_owner_result_invalid")

    async def _issue(self, session, request, identity, *, transient):
        if not isinstance(session, AsyncSession):
            raise _invalid()
        facts = await self._identity(identity)
        kind = SourceType.WORKFLOW_VERSION if transient else request.source_type
        owner = self._owners.get(kind)
        method = "aresolve_transient" if transient else "aresolve_source"
        if owner is None or not callable(getattr(owner, method, None)):
            raise ReferenceCoverageNotReadyError(reason="reference_source_owner_unconfigured")
        # A fresh external Session may autobegin on its Owner's first business
        # SELECT. Existing transactions must retain their exact identity.
        before = self._transaction(session) if session.sync_session.get_transaction() is not None else None
        with session.no_autoflush:
            snapshot = await getattr(owner, method)(session, request, identity)
        (self._transient_result if transient else self._source_result)(request, snapshot)
        transaction = self._transaction(session)
        if before is not None:
            try:
                before.assert_current(session)
            except (TypeError, ValueError) as exc:
                raise _invalid() from exc
        if await self._identity(identity) != facts:
            raise _invalid()
        scope = TransientTargetReadScope(snapshot) if transient else SourceOwnerReadScope(snapshot, request.purpose)
        self._issued[scope] = _Registration(owner, request, snapshot, identity, facts, transaction, scope._nonce)
        return scope

    async def aissue_scope(self, session, request, identity):
        if not isinstance(request, SourceReadRequest):
            raise _invalid()
        return await self._issue(session, request, identity, transient=False)

    async def aissue_transient_scope(self, session, request, identity):
        if not isinstance(request, TransientTargetRequest):
            raise _invalid()
        return await self._issue(session, request, identity, transient=True)

    async def _registration(self, session, scope, identity):
        if not isinstance(scope, (SourceOwnerReadScope, TransientTargetReadScope)):
            raise _invalid()
        registration = self._issued.get(scope)
        if (
            registration is None
            or registration.identity is not identity
            or scope.snapshot is not registration.snapshot
            or scope._nonce is not registration.nonce
            or scope.purpose != (registration.request.purpose if isinstance(scope, SourceOwnerReadScope) else "preview")
        ):
            raise _invalid()
        try:
            registration.transaction.assert_current(session)
        except (TypeError, ValueError) as exc:
            raise _invalid() from exc
        if await self._identity(identity) != registration.facts:
            raise _invalid()
        return registration

    async def aget_source_snapshot(self, session, scope, identity):
        if not isinstance(scope, SourceOwnerReadScope):
            raise _invalid()
        return (await self._registration(session, scope, identity)).snapshot

    async def aget_transient_snapshot(self, session, scope, identity):
        if not isinstance(scope, TransientTargetReadScope):
            raise _invalid()
        return (await self._registration(session, scope, identity)).snapshot

    async def aassert_target_keys(self, session, scope, identity, target_keys, *, allowed_types):
        registration = await self._registration(session, scope, identity)
        types = {TargetType(kind) for kind in allowed_types}
        expected = {ref.target for ref in registration.snapshot.references if ref.target.target_type in types}
        if (
            not isinstance(target_keys, tuple)
            or any(not isinstance(key, TargetKey) for key in target_keys)
            or len(target_keys) != len(set(target_keys))
            or set(target_keys) != expected
        ):
            raise _invalid("reference_read_target_plan_changed")
        return registration.snapshot

    def _install_target_owners(self, owners):
        registered = {TargetType(kind): owner for kind, owner in owners.items()}
        if any(
            not callable(getattr(owner, method, None))
            for owner in registered.values()
            for method in ("ainspect_source_targets", "ainspect_transient_targets")
        ):
            raise TypeError("read targets require native async TargetOwner ports")
        if self._target_owners is not None and (
            self._target_owners.keys() != registered.keys()
            or any(self._target_owners[kind] is not owner for kind, owner in registered.items())
        ):
            raise ValueError("a source authority cannot replace its registered target Owners")
        self._target_owners = MappingProxyType(registered)

    async def _ainspect_targets(self, session, scope, identity):
        registration = await self._registration(session, scope, identity)
        registration.target_plan = None
        if self._target_owners is None:
            raise ReferenceCoverageNotReadyError(reason="reference_read_targets_unconfigured")
        keys = tuple(sorted({ref.target for ref in registration.snapshot.references}, key=lambda k: k.lock_order_key))
        groups = []
        for key in keys:
            owner = self._target_owners.get(key.target_type)
            if owner is None:
                raise ReferenceCoverageNotReadyError(reason="reference_read_target_owner_unconfigured")
            group = next((group for group in groups if group[0] is owner), None)
            if group is None:
                groups.append((owner, [key]))
            else:
                group[1].append(key)
        facts = []
        method = "ainspect_source_targets" if isinstance(scope, SourceOwnerReadScope) else "ainspect_transient_targets"
        for owner, group in groups:
            with session.no_autoflush:
                result = await getattr(owner, method)(session, scope, tuple(group), identity=identity)
            if (
                not isinstance(result, tuple)
                or len(result) != len(group)
                or any(not isinstance(fact, ReferenceTargetReadFact) for fact in result)
                or {fact.key for fact in result} != set(group)
            ):
                raise _invalid("reference_read_target_owner_result_invalid")
            await self._registration(session, scope, identity)
            facts.extend(result)
        registration.target_plan = tuple(sorted(facts, key=lambda fact: fact.key.lock_order_key))
        return registration.target_plan

    async def _revalidate(self, session, scope, identity, *, transient):
        if not isinstance(scope, TransientTargetReadScope if transient else SourceOwnerReadScope):
            raise _invalid()
        registration = await self._registration(session, scope, identity)
        if registration.target_plan is None:
            raise _invalid("reference_read_target_plan_required")
        registration.target_plan = None
        method = "arevalidate_transient" if transient else "arevalidate_source"
        if not callable(getattr(registration.owner, method, None)):
            raise ReferenceCoverageNotReadyError(reason="reference_source_owner_unconfigured")
        with session.no_autoflush:
            current = await getattr(registration.owner, method)(
                session, registration.request, identity, registration.snapshot
            )
        await self._registration(session, scope, identity)
        if current != registration.snapshot:
            raise KnowledgeOperationPlanConflictError(reason="reference_read_source_changed")
        return registration.snapshot

    async def arevalidate_scope(self, session, scope, identity):
        return await self._revalidate(session, scope, identity, transient=False)

    async def arevalidate_transient_scope(self, session, scope, identity):
        return await self._revalidate(session, scope, identity, transient=True)
