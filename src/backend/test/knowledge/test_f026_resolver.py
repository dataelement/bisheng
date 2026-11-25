"""F026 red contract: trusted routing facts and capabilities precede port construction."""

from unittest.mock import Mock

import pytest


def resolve(provider_key, binding, operation, factories):
    # Import inside the test: pytest must collect each contract even before T004 exists.
    from bisheng.knowledge.application.provider_resolver import ProviderResolver

    return ProviderResolver(factories=factories).resolve(
        tenant_id=17, space_id=29, provider_key=provider_key, binding=binding, operation=operation
    )


def factory(operation, status="supported"):
    result = Mock()
    result.capabilities.return_value = {operation: status}
    return result


def test_explicit_native_routes_to_original_executor_without_remote_binding():
    native = factory("document.read")
    external = factory("document.read")
    port = resolve("native", None, "document.read", {"native": native, "weknora": external})
    assert port is native.build.return_value
    native.build.assert_called_once()
    external.build.assert_not_called()


def test_external_without_binding_refuses_instead_of_using_native():
    from bisheng.knowledge.application.provider_resolver import BindingUnavailable

    native = factory("document.read")
    external = factory("document.read")
    with pytest.raises(BindingUnavailable):
        resolve("weknora", None, "document.read", {"native": native, "weknora": external})
    native.build.assert_not_called()
    external.build.assert_not_called()


def sample_binding():
    # Test-only registration; resolver receives server-loaded facts, not request JSON.
    return {
        "tenant_id": 17,
        "space_id": 29,
        "provider_key": "sample",
        "instance_id": 7,
        "generation": 2,
        "remote_scope_id": "owner",
        "remote_kb_id": "kb",
        "state": "ready",
    }


def test_registered_third_provider_routes_supported_operation():
    sample = factory("document.read")
    port = resolve("sample", sample_binding(), "document.read", {"sample": sample})
    assert port is sample.build.return_value
    sample.build.assert_called_once()


def test_registered_third_provider_rejects_unsupported_wiki_before_build():
    from bisheng.knowledge.application.provider_resolver import CapabilityUnavailable

    sample = factory("wiki.graph", "unsupported")
    with pytest.raises(CapabilityUnavailable):
        resolve("sample", sample_binding(), "wiki.graph", {"sample": sample})
    sample.build.assert_not_called()


@pytest.mark.parametrize("change", [{"tenant_id": 18}, {"space_id": 30}, {"state": "provisioning"}])
def test_binding_scope_or_state_mismatch_prevents_port_creation(change):
    from bisheng.knowledge.application.provider_resolver import BindingUnavailable

    sample = factory("document.read")
    with pytest.raises(BindingUnavailable):
        resolve("sample", sample_binding() | change, "document.read", {"sample": sample})
    sample.build.assert_not_called()
