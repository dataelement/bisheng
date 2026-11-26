"""Offline deterministic host firewall contract; unrestricted runner egress."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

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
    assert ["iptables", "-A", "BSRE_FWD", "-j", "ACCEPT"] in rules
    assert ["iptables", "-A", "BSRE_IN", "-j", "ACCEPT"] in rules


def test_plan_does_not_deny_private_or_pin_dns():
    rules = plan("10.0.0.0/8")
    deny_dest = [row for row in rules if row[:4] == ["iptables", "-A", "BSRE_FWD", "-d"] and row[-1] == "DROP"]
    assert deny_dest == []
    assert not any(row[:4] == ["iptables", "-A", "BSRE_FWD", "-d"] and "223.5.5.5" in row for row in rules)
    assert ["ip6tables", "-A", "BSRE6_FWD", "-j", "ACCEPT"] in rules


def test_compose_dedicated_network_identity_without_dns_pin():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text())
    assert compose["networks"]["sandbox_net"] == {"name": "bisheng-runner", "external": True}
    for index in (1, 2):
        runner = compose["services"][f"code-runner-{index}"]
        assert runner["networks"] == {"sandbox_net": {"ipv4_address": f"172.30.166.1{index}"}}
        assert runner["restart"] == "on-failure"
        assert "NET_ADMIN" not in runner["cap_add"] and "NET_RAW" not in runner["cap_add"]
        assert "dns" not in runner
        assert "sysctls" not in runner or "disable_ipv6" not in str(runner.get("sysctls", {}))
