"""Frozen W3 read values and Owner ports; constructing a value grants nothing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    ReferenceState,
    SourceKey,
    SourceType,
    TargetKey,
    TargetType,
    normalize_references,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


SourceReadPurpose = Literal["execute", "inspect"]


def canonical_payload_json(value: dict) -> str:
    if not isinstance(value, dict):
        raise TypeError("source payload must be a JSON object")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_digest(payload_json: str) -> str:
    if not isinstance(payload_json, str) or canonical_payload_json(json.loads(payload_json)) != payload_json:
        raise ValueError("source payload must use canonical JSON")
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _text(value, label: str, maximum: int = 64) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be nonempty bounded text")


def _tenant(value) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("source tenant must be a positive integer")


@dataclass(frozen=True, slots=True)
class SourceReadRequest:
    source_type: SourceType
    source_id: str
    source_version: str | None = None
    purpose: SourceReadPurpose = "execute"
    inspect_token: str | None = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "source_type", SourceType(self.source_type))
        _text(self.source_id, "source ID")
        if self.source_version is not None:
            _text(self.source_version, "source version")
            if self.source_version == "__root__":
                raise ValueError("root guard is not a business source version")
        if self.purpose not in {"execute", "inspect"}:
            raise ValueError("source read purpose is execute or inspect")
        if self.inspect_token is not None:
            _text(self.inspect_token, "inspection evidence", 256)
            if self.purpose != "inspect":
                raise ValueError("inspection evidence cannot authorize execution")


@dataclass(frozen=True, slots=True)
class AuthorizedSourceSnapshot:
    source_key: SourceKey
    references: tuple[ReferenceSpec, ...]
    extractor_version: str
    configuration_digest: str
    payload_json: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.source_key, SourceKey):
            raise TypeError("source snapshot needs a real SourceKey")
        if not isinstance(self.references, tuple):
            raise TypeError("source references must be a tuple")
        object.__setattr__(self, "references", normalize_references(self.references))
        _text(self.extractor_version, "extractor version", 128)
        if self.configuration_digest != payload_digest(self.payload_json):
            raise ValueError("source configuration digest does not match its immutable payload")


@dataclass(frozen=True, slots=True)
class TransientTargetRequest:
    resource_type: Literal["workflow"]
    resource_id: str
    payload_json: str = field(repr=False)

    def __post_init__(self):
        if self.resource_type != "workflow":
            raise ValueError("only workflow has an unsaved preview entry")
        _text(self.resource_id, "preview root ID")
        payload_digest(self.payload_json)


@dataclass(frozen=True, slots=True)
class AuthorizedTransientSnapshot:
    resource_type: Literal["workflow"]
    resource_id: str
    owner_tenant_id: int
    references: tuple[ReferenceSpec, ...]
    extractor_version: str
    configuration_digest: str
    payload_json: str = field(repr=False)

    def __post_init__(self):
        TransientTargetRequest(self.resource_type, self.resource_id, self.payload_json)
        _tenant(self.owner_tenant_id)
        if not isinstance(self.references, tuple):
            raise TypeError("transient references must be a tuple")
        object.__setattr__(self, "references", normalize_references(self.references))
        _text(self.extractor_version, "extractor version", 128)
        if self.configuration_digest != payload_digest(self.payload_json):
            raise ValueError("transient configuration digest does not match its payload")


@dataclass(frozen=True, slots=True)
class ReadIdentityFacts:
    request_tenant_id: int
    fingerprint: Hashable = field(repr=False)

    def __post_init__(self):
        _tenant(self.request_tenant_id)
        hash(self.fingerprint)


@dataclass(frozen=True, slots=True)
class ReferenceTargetReadFact:
    key: TargetKey
    state: ReferenceState
    is_valid: bool
    target_tenant_id: int | None = None
    target_space_id: int | None = None

    def __post_init__(self):
        if not isinstance(self.key, TargetKey):
            raise TypeError("read target must be a TargetKey")
        object.__setattr__(self, "state", ReferenceState(self.state))
        if type(self.is_valid) is not bool:
            raise TypeError("read validity must be a bool")
        if self.state != ReferenceState.VALID and self.is_valid:
            raise ValueError("invalid lifecycle cannot be executable")
        if self.state == ReferenceState.VALID and not self.is_valid and self.key.target_type != TargetType.MODEL:
            raise ValueError("only a live model can have revoked binding eligibility")
        if self.target_tenant_id is None:
            if self.state != ReferenceState.INVALID_LEGACY:
                raise ValueError("only frozen legacy facts can have unknown target ownership")
        else:
            _tenant(self.target_tenant_id)
        if self.target_space_id is not None:
            _tenant(self.target_space_id)


def _result(snapshot, states) -> None:
    if not isinstance(states, tuple) or any(not isinstance(item, ReferenceTargetReadFact) for item in states):
        raise TypeError("read target states must be immutable facts")
    keys = tuple(item.key for item in states)
    if len(keys) != len(set(keys)) or set(keys) != {ref.target for ref in snapshot.references}:
        raise ValueError("read result must cover every exact configured target")


@dataclass(frozen=True, slots=True)
class SourceReferenceReadResult:
    snapshot: AuthorizedSourceSnapshot
    target_states: tuple[ReferenceTargetReadFact, ...]
    source_revision: int
    root_revision: int

    def __post_init__(self):
        if not isinstance(self.snapshot, AuthorizedSourceSnapshot):
            raise TypeError("saved result needs a saved source snapshot")
        _result(self.snapshot, self.target_states)
        if any(type(value) is not int or value < 0 for value in (self.source_revision, self.root_revision)):
            raise ValueError("source read revisions must be nonnegative integers")


@dataclass(frozen=True, slots=True)
class TransientReferenceReadResult:
    snapshot: AuthorizedTransientSnapshot
    target_states: tuple[ReferenceTargetReadFact, ...]

    def __post_init__(self):
        if not isinstance(self.snapshot, AuthorizedTransientSnapshot):
            raise TypeError("preview result needs a transient snapshot")
        _result(self.snapshot, self.target_states)


class SourceReadIdentityPort(Protocol):
    async def acapture(self, identity: object) -> ReadIdentityFacts: ...


class ReferenceSourceOwnerPort(Protocol):
    async def aresolve_source(
        self, session: AsyncSession, request: SourceReadRequest, identity: object
    ) -> AuthorizedSourceSnapshot: ...

    async def arevalidate_source(
        self,
        session: AsyncSession,
        request: SourceReadRequest,
        identity: object,
        expected: AuthorizedSourceSnapshot,
    ) -> AuthorizedSourceSnapshot: ...


class ReferenceTransientOwnerPort(Protocol):
    async def aresolve_transient(
        self, session: AsyncSession, request: TransientTargetRequest, identity: object
    ) -> AuthorizedTransientSnapshot: ...

    async def arevalidate_transient(
        self,
        session: AsyncSession,
        request: TransientTargetRequest,
        identity: object,
        expected: AuthorizedTransientSnapshot,
    ) -> AuthorizedTransientSnapshot: ...


class ReferenceTargetReadOwnerPort(Protocol):
    async def ainspect_source_targets(
        self, session: AsyncSession, scope: object, target_keys: tuple[TargetKey, ...], *, identity: object
    ) -> tuple[ReferenceTargetReadFact, ...]: ...

    async def ainspect_transient_targets(
        self, session: AsyncSession, scope: object, target_keys: tuple[TargetKey, ...], *, identity: object
    ) -> tuple[ReferenceTargetReadFact, ...]: ...
