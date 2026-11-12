"""T537: native business writers borrow the same explicitly registered runtime.

覆盖 AC: AC-87, AC-88, AC-89
"""

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application import access
from test.knowledge_unification.test_binding_write_runtime import runtime


def test_native_access_never_bootstraps_unconfigured_runtime(monkeypatch):
    monkeypatch.setattr(access, "_runtime", None)
    with pytest.raises(ReferenceCoverageNotReadyError):
        access.get_reference_binding_runtime_sync()


async def test_native_and_async_access_borrow_the_same_registered_object(monkeypatch):
    configured, _owner = runtime()
    monkeypatch.setattr(access, "_runtime", configured)
    assert access.get_reference_binding_runtime_sync() is await access.get_reference_binding_runtime() is configured
