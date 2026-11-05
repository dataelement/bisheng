"""F118 internal reference contracts: identities, transaction receipts and sets.

These objects are application protocols, never HTTP request schemas. Target
Owners issue receipts after verifying and locking their business rows. Binding
writers validate the issuer against their registered Owner and consume receipts
in the same active SQL transaction; a bare target ID is not a verified target.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

ROOT_GUARD_VERSION = "__root__"
CURRENT_SOURCE_VERSION = "current"
REFERENCE_DIGEST_VERSION = "sha256-reference-set-v1"
RECEIPT_SCHEMA_VERSION = 1


class TargetType(StrEnum):
    MODEL = "model"
    KNOWLEDGE_SPACE = "knowledge_space"
    KNOWLEDGE_FILE = "knowledge_file"


class SourceType(StrEnum):
    WORKFLOW_VERSION = "workflow_version"
    ASSISTANT = "assistant"
    HOSTED_APP_VERSION = "hosted_app_version"
    CHANNEL_SYNC = "channel_sync"
    KNOWLEDGE = "knowledge"
    MODEL_DEFAULT = "model_default"


class ReferenceState(StrEnum):
    VALID = "valid"
    DELETING = "deleting"
    INVALID_DELETED = "invalid_deleted"
    INVALID_LEGACY = "invalid_legacy"


class ReferenceSetKind(StrEnum):
    SOURCE = "source"
    ROOT_GUARD = "root_guard"


class TargetDeleteStage(StrEnum):
    DELETING = "deleting"
    DELETED = "deleted"


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _revision(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _text(value: str, name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA256 digest")


def canonical_target_id(value: str | int) -> str:
    """Normalize an Owner-verified numeric entity ID without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("target ID must be a positive decimal entity ID")
    candidate = str(value)
    if not candidate.isascii() or not candidate.isdecimal() or len(candidate) > 64 or int(candidate) <= 0:
        raise ValueError("target ID must be a positive decimal entity ID of at most 64 digits")
    return str(int(candidate))


@dataclass(frozen=True, slots=True)
class SourceKey:
    tenant_id: int
    source_type: SourceType
    source_id: str
    source_version: str

    def __post_init__(self) -> None:
        _positive_integer(self.tenant_id, "source tenant")
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        _text(self.source_id, "source ID", 64)
        _text(self.source_version, "source version", 64)
        if self.source_version == ROOT_GUARD_VERSION:
            raise ValueError("root guard version is reserved for the binding Repository")


@dataclass(frozen=True, slots=True)
class TargetKey:
    target_type: TargetType
    target_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_type", TargetType(self.target_type))
        object.__setattr__(self, "target_id", canonical_target_id(self.target_id))

    @property
    def lock_order_key(self) -> tuple[int, int]:
        return (tuple(TargetType).index(self.target_type), int(self.target_id))


@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    slot_key: str
    target: TargetKey

    def __post_init__(self) -> None:
        _text(self.slot_key, "reference slot", 192)
        if not isinstance(self.target, TargetKey):
            raise TypeError("reference target must be a TargetKey")


def normalize_references(references: tuple[ReferenceSpec, ...]) -> tuple[ReferenceSpec, ...]:
    if any(not isinstance(reference, ReferenceSpec) for reference in references):
        raise TypeError("references must contain only ReferenceSpec values")
    return tuple(
        sorted(set(references), key=lambda ref: (ref.slot_key, ref.target.target_type.value, ref.target.target_id))
    )


def reference_set_digest(references: tuple[ReferenceSpec, ...]) -> str:
    """Hash configuration identities; moving a file must not rewrite its sources."""
    canonical = [
        (reference.slot_key, reference.target.target_type.value, reference.target.target_id)
        for reference in normalize_references(references)
    ]
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyEvidence:
    run_id: str
    baseline_hash: str
    evidence_key: str

    def __post_init__(self) -> None:
        _text(self.run_id, "legacy run ID", 64)
        _digest(self.baseline_hash, "legacy baseline hash")
        _text(self.evidence_key, "legacy evidence key", 128)


@dataclass(frozen=True, slots=True)
class DeletionEvidence:
    operation_id: str
    target: TargetKey
    target_tenant_id: int
    stage: TargetDeleteStage

    def __post_init__(self) -> None:
        _text(self.operation_id, "delete operation ID", 64)
        if not isinstance(self.target, TargetKey):
            raise TypeError("deletion evidence must identify a TargetKey")
        _positive_integer(self.target_tenant_id, "deleted target tenant")
        object.__setattr__(self, "stage", TargetDeleteStage(self.stage))


