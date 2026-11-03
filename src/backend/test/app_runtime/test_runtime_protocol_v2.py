"""Service signatures bind authority-bearing query/body and survive restarts."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def protocol():
    from bisheng.app_runtime.domain.services import runtime_protocol

    return runtime_protocol


async def test_replay_and_scope_fail_closed(protocol):
    """AC-06, AC-53: a key cannot change roles or replay a consumed nonce."""
    seen = set()

    async def consume(key, ttl):
        if key in seen:
            return False
        seen.add(key)
        return True

    keys = {"node-a": {"secret": "test-only-signing-key", "roles": ["manager"], "node_id": "node-a"}}
    headers = protocol.signed_headers(
        "POST", "/path?a=1", b"{}", key_id="node-a", secret=keys["node-a"]["secret"], timestamp=1000, nonce="a" * 32
    )
    identity = await protocol.authenticate(
        "POST", "/path?a=1", b"{}", headers, keys, consume, required_role="manager", now=1000
    )
    assert identity.node_id == "node-a"
    for role in ["manager", "egress", "entry"]:
        with pytest.raises(protocol.ProtocolRejected):
            await protocol.authenticate(
                "POST", "/path?a=1", b"{}", headers, keys, consume, required_role=role, now=1000
            )


@pytest.mark.parametrize(
    "url,body,now",
    [
        ("/path?a=2", b"{}", 1000),
        ("/path?a=1", b"changed", 1000),
        ("/path?a=1", b"{}", 1061),
        ("/path?a=1", b"{}", 1060),
        ("/path?a=1", b"{}", 940),
    ],
)
async def test_tampering_or_expiry(protocol, url, body, now):
    """AC-53: query/body changes and signatures older than 60 seconds fail."""

    async def consume(key, ttl):
        return True

    keys = {"node": {"secret": "test-only-key", "roles": ["manager"]}}
    headers = protocol.signed_headers(
        "POST", "/path?a=1", b"{}", key_id="node", secret=keys["node"]["secret"], timestamp=1000, nonce="b" * 32
    )
    with pytest.raises(protocol.ProtocolRejected):
        await protocol.authenticate("POST", url, body, headers, keys, consume, required_role="manager", now=now)


async def test_nonce_store_outage_is_not_allow(protocol):
    """AC-49, AC-53: persistence failure must reject the sensitive operation."""

    async def broken(key, ttl):
        raise ConnectionError("fixture unavailable")

    keys = {"node": {"secret": "test-only-key", "roles": ["manager"]}}
    headers = protocol.signed_headers(
        "POST", "/p", b"", key_id="node", secret=keys["node"]["secret"], timestamp=1000, nonce="c" * 32
    )
    with pytest.raises(ConnectionError):
        await protocol.authenticate("POST", "/p", b"", headers, keys, broken, required_role="manager", now=1000)


@pytest.mark.parametrize(
    "relative", ["runtime-manager/runtime_manager/platform_protocol.py", "app-proxy/app_proxy/platform_protocol.py"]
)
def test_manager_and_backend_share_canonical_vectors(protocol, relative):
    """AC-53: independent images must sign the same bytes and repeated queries."""
    path = Path(__file__).resolve().parents[3] / relative
    spec = importlib.util.spec_from_file_location("runtime_wire_vectors", path)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args = ("GET", "/apps/a%2Fb?x=2&x=1&blank=", b"", 1000, "d" * 32, "node")
    assert protocol.canonical_message(*args) == module.canonical_message(*args)
    assert b"/apps/a/b?blank=&x=1&x=2" in protocol.canonical_message(*args)
