"""Explicit APP-only read factories; unconfigured processes refuse admission."""

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.source_read import ReferenceSourceReadRuntime

_runtime: ReferenceSourceReadRuntime | None = None
_user_factory = None


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
