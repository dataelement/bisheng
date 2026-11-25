"""Startup-owned allowlist; a provider key is never a module path."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PortContext:
    tenant_id: int
    space_id: int
    provider_key: str
    operation: str
    instance_id: int | None = None
    generation: int | None = None
    remote_scope_id: str | None = None
    remote_kb_id: str | None = None


class ProviderFactory(Protocol):
    def capabilities(self, context: PortContext) -> Mapping[str, str]:
        """Effective, object-specific readiness; must not perform content writes."""
        ...

    def build(self, context: PortContext) -> object:
        """Build the execution port, not a service which routes back to the resolver."""
        ...


class ProviderRegistry:
    def __init__(self, factories: Mapping[str, ProviderFactory]):
        self._factories = MappingProxyType(dict(factories))

    def lookup(self, key: str) -> ProviderFactory | None:
        return self._factories.get(key)
