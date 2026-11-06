"""Bounded internal metadata disclosure; source visibility grants no execution."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, TransactionIdentity
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity


@dataclass(frozen=True, slots=True)
class SourceDisclosure:
    source: SourceKey
    name: str
    version_label: str | None
    entry: str | None

    def __post_init__(self):
        if not isinstance(self.source, SourceKey) or type(self.name) is not str:
            raise TypeError("disclosure requires a SourceKey and a real name")
        if any(value is not None and type(value) is not str for value in (self.version_label, self.entry)):
            raise TypeError("disclosure labels and entries must be text or None")


class SourceDisclosurePort(Protocol):
    async def adisclose_sources(
        self, session, *, identity, source_keys: tuple[SourceKey, ...]
    ) -> tuple[SourceDisclosure | None, ...]: ...


class SourceDisclosureRuntime:
    def __init__(self, owners, *, identity_port=None):
        if not isinstance(owners, dict) or any(not isinstance(kind, SourceType) for kind in owners):
            raise TypeError("disclosure owners must be keyed by SourceType")
        self.owners = MappingProxyType(dict(owners))
        self.identity = identity_port if identity_port is not None else AuthenticatedSourceReadIdentity()

    async def adisclose_sources(
        self, session, *, identity, source_keys: tuple[SourceKey, ...]
    ) -> tuple[SourceDisclosure | None, ...]:
        if (
            type(source_keys) is not tuple
            or len(source_keys) > 200
            or any(not isinstance(key, SourceKey) for key in source_keys)
        ):
            raise ReferenceCoverageNotReadyError(reason="source_disclosure_invalid_batch")
        if not source_keys:
            return ()
        try:
            original = await self.identity.acapture(identity)
            transaction = TransactionIdentity.capture(session)
            groups = {}
            for index, key in enumerate(source_keys):
                if key.tenant_id == original.request_tenant_id:
                    groups.setdefault(key.source_type, []).append((index, key))
            result = [None] * len(source_keys)
            for kind, values in groups.items():
                owner = self.owners.get(kind)
                method = getattr(owner, "adisclose_sources", None)
                if not callable(method):
                    raise ReferenceCoverageNotReadyError(reason="source_disclosure_owner_unconfigured")
                requested = tuple(key for _, key in values)
                actual = await method(session, identity=identity, source_keys=requested)
                if type(actual) is not tuple or len(actual) != len(requested):
                    raise ReferenceCoverageNotReadyError(reason="source_disclosure_incomplete_result")
                for (index, key), item in zip(values, actual, strict=True):
                    if item is not None and (not isinstance(item, SourceDisclosure) or item.source != key):
                        raise ReferenceCoverageNotReadyError(reason="source_disclosure_mismatched_result")
                    result[index] = item
                transaction.assert_current(session)
            if await self.identity.acapture(identity) != original:
                raise ReferenceCoverageNotReadyError(reason="source_disclosure_identity_changed")
            transaction.assert_current(session)
            return tuple(result)
        except ReferenceCoverageNotReadyError:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="source_disclosure_failed") from error
