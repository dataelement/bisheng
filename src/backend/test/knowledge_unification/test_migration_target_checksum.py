"""Knowledge inventory consumes the permission SSOT through its application."""

import importlib
import inspect
from unittest.mock import Mock

from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)


def test_target_checksum_is_the_actual_repository_template_without_runtime_io(monkeypatch):
    module = importlib.import_module("bisheng.permission.application.migration_read")
    client = Mock(side_effect=AssertionError("pure target checksum must not construct a transport"))
    discovery = Mock(side_effect=AssertionError("pure target checksum must not discover or publish a model"))
    monkeypatch.setattr(module, "FGAClient", client)
    monkeypatch.setattr(module, "discover_openfga_runtime", discovery)
    getter = module.target_authorization_model_checksum
    assert inspect.signature(getter).parameters == {}
    expected = authorization_model_checksum(build_authorization_model_f048())
    assert getter() == expected and getter() == expected
    client.assert_not_called()
    discovery.assert_not_called()