@dataclass(frozen=True, slots=True)
class VerifiedReferenceTarget:
    key: TargetKey
    target_tenant_id: int | None
    target_space_id: str | None
    model_server_id: str | None
    state: ReferenceState
    target_revision: str
    evidence: LegacyEvidence | DeletionEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, TargetKey):
            raise TypeError("verified target must contain a TargetKey")
        object.__setattr__(self, "state", ReferenceState(self.state))
        _text(self.target_revision, "target revision", 64)
        if self.target_tenant_id is None:
            if self.state != ReferenceState.INVALID_LEGACY or not isinstance(self.evidence, LegacyEvidence):
                raise ValueError("unknown target tenant requires registered legacy evidence")
        else:
            _positive_integer(self.target_tenant_id, "target tenant")
        if self.state == ReferenceState.INVALID_LEGACY and not isinstance(self.evidence, LegacyEvidence):
            raise ValueError("legacy invalid targets require frozen baseline evidence")
        if self.state in (ReferenceState.DELETING, ReferenceState.INVALID_DELETED) and not isinstance(
            self.evidence, DeletionEvidence
        ):
            raise ValueError("deleted targets require the original deletion evidence")
        if self.state == ReferenceState.VALID and self.evidence is not None:
            raise ValueError("live targets do not carry deletion or legacy evidence")
        if isinstance(self.evidence, DeletionEvidence):
            if self.evidence.target != self.key or self.evidence.target_tenant_id != self.target_tenant_id:
                raise ValueError("deletion evidence belongs to a different target or owner")
            expected_stage = (
                TargetDeleteStage.DELETING if self.state == ReferenceState.DELETING else TargetDeleteStage.DELETED
            )
            if self.evidence.stage != expected_stage:
                raise ValueError("deletion evidence does not match the verified target phase")
        if self.target_space_id is not None:
            object.__setattr__(self, "target_space_id", canonical_target_id(self.target_space_id))
        if self.model_server_id is not None:
            object.__setattr__(self, "model_server_id", canonical_target_id(self.model_server_id))
        if self.key.target_type == TargetType.MODEL and self.target_space_id is not None:
            raise ValueError("model targets do not belong to a knowledge space")
        if self.key.target_type != TargetType.MODEL and self.model_server_id is not None:
            raise ValueError("knowledge targets do not carry a model server ID")
        if self.key.target_type == TargetType.KNOWLEDGE_SPACE and self.target_space_id not in (
            None,
            self.key.target_id,
        ):
            raise ValueError("space target ownership must refer to itself")
        if self.key.target_type == TargetType.KNOWLEDGE_FILE and self.state == ReferenceState.VALID:
            if self.target_space_id is None:
                raise ValueError("live file targets require their verified space")
        if self.key.target_type == TargetType.MODEL and self.state == ReferenceState.VALID:
            if self.model_server_id is None:
                raise ValueError("live model targets require their verified model server")


def _active_transaction(session: Session | AsyncSession) -> SessionTransaction:
    actual_session = session.sync_session if isinstance(session, AsyncSession) else session
    if not isinstance(actual_session, Session):
        raise TypeError("reference writes require a SQLAlchemy Session or AsyncSession")
    transaction = actual_session.get_nested_transaction() or actual_session.get_transaction()
    if transaction is None or not transaction.is_active or not actual_session.is_active:
        raise ValueError("reference receipt requires an active SQL transaction")
    return transaction


@dataclass(frozen=True, slots=True, eq=False)
class TransactionIdentity:
    session: Session | AsyncSession = field(repr=False, compare=False)
    transaction: SessionTransaction = field(repr=False, compare=False)

    @classmethod
    def capture(cls, session: Session | AsyncSession) -> TransactionIdentity:
        return cls(session=session, transaction=_active_transaction(session))

    def assert_current(self, session: Session | AsyncSession) -> None:
        if self.session is not session or self.transaction is not _active_transaction(session):
            raise ValueError("reference receipt belongs to a different SQL transaction")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class TargetLockReceipt:
    """An Owner result; authority exists only after the Verifier registers it.

    Public fields, an issuer pointer or reconstructing this dataclass do not
    prove that Owner verification ran. None source is reserved for owner_query.
    """

    source_key: SourceKey | None
    target: VerifiedReferenceTarget
    transaction: TransactionIdentity
    issuer: object = field(repr=False, compare=False)
    schema_version: int = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECEIPT_SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError("unsupported reference receipt schema")
        if self.issuer is None:
            raise ValueError("target receipt requires its registered Owner issuer")
        self.transaction.assert_current(self.transaction.session)


@dataclass(frozen=True, slots=True)
class BindingWriteContext:
    source_key: SourceKey
    expected_root_revision: int
    locked_root_revision: int
    locked_targets: tuple[TargetKey, ...]
    old_references_digest: str
    receipts: tuple[TargetLockReceipt, ...]
    transaction: TransactionIdentity
    receipt_schema_version: int = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _revision(self.expected_root_revision, "expected root revision")
        _revision(self.locked_root_revision, "locked root revision")
        _digest(self.old_references_digest, "old references digest")
        if self.receipt_schema_version != RECEIPT_SCHEMA_VERSION or isinstance(self.receipt_schema_version, bool):
            raise ValueError("unsupported reference write context schema")
        canonical_targets = tuple(sorted(set(self.locked_targets), key=lambda key: key.lock_order_key))
        if self.locked_targets != canonical_targets:
            raise ValueError("target lock set must be unique and in canonical lock order")
        if len(self.receipts) != len(self.locked_targets) or {r.target.key for r in self.receipts} != set(
            self.locked_targets
        ):
            raise ValueError("target receipts must cover the complete locked target set")
        self.transaction.assert_current(self.transaction.session)
        for receipt in self.receipts:
            if receipt.source_key != self.source_key:
                raise ValueError("target receipt belongs to another source")
            receipt.transaction.assert_current(self.transaction.session)


