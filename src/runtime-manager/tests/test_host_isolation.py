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


@pytest.mark.parametrize("mutation", [None, "earlier_accept", "foreign_subnet"])
def test_parent_jump_readback_accepts_canonical_order_but_preserves_fences(monkeypatch, descriptor, mutation):
    """Real iptables-save reorders -s before -i; the first-rule and exact-subnet checks still apply."""
    from copy import deepcopy
    from types import SimpleNamespace

    from runtime_manager import host_isolation

    second = deepcopy(descriptor["networks"][0])
    second.update(
        name="build",
        id="def456",
        bridge="br-def456",
        subnet="172.31.0.0/24",
        gateway="172.31.0.1",
        proxy_ip="172.31.0.2",
    )
    descriptor["networks"].append(second)
    saved = "*filter\n:INPUT ACCEPT [0:0]\n:DOCKER-USER - [0:0]\nCOMMIT\n"
    program = iptables_restore(descriptor, saved)
    current = []
    for item in reversed(descriptor["networks"]):
        for parent, chain in (("INPUT", host_isolation.INPUT), ("DOCKER-USER", host_isolation.FORWARD)):
            current.append(f"-A {parent} -s {item['subnet']} -i {item['bridge']} -j {chain}")
    current.extend(line for line in program.splitlines() if line.startswith("-A "))
    if mutation == "earlier_accept":
        current.insert(0, "-A INPUT -j ACCEPT")
    elif mutation == "foreign_subnet":
        current[0] = current[0].replace("172.31.0.0/24", "172.99.0.0/24")
    reads = iter([saved, "\n".join(current)])

    def command(args, raw=None, *, check=True):
        return SimpleNamespace(stdout=next(reads) if args[0] == "iptables-save" else "", returncode=0)

    monkeypatch.setattr(host_isolation, "command", command)
    if mutation is None:
        assert host_isolation.apply_rules(descriptor, "iptables")
    else:
        with pytest.raises(ValueError, match="host_firewall_jump_not_first"):
            host_isolation.apply_rules(descriptor, "iptables")


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


def add_ingress(descriptor):
    descriptor["ingress_containers"] = ["manager", "entry"]
    descriptor["networks"][0]["ingress"] = [
        {"container": "manager", "ip": "172.30.0.3"},
        {"container": "entry", "ip": "172.30.0.4"},
    ]
    return descriptor


def test_trusted_control_ingress_is_exact_forward_tcp_only(descriptor):
    add_ingress(descriptor)
    text = iptables_restore(descriptor, "")
    for peer in descriptor["networks"][0]["ingress"]:
        expected = (
            f"-A BISHENG_APP_FORWARD -i br-abc123 -s {peer['ip']} -d 172.30.0.0/24 "
            "-p tcp -m conntrack --ctdir ORIGINAL -j RETURN"
        )
        assert expected in text
        assert text.index(expected) < text.index("-A BISHENG_APP_FORWARD -j DROP")
        assert not any(peer["ip"] in line for line in text.splitlines() if line.startswith("-A BISHENG_APP_INPUT"))
    assert "-s 172.30.0.0/24 -d 172.30.0.0/24" not in text
    assert "--dport 3128" in text


def test_nft_trusted_ingress_never_opens_host_input(descriptor):
    import json

    add_ingress(descriptor)
    rules = [x["add"]["rule"] for x in nft_document(descriptor)["nftables"] if "rule" in x.get("add", {})]
    for peer in descriptor["networks"][0]["ingress"]:
        matched = [rule for rule in rules if peer["ip"] in json.dumps(rule)]
        assert len(matched) == 1 and matched[0]["chain"] == "forward"
        encoded = json.dumps(matched[0])
        assert "daddr" in encoded and "tcp" in encoded and "original" in encoded
    assert rules[-1]["expr"][-1] == {"drop": None}


@pytest.mark.parametrize("change", ["outside", "gateway", "proxy", "duplicate", "foreign", "invalid_type", "missing"])
def test_trusted_ingress_refuses_ambiguous_identity_or_address(descriptor, change):
    add_ingress(descriptor)
    peer = descriptor["networks"][0]["ingress"][0]
    if change == "outside":
        peer["ip"] = "192.0.2.1"
    elif change == "gateway":
        peer["ip"] = "172.30.0.1"
    elif change == "proxy":
        peer["ip"] = "172.30.0.2"
    elif change == "duplicate":
        descriptor["networks"][0]["ingress"][1]["ip"] = peer["ip"]
    elif change == "foreign":
        peer["container"] = "application"
    elif change == "invalid_type":
        peer["ip"] = None
    else:
        descriptor["networks"][0]["ingress"].pop()
    with pytest.raises(ValueError):
        validate_descriptor(descriptor)


@pytest.mark.parametrize("change", [None, "application", "stopped", "network_changed", "recreated", "ip_changed"])
def test_discovery_pins_actual_trusted_container_identity(descriptor, change):
    from copy import deepcopy

    from runtime_manager.host_isolation import discover

    descriptor = add_ingress(descriptor)
    network = descriptor["networks"][0]

    class API:
        def info(self):
            return {"ID": "engine-a", "SecurityOptions": []}

        def inspect_network(self, name):
            return {
                "Id": network["id"],
                "Driver": "bridge",
                "Internal": True,
                "EnableIPv6": False,
                "IPAM": {"Config": [{"Subnet": network["subnet"], "Gateway": network["gateway"]}]},
                "Options": {"com.docker.network.bridge.name": network["bridge"]},
            }

        def inspect_container(self, name):
            peer = next((x for x in network["ingress"] if x["container"] == name), None)
            doc = {
                "Id": ("b" if name == "manager" else "c") * 64,
                "State": {"Running": True},
                "Config": {"Labels": {}},
                "NetworkSettings": {
                    "Networks": {
                        "bisheng-apps": {
                            "NetworkID": network["id"],
                            "IPAddress": peer["ip"] if peer else network["proxy_ip"],
                        }
                    }
                },
            }
            if name == "manager":
                if change == "application":
                    doc["Config"]["Labels"] = {"bisheng.managed": "v2"}
                elif change == "stopped":
                    doc["State"]["Running"] = False
                elif change == "network_changed":
                    doc["NetworkSettings"]["Networks"]["bisheng-apps"]["NetworkID"] = "replacement"
                elif change == "recreated":
                    doc["Id"] = "e" * 64
                elif change == "ip_changed":
                    doc["NetworkSettings"]["Networks"]["bisheng-apps"]["IPAddress"] = "172.30.0.5"
            return doc

    config = {**deepcopy(descriptor), "network_names": ["bisheng-apps"]}
    if change in {"application", "stopped", "network_changed"}:
        with pytest.raises(ValueError):
            discover(API(), config)
    else:
        actual = discover(API(), config)
        if change in {None, "recreated"}:
            assert actual == descriptor
        else:
            assert actual != descriptor
