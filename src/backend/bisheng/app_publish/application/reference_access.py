"""Explicit APP-only read factories; unconfigured processes refuse admission."""

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

_runtime: ReferenceSourceReadRuntime | None = None
_user_factory = None


class HostedAppReferenceReadRuntime(ReferenceSourceReadRuntime):
    """APP-only authority keeps final model checks bound to whole-source admission."""

    def __init__(self, source_owner, verifier, repository, target_owners):
        super().__init__(verifier, repository, target_owners)
        self._source_owner = source_owner
        self._admission_authority = object()
        source_owner._install_admission_authority(self._admission_authority)

    @property
    def source_owner(self):
        return self._source_owner

    async def arequire_source_valid(self, session, scope, identity):
        result = await super().arequire_source_valid(session, scope, identity)
        self.source_owner._mark_admitted(self._admission_authority, session, result.snapshot, identity)
        return result


def configure_hosted_app_reference_runtimes(runtime, user_factory):
    global _runtime, _user_factory
    if not isinstance(runtime, ReferenceSourceReadRuntime) or not callable(user_factory):
        raise TypeError("APP reference reads require their actual runtime and user authority factory")
    _runtime, _user_factory = runtime, user_factory


async def get_hosted_app_reference_runtime():
    if _runtime is None:
        raise ReferenceCoverageNotReadyError(reason="app_reference_runtime_unconfigured")
    return _runtime


async def get_hosted_app_user_reference_runtime(authorization_context=None):
    if _user_factory is None:
        raise ReferenceCoverageNotReadyError(reason="app_user_reference_runtime_unconfigured")
    runtime = _user_factory(authorization_context)
    if not isinstance(runtime, ReferenceSourceReadRuntime):
        raise TypeError("APP user reference reads require an actual independently assembled runtime")
    return runtime
