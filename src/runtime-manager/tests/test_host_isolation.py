"""Owned host rules only; no local firewall mutations. 覆盖 AC: AC-66, AC-67, AC-68, AC-69."""

import pytest

from runtime_manager.host_isolation import iptables_restore, nft_document, validate_descriptor


@pytest.fixture
def descriptor():
    return {
        "node_id": "node-a",
        "engine_id": "engine-a",
        "proxy_container": "egress",
        "canary_image": "image@sha256:" + "a" * 64,
        "host_targets": [["192.0.2.5", 7860]],
        "networks": [
            {
                "name": "bisheng-apps",
                "id": "abc123",
                "bridge": "br-abc123",
                "subnet": "172.30.0.0/24",
                "gateway": "172.30.0.1",
                "proxy_ip": "172.30.0.2",
            }
        ],
    }


def test_input_and_forward_only_reply_or_fixed_original_proxy(descriptor):
    text = iptables_restore(descriptor, "*filter\n:INPUT ACCEPT [0:0]\n-A INPUT -p tcp --dport 22 -j ACCEPT\nCOMMIT\n")
    assert "-I INPUT 1 -i br-abc123 -s 172.30.0.0/24 -j BISHENG_APP_INPUT" in text
    assert "-I DOCKER-USER 1" in text
    assert "--ctdir REPLY --ctstate ESTABLISHED" in text
    assert "--ctdir ORIGINAL" in text and "-d 172.30.0.2" in text and "--dport 3128" in text
    assert "RELATED" not in text
    assert "-F INPUT" not in text and "--dport 22" not in text
    assert "-A BISHENG_APP_INPUT -j DROP" in text


def test_reapply_removes_only_exact_owned_jumps(descriptor):
    prior = "-A INPUT -i oldbr -s 172.31.0.0/24 -j BISHENG_APP_INPUT\n-A INPUT -j OTHER\n"
    text = iptables_restore(descriptor, prior)
    assert "-D INPUT -i oldbr -s 172.31.0.0/24 -j BISHENG_APP_INPUT" in text
    assert "-D INPUT -j OTHER" not in text


def test_nft_owns_input_and_forward_table_only(descriptor):
    document = nft_document(descriptor, exists=True)
    assert document["nftables"][0] == {"delete": {"table": {"family": "inet", "name": "bisheng_egress"}}}
    chains = [entry["add"]["chain"] for entry in document["nftables"] if "chain" in entry.get("add", {})]
    assert {chain["hook"] for chain in chains} == {"input", "forward"}
    assert all(chain["prio"] == -100 for chain in chains)


@pytest.mark.parametrize("value", ["2001:db8::/64", "0.0.0.0/0", "172.30.0.1/24"])
def test_unprotected_or_ambiguous_network_refused(descriptor, value):
    descriptor["networks"][0]["subnet"] = value
    with pytest.raises(ValueError):
        validate_descriptor(descriptor)


def test_real_engine_adapter_gates_creation_but_preserves_stop(monkeypatch):
    from types import SimpleNamespace

    from runtime_manager import host_isolation
    from runtime_manager.docker_backend import _RealDockerBackend

    calls = []
    api = SimpleNamespace(
        create_container_from_config=lambda payload, name: calls.append("create"),
        stop=lambda ref, timeout: calls.append(("stop", ref)),
    )
    backend = _RealDockerBackend()
    backend._api = api

    def denied(*args):
        raise ValueError("proof expired")

    monkeypatch.setattr(host_isolation, "manager_proof", denied)
    with pytest.raises(ValueError, match="proof expired"):
        backend.create_container("new", {"HostConfig": {"NetworkMode": "bisheng-apps"}})
    backend.stop_container("existing")
    assert calls == [("stop", "existing")]


def test_manager_rechecks_actual_engine_descriptor(monkeypatch, descriptor):
    from types import SimpleNamespace

    from runtime_manager import platform_client
    from runtime_manager.host_isolation import manager_proof
    from runtime_manager.platform_protocol import content_digest

    engine = {"id": "engine-a"}

    class API:
        def info(self):
            return {"ID": engine["id"], "SecurityOptions": []}

        def inspect_network(self, name):
            return {
                "Id": "abc123",
                "Driver": "bridge",
                "Internal": True,
                "EnableIPv6": False,
                "IPAM": {"Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}]},
                "Options": {"com.docker.network.bridge.name": "br-abc123"},
            }

        def inspect_container(self, ref):
            return {
                "NetworkSettings": {"Networks": {"bisheng-apps": {"NetworkID": "abc123", "IPAddress": "172.30.0.2"}}}
            }

    class Client:
        def __init__(self, config, **kwargs):
            assert kwargs["timeout"] == 3
            pass

        def request(self, *args):
            return {"descriptor": descriptor, "config_digest": content_digest(descriptor), "engine_id": "engine-a"}

        def close(self):
            pass

    monkeypatch.setattr(platform_client, "PlatformClient", Client)
    manager_proof(API(), SimpleNamespace(), "bisheng-apps")
    engine["id"] = "replacement"
    with pytest.raises(platform_client.PlatformError, match="descriptor_changed"):
        manager_proof(API(), SimpleNamespace(), "bisheng-apps")
