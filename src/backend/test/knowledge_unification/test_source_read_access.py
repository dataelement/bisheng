"""T348: missing production read wiring must never grant or guess access."""

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.source_access import (
    configure_reference_read_runtime,
    get_reference_read_runtime,
)


async def test_unconfigured_source_reader_fails_closed(monkeypatch):
    monkeypatch.setattr("bisheng.resource_reference.application.source_access._runtime", None)
    with pytest.raises(ReferenceCoverageNotReadyError) as failure:
        await get_reference_read_runtime()
    assert failure.value.Code == 10994


def test_arbitrary_objects_cannot_install_a_reader():
    with pytest.raises(TypeError):
        configure_reference_read_runtime(object())
