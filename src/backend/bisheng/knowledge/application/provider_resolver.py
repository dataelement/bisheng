"""Route server-loaded space facts to a registered execution port.

This component neither authenticates a request nor loads facts from a client.
The application must authorize the operation and supply the active binding.
"""

from collections.abc import Mapping

from bisheng.knowledge.infrastructure.providers.registry import PortContext, ProviderFactory, ProviderRegistry


class BindingUnavailable(ValueError):
    """Missing, stale or mismatched trusted routing facts."""


class CapabilityUnavailable(ValueError):
    """The operation has no positive capability proof for this target."""


def _positive(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise BindingUnavailable("invalid provider routing identity")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BindingUnavailable("missing provider routing identity")
    return value  # Provider IDs are opaque: preserve exact bytes on the wire.


class ProviderResolver:
    def __init__(self, factories: Mapping[str, ProviderFactory] | ProviderRegistry):
        self._registry = factories if isinstance(factories, ProviderRegistry) else ProviderRegistry(factories)

    def resolve(
        self, *, tenant_id: int, space_id: int, provider_key: str, binding: Mapping[str, object] | None, operation: str
    ) -> object:
        _positive(tenant_id)
        _positive(space_id)
        factory = self._registry.lookup(_identifier(provider_key))
        if factory is None:
            raise BindingUnavailable("unregistered provider")
        if binding is not None and (
            _positive(binding.get("tenant_id")) != tenant_id
            or _positive(binding.get("space_id")) != space_id
            or binding.get("provider_key") != provider_key
            or binding.get("state") != "ready"
        ):
            raise BindingUnavailable("provider binding unavailable")

        if provider_key == "native":
            if binding is not None and any(
                binding.get(k) is not None for k in ("generation", "instance_id", "remote_kb_id", "remote_scope_id")
            ):
                raise BindingUnavailable("native route cannot carry an external target")
            context = PortContext(tenant_id, space_id, provider_key, operation)
        else:
            if binding is None:
                raise BindingUnavailable("external route requires a binding")
            context = PortContext(
                tenant_id,
                space_id,
                provider_key,
                operation,
                _positive(binding.get("instance_id")),
                _positive(binding.get("generation")),
                _identifier(binding.get("remote_scope_id")),
                _identifier(binding.get("remote_kb_id")),
            )
        if factory.capabilities(context).get(operation) != "supported":
            raise CapabilityUnavailable("operation not supported for this target")
        return factory.build(context)
