"""Capability-environment seam — the second place F054 lets F055 in (F055 T056).

``lifecycle_hooks`` exists because deletion has a consequence only F055 knows
how to carry out. This module exists for the mirror case on the way up: the
environment a hosted container starts with includes the application's runtime
credential and the model face's address, and **minting a credential is F055's
job**, not the state machine's. Dependency direction stays F055 → F054.

Two properties, both deliberate:

* **Unregistered means no capability environment, not a failure.** A process
  that never ran F055's composition root (or a deployment without the capability
  bus) starts applications with F054's own variables and nothing else — the
  application then has no ``BISHENG_APP_TOKEN``, which is the honest state of
  affairs rather than a start that fails for a reason nobody can read.
* **A provider that raises stops the start.** Once a provider *is* registered,
  its failure means "this container would run without the credential it was
  promised" — serving that would give the application's users a broken feature
  with no error anywhere. The caller lets the exception through to its normal
  parking path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

#: ``(app_id, capabilities) -> Awaitable[dict[str, str]]``
CapabilityEnvProvider = Callable[..., Awaitable[dict]]

_provider: CapabilityEnvProvider | None = None


def register_capability_env_provider(provider: CapabilityEnvProvider) -> None:
    """Install the provider. Idempotent by identity, like the deletion hooks."""
    global _provider
    _provider = provider


def clear_capability_env_provider() -> None:
    """Drop the provider — composition-root reset and test isolation only."""
    global _provider
    _provider = None


async def capability_env(*, app_id: str, capabilities) -> dict[str, str]:
    """The capability environment for one start, or ``{}`` when nobody provides one."""
    if _provider is None:
        return {}
    return dict(await _provider(app_id=app_id, capabilities=capabilities) or {})


__all__ = [
    "CapabilityEnvProvider",
    "capability_env",
    "clear_capability_env_provider",
    "register_capability_env_provider",
]