@dataclass(frozen=True, slots=True)
class VerifiedReferenceSet:
    references: tuple[ReferenceSpec, ...]
    extractor_version: str
    context: BindingWriteContext

    def __post_init__(self) -> None:
        _text(self.extractor_version, "extractor version", 64)
        object.__setattr__(self, "references", normalize_references(self.references))
        if not {reference.target for reference in self.references}.issubset(self.context.locked_targets):
            raise ValueError("reference set contains a target outside its verified lock set")

    @property
    def digest(self) -> str:
        return reference_set_digest(self.references)


@dataclass(frozen=True, slots=True)
class BindingReplaceResult:
    source_key: SourceKey
    source_revision: int
    root_revision: int
    digest: str
    added: int
    removed: int
    retained_invalid: int


@dataclass(frozen=True, slots=True)
class CoverageStatus:
    tenant_id: int
    source_type: SourceType
    writer_contract_version: str
    ready: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        _positive_integer(self.tenant_id, "coverage tenant")
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        _text(self.writer_contract_version, "writer contract version", 64)
        if not self.ready and not self.reason:
            raise ValueError("unready reference coverage requires an explicit reason")


class CoveragePort(Protocol):
    def get_status(self, tenant_id: int, source_type: SourceType, writer_contract_version: str) -> CoverageStatus: ...

    async def aget_status(
        self, tenant_id: int, source_type: SourceType, writer_contract_version: str
    ) -> CoverageStatus: ...


def tenant_inventory_digest(tenant_ids: tuple[int, ...]) -> str:
    """Canonical inventory: sorted unique positive JSON integers, UTF-8, no spaces."""
    for tenant_id in tenant_ids:
        _positive_integer(tenant_id, "inventory tenant")
    if tenant_ids != tuple(sorted(set(tenant_ids))):
        raise ValueError("verified tenant inventory must be unique and sorted")
    return hashlib.sha256(json.dumps(tenant_ids, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GlobalCoverageStatus:
    """Internal complete tenant-inventory evidence, never an HTTP response DTO."""

    ready: bool
    writer_contract_version: str
    source_types: tuple[SourceType, ...]
    tenant_inventory_hash: str | None
    coverage_epoch: int
    verified_tenant_ids: tuple[int, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.writer_contract_version, "writer contract version", 64)
        _revision(self.coverage_epoch, "coverage epoch")
        object.__setattr__(self, "source_types", tuple(SourceType(value) for value in self.source_types))
        if self.ready:
            if len(self.source_types) != len(SourceType) or set(self.source_types) != set(SourceType):
                raise ValueError("global readiness requires every source type exactly once")
            if self.coverage_epoch == 0 or not self.verified_tenant_ids:
                raise ValueError("global readiness requires a verified nonempty tenant inventory and epoch")
            if self.tenant_inventory_hash != tenant_inventory_digest(self.verified_tenant_ids):
                raise ValueError("global tenant inventory hash does not match")


class GlobalCoveragePort(Protocol):
    def get_global_status(self, writer_contract_version: str) -> GlobalCoverageStatus: ...

    async def aget_global_status(self, writer_contract_version: str) -> GlobalCoverageStatus: ...


class ReferenceTargetOwnerPort(Protocol):
    """Business-owned, Repository-backed facts and authorization.

    bind receives a real source; owner_query receives None and must verify
    actual target ownership. Both stay in the caller's active SQL transaction.
    A shared Owner receives all its target kinds in one lock plan.
    """

    def prelock_targets(
        self, session: Session, target_keys: tuple[TargetKey, ...], source_keys: tuple[SourceKey, ...]
    ) -> None:
        """Physical union lock only: no binding, sharing or legacy authority."""
        ...

    async def aprelock_targets(
        self, session: AsyncSession, target_keys: tuple[TargetKey, ...], source_keys: tuple[SourceKey, ...]
    ) -> None: ...

    def lock_and_verify(
        self,
        session: Session,
        target_keys: tuple[TargetKey, ...],
        source_key: SourceKey | None,
        operation: Literal["bind", "owner_query"],
    ) -> tuple[TargetLockReceipt, ...]: ...

    async def alock_and_verify(
        self,
        session: AsyncSession,
        target_keys: tuple[TargetKey, ...],
        source_key: SourceKey | None,
        operation: Literal["bind", "owner_query"],
    ) -> tuple[TargetLockReceipt, ...]: ...
