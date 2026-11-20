"""Offline deterministic host firewall contract; not packet-path validation."""

from __future__ import annotations

import ipaddress
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "docker/lib/runner-egress.sh"


def plan(internal="none"):
    result = subprocess.run(
        ["bash", str(HELPER), "plan"],
        capture_output=True,
        text=True,
        env={**os.environ, "RUNNER_INTERNAL_CIDRS": internal},
        check=True,
    )
    return [shlex.split(line) for line in result.stdout.splitlines()]


def test_plan_never_flushes_or_changes_other_default_policy():
    rules = plan()
    assert all(row[1] in {"-N", "-A", "-I"} for row in rules)
    for row in rules:
        if row[1] == "-I":
            assert row[4:6] == ["-i", "br-bsrunner"]
    assert [
        "iptables",
        "-A",
        "BSRE_FWD",
        "-m",
        "conntrack",
        "--ctstate",
        "ESTABLISHED",
        "--ctdir",
        "REPLY",
        "-j",
        "ACCEPT",
    ] in rules
    assert ["iptables", "-A", "BSRE_FWD", "-m", "addrtype", "--dst-type", "LOCAL", "-j", "DROP"] in rules


@pytest.mark.parametrize(
    "address",
    [
        "0.1.2.3",
        "10.1.2.3",
        "100.100.100.200",
        "127.0.0.1",
        "169.254.169.254",
        "172.16.1.2",
        "172.31.255.255",
        "192.168.1.1",
        "192.0.0.1",
        "192.0.2.1",
        "192.88.99.1",
        "198.19.0.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.1.2.3",
        "255.255.255.255",
    ],
)
def test_nonpublic_blocked_before_any_public_allow(address):
    rules = plan()
    blocks = [
        (index, ipaddress.ip_network(row[4]))
        for index, row in enumerate(rules)
        if row[:4] == ["iptables", "-A", "BSRE_FWD", "-d"] and row[-1] == "DROP"
    ]
    first_public = next(i for i, row in enumerate(rules) if row[-1] == "ACCEPT" and "-p" in row)
    assert any(ipaddress.ip_address(address) in net and index < first_public for index, net in blocks)


@pytest.mark.parametrize("address", ["223.5.5.5", "8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_public_controls_not_in_nonpublic_deny(address):
    blocks = [
        ipaddress.ip_network(row[4])
        for row in plan()
        if row[:4] == ["iptables", "-A", "BSRE_FWD", "-d"] and row[-1] == "DROP"
    ]
    assert not any(ipaddress.ip_address(address) in network for network in blocks)


def test_dns_and_ipv6_policy():
    rules = plan("106.12.0.0/16")
    assert ["iptables", "-A", "BSRE_FWD", "-d", "106.12.0.0/16", "-j", "DROP"] in rules
    for proto in ("tcp", "udp"):
        allow = ["iptables", "-A", "BSRE_FWD", "-d", "223.5.5.5", "-p", proto, "--dport", "53", "-j", "ACCEPT"]
        deny = ["iptables", "-A", "BSRE_FWD", "-p", proto, "--dport", "53", "-j", "DROP"]
        public = ["iptables", "-A", "BSRE_FWD", "-p", proto, "-j", "ACCEPT"]
        assert rules.index(allow) < rules.index(deny) < rules.index(public)
    assert ["ip6tables", "-A", "BSRE6_DROP", "-j", "DROP"] in rules
    for chain in ("INPUT", "FORWARD"):
        assert ["ip6tables", "-I", chain, "1", "-i", "br-bsrunner", "-j", "BSRE6_DROP"] in rules


def test_compose_dedicated_network_identity_and_namespace():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    assert compose["networks"]["sandbox_net"] == {"name": "bisheng-runner", "external": True}
    for index in (1, 2):
        runner = compose["services"][f"code-runner-{index}"]
        assert runner["networks"] == {"sandbox_net": {"ipv4_address": f"172.30.166.1{index}"}}
        assert runner["restart"] == "no"
        assert "NET_ADMIN" not in runner["cap_add"] and "NET_RAW" not in runner["cap_add"]
        assert runner["sysctls"]["net.ipv6.conf.all.disable_ipv6"] == "1"
        assert runner["sysctls"]["net.ipv6.conf.default.disable_ipv6"] == "1"
        assert runner["dns"] == ["223.5.5.5"]
