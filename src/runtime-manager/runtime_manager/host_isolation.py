"""Docker-host isolation installer/reconciler. Invoke on the host, never inside manager.

The reporter and manager have different HMAC identities. The reporter owns only
its INPUT/FORWARD chains/table; a failed repair stops only labeled executions on
this node's inspected networks. It never deletes app containers, volumes or data.
"""

from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from runtime_manager.platform_protocol import canonical_json, content_digest, signed_headers

INPUT = "BISHENG_APP_INPUT"
FORWARD = "BISHENG_APP_FORWARD"
TABLE = "bisheng_egress"


def validate_descriptor(descriptor):
    if not descriptor["networks"] or "@sha256:" not in descriptor["canary_image"]:
        raise ValueError("host_isolation_descriptor_invalid")
    for item in descriptor["networks"]:
        subnet = ipaddress.ip_network(item["subnet"], strict=True)
        if subnet.version != 4 or subnet.prefixlen < 8 or not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", item["bridge"]):
            raise ValueError("host_isolation_network_unsupported")
        for key in ("proxy_ip", "gateway"):
            if ipaddress.ip_address(item[key]) not in subnet:
                raise ValueError("host_isolation_address_mismatch")
    for address, port in descriptor["host_targets"]:
        if ipaddress.ip_address(address).version != 4 or not 1 <= int(port) <= 65535:
            raise ValueError("host_isolation_target_invalid")
    if not descriptor["host_targets"]:
        raise ValueError("host_isolation_targets_required")


def discover(api, config):
    info = api.info()
    if any("rootless" in str(option) for option in info.get("SecurityOptions", [])):
        raise ValueError("rootless_not_supported")
    result = {key: config[key] for key in ("node_id", "proxy_container", "canary_image", "host_targets")}
    result["engine_id"] = info["ID"]
    result["networks"] = []
    for name in config["network_names"]:
        network = api.inspect_network(name)
        if network["Driver"] != "bridge" or network.get("EnableIPv6") or not network.get("Internal"):
            raise ValueError("ipv4_internal_bridge_required")
        ipam = network.get("IPAM", {}).get("Config", [])
        if len(ipam) != 1:
            raise ValueError("network_ipam_ambiguous")
        proxy = api.inspect_container(config["proxy_container"])
        endpoint = proxy["NetworkSettings"]["Networks"].get(name)
        if not endpoint or endpoint["NetworkID"] != network["Id"]:
            raise ValueError("egress_network_mismatch")
        result["networks"].append(
            {
                "name": name,
                "id": network["Id"],
                "bridge": network.get("Options", {}).get("com.docker.network.bridge.name")
                or "br-" + network["Id"][:12],
                "subnet": ipam[0]["Subnet"],
                "gateway": ipam[0]["Gateway"],
                "proxy_ip": endpoint["IPAddress"],
            }
        )
    validate_descriptor(result)
    return result


def owned_jumps(save):
    rows = []
    for line in save.splitlines():
        words = shlex.split(line)
        if len(words) >= 4 and words[:2] in (["-A", "INPUT"], ["-A", "DOCKER-USER"]):
            if "-j" in words and words[words.index("-j") + 1] in {INPUT, FORWARD}:
                rows.append(words)
    return rows


def iptables_restore(descriptor, save, *, remove=False):
    validate_descriptor(descriptor)
    lines = ["*filter"]
    if not remove:
        lines += [f":{INPUT} - [0:0]", f":{FORWARD} - [0:0]", f"-F {INPUT}", f"-F {FORWARD}"]
    for words in owned_jumps(save):
        lines.append(shlex.join(["-D", *words[1:]]))
    if remove:
        for chain in (INPUT, FORWARD):
            if f":{chain} " in save:
                lines.extend([f"-F {chain}", f"-X {chain}"])
    else:
        for item in descriptor["networks"]:
            bridge, subnet, proxy = item["bridge"], item["subnet"], item["proxy_ip"]
            lines += [
                f"-I INPUT 1 -i {bridge} -s {subnet} -j {INPUT}",
                f"-I DOCKER-USER 1 -i {bridge} -s {subnet} -j {FORWARD}",
            ]
            for chain in (INPUT, FORWARD):
                lines += [
                    f"-A {chain} -i {bridge} -s {subnet} -m conntrack --ctdir REPLY --ctstate ESTABLISHED -j RETURN",
                    f"-A {chain} -i {bridge} -s {subnet} -d {proxy} -p tcp --dport 3128 -m conntrack --ctdir ORIGINAL -j RETURN",
                ]
        lines += [f"-A {INPUT} -j DROP", f"-A {FORWARD} -j DROP"]
    return "\n".join([*lines, "COMMIT", ""])


def nft_document(descriptor, *, exists=False, remove=False):
    validate_descriptor(descriptor)
    commands = []
    table = {"family": "inet", "name": TABLE}
    if exists:
        commands.append({"delete": {"table": table}})
    if remove:
        return {"nftables": commands}
    commands.append({"add": {"table": table}})
    for hook in ("input", "forward"):
        commands.append(
            {
                "add": {
                    "chain": {
                        "family": "inet",
                        "table": TABLE,
                        "name": hook,
                        "type": "filter",
                        "hook": hook,
                        "prio": -100,
                        "policy": "accept",
                    }
                }
            }
        )
        for item in descriptor["networks"]:

            def match(left, right):
                return {"match": {"op": "==", "left": left, "right": right}}

            base = [
                match({"meta": {"key": "iifname"}}, item["bridge"]),
                match(
                    {"payload": {"protocol": "ip", "field": "saddr"}},
                    {
                        "prefix": {
                            "addr": str(ipaddress.ip_network(item["subnet"]).network_address),
                            "len": ipaddress.ip_network(item["subnet"]).prefixlen,
                        }
                    },
                ),
            ]
            reply = [
                *base,
                match({"ct": {"key": "direction"}}, "reply"),
                match({"ct": {"key": "state"}}, "established"),
                {"accept": None},
            ]
            proxy = [
                *base,
                match({"payload": {"protocol": "ip", "field": "daddr"}}, item["proxy_ip"]),
                match({"meta": {"key": "l4proto"}}, "tcp"),
                match({"payload": {"protocol": "tcp", "field": "dport"}}, 3128),
                match({"ct": {"key": "direction"}}, "original"),
                {"accept": None},
            ]
            for expr in (reply, proxy, [*base, {"drop": None}]):
                commands.append({"add": {"rule": {"family": "inet", "table": TABLE, "chain": hook, "expr": expr}}})
    return {"nftables": commands}


def command(args, raw=None, *, check=True):
    result = subprocess.run(args, input=raw, text=True, capture_output=True, timeout=30, check=False)
    if check and result.returncode:
        raise ValueError("host_firewall_command_failed")
    return result


def normalized_iptables(line):
    words = shlex.split(line)
    result = []
    for flag, value in zip(words[::2], words[1::2], strict=True):
        if flag == "-m" and value == "tcp":
            continue
        if flag in {"-s", "-d"}:
            value = str(ipaddress.ip_network(value, strict=False))
        result.append((flag, value))
    if len(words) % 2:
        raise ValueError("iptables_readback_invalid")
    return tuple(sorted(result))


def apply_rules(descriptor, backend, *, remove=False):
    if backend == "iptables":
        saved = command(["iptables-save", "-t", "filter"]).stdout
        program = iptables_restore(descriptor, saved, remove=remove)
        command(["iptables-restore", "--test", "--noflush"], program)
        command(["iptables-restore", "--wait", "5", "--noflush"], program)
        if remove:
            return ""
        # Match each owned rule and the first per-network parent jump exactly.
        current = command(["iptables-save", "-t", "filter"]).stdout
        expected = {
            line for line in program.splitlines() if line.startswith(("-A " + INPUT + " ", "-A " + FORWARD + " "))
        }
        actual = {
            line for line in current.splitlines() if line.startswith(("-A " + INPUT + " ", "-A " + FORWARD + " "))
        }
        # iptables-save may canonicalize options. Parse token lists rather than
        # accepting substring evidence; disagreement fails closed for that host.
        if {normalized_iptables(x) for x in expected} != {normalized_iptables(x) for x in actual}:
            raise ValueError("host_firewall_readback_mismatch")
        for parent, chain in (("INPUT", INPUT), ("DOCKER-USER", FORWARD)):
            rules = [shlex.split(line) for line in current.splitlines() if line.startswith("-A " + parent + " ")]
            first = rules[: len(descriptor["networks"])]
            expected_jumps = {
                normalized_iptables(f"-A {parent} -i {item['bridge']} -s {item['subnet']} -j {chain}")
                for item in descriptor["networks"]
            }
            if {normalized_iptables(shlex.join(x)) for x in first} != expected_jumps:
                raise ValueError("host_firewall_jump_not_first")
        return content_digest(sorted(actual))
    if backend != "nftables":
        raise ValueError("host_firewall_backend_unsupported")
    exists = command(["nft", "list", "table", "inet", TABLE], check=False).returncode == 0
    program = nft_document(descriptor, exists=exists, remove=remove)
    raw = json.dumps(program)
    command(["nft", "--check", "--json", "--file", "-"], raw)
    command(["nft", "--json", "--file", "-"], raw)
    if remove:
        return ""
    current = json.loads(command(["nft", "--json", "list", "table", "inet", TABLE]).stdout)["nftables"]
    expected_rules = [x["add"]["rule"] for x in program["nftables"] if "rule" in x.get("add", {})]
    actual_rules = [
        {k: v for k, v in x["rule"].items() if k in {"family", "table", "chain", "expr"}}
        for x in current
        if "rule" in x
    ]
    chains = [x["chain"] for x in current if "chain" in x]
    if (
        actual_rules != expected_rules
        or {x.get("hook") for x in chains} != {"input", "forward"}
        or any(x.get("prio") != -100 for x in chains)
    ):
        raise ValueError("host_firewall_readback_mismatch")
    return content_digest(actual_rules)


def stop_managed(api, descriptor):
    """Confirm stop by exact container ID; never remove applications or volumes."""
    network_ids = {item["id"] for item in descriptor["networks"]}
    for candidate in api.containers(all=True, filters={"label": "bisheng.managed"}):
        ident = candidate["Id"]
        actual = api.inspect_container(ident)
        labels = actual.get("Config", {}).get("Labels") or {}
        attached = {x["NetworkID"] for x in actual.get("NetworkSettings", {}).get("Networks", {}).values()}
        if not attached & network_ids:
            continue
        if (
            labels.get("bisheng.managed") in {"v2", "probe"}
            and labels.get("bisheng.runtime.node") != descriptor["node_id"]
        ):
            continue
        if labels.get("bisheng.managed") not in {"v2", "true", "preview", "probe"}:
            continue
        if actual["State"]["Running"]:
            api.stop(ident, timeout=10)
        if api.inspect_container(ident)["State"]["Running"]:
            raise ValueError("managed_execution_stop_unconfirmed")


def reclaim_canaries(api, node_id):
    for row in api.containers(all=True, filters={"label": "bisheng.isolation.node=" + node_id}):
        ref = row["Id"]
        actual = api.inspect_container(ref)
        labels = actual.get("Config", {}).get("Labels") or {}
        nonce = labels.get("bisheng.isolation.canary", "")
        try:
            expired = 0 < int(labels.get("bisheng.isolation.expires", "0")) <= time.time()
        except ValueError:
            expired = False
        if (
            actual.get("Id") != ref
            or labels.get("bisheng.isolation.node") != node_id
            or not re.fullmatch(r"[a-f0-9]{32}", nonce)
            or not expired
        ):
            continue
        if actual["State"]["Running"]:
            api.stop(ref, timeout=5)
        stopped = api.inspect_container(ref)
        if (
            stopped.get("Id") != ref
            or (stopped.get("Config", {}).get("Labels") or {}).get("bisheng.isolation.canary") != nonce
            or stopped["State"]["Running"]
        ):
            raise ValueError("host_canary_stop_unconfirmed")
        api.remove_container(ref, force=False, v=False)


def canary(api, descriptor):
    # Negative probes require a listening host endpoint so absence of a service
    # cannot masquerade as firewall enforcement. The installer uses fixed admin
    # targets, never an application-supplied scan range.
    for address, port in descriptor["host_targets"]:
        with socket.create_connection((address, int(port)), timeout=3):
            pass
    for network in descriptor["networks"]:
        nonce = uuid4().hex
        labels = {
            "bisheng.isolation.canary": nonce,
            "bisheng.isolation.node": descriptor["node_id"],
            "bisheng.isolation.expires": str(int(time.time()) + 120),
        }
        server = 'from http.server import HTTPServer,BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n def do_GET(self):\n  self.send_response(200); self.end_headers(); self.wfile.write(b"ok")\nHTTPServer(("0.0.0.0",8080),H).serve_forever()'
        ref = api.create_container(
            image=descriptor["canary_image"],
            name="bisheng-isolation-" + nonce,
            command=["python", "-u", "-c", server],
            entrypoint=[],
            user="10001:10001",
            labels=labels,
            host_config=api.create_host_config(
                network_mode=network["name"],
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit="64m",
                pids_limit=32,
                auto_remove=False,
            ),
        )["Id"]
        try:
            api.start(ref)
            info = api.inspect_container(ref)
            address = info["NetworkSettings"]["Networks"][network["name"]]["IPAddress"]
            deadline = time.monotonic() + 20
            while True:
                try:
                    with httpx.Client(trust_env=False, timeout=2) as http:
                        if http.get(f"http://{address}:8080/").status_code == 200:
                            break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise ValueError("host_ingress_reply_failed") from None
                    time.sleep(0.2)
            targets = [*descriptor["host_targets"]]
            # Prove the same listening service is denied via the bridge gateway
            # as well as the admin-published host address.
            for _, port in descriptor["host_targets"]:
                with socket.create_connection((network["gateway"], int(port)), timeout=3):
                    pass
                targets.append([network["gateway"], int(port)])
            script = """import json,socket
results=[]
for host,port in json.loads(__import__('sys').argv[1]):
 try:
  with socket.create_connection((host,port),timeout=2): pass
  results.append(True)
 except OSError: results.append(False)
print(json.dumps(results))
"""
            endpoints = [[network["proxy_ip"], 3128], *targets]
            exec_id = api.exec_create(ref, ["python", "-c", script, json.dumps(endpoints)])["Id"]
            result = api.exec_start(exec_id)
            if api.exec_inspect(exec_id)["ExitCode"] != 0 or json.loads(result) != [True] + [False] * len(targets):
                raise ValueError("host_canary_allow_deny_failed")
        finally:
            info = api.inspect_container(ref)
            if info["Id"] != ref or any(
                (info.get("Config", {}).get("Labels") or {}).get(key) != value for key, value in labels.items()
            ):
                raise ValueError("host_canary_identity_changed")
            if info["State"]["Running"]:
                api.stop(ref, timeout=5)
            if api.inspect_container(ref)["State"]["Running"]:
                raise ValueError("host_canary_stop_unconfirmed")
            api.remove_container(ref, force=False, v=False)
    return dict.fromkeys(
        (
            "ipv4_bridge",
            "rules_read_back",
            "egress_allowed",
            "host_gateway_denied",
            "host_published_denied",
            "ingress_reply_allowed",
        ),
        True,
    )


def manager_proof(api, config, network):
    """Unprivileged manager verifies backend proof against this actual Engine."""
    from runtime_manager.platform_client import PlatformClient, PlatformError

    with_client = PlatformClient(config, timeout=3)
    try:
        proof = with_client.request("GET", "/api/v1/internal/app-runtime/v2/host-isolation")
    finally:
        with_client.close()
    descriptor = proof["descriptor"]
    names = [item["name"] for item in descriptor["networks"]]
    if network and network not in names:
        raise PlatformError("host_network_unprotected")
    discovered = discover(api, {**descriptor, "network_names": names})
    if content_digest(discovered) != proof["config_digest"] or discovered["engine_id"] != proof["engine_id"]:
        raise PlatformError("host_isolation_descriptor_changed")


def publish_report(config, descriptor, *, status, checks, rule_digest):
    body = {
        "engine_id": descriptor["engine_id"],
        "network_id": descriptor["networks"][0]["id"],
        "config_digest": content_digest(descriptor),
        "rule_digest": rule_digest,
        "revision": time.time_ns(),
        "checked_at": datetime.now(UTC).isoformat(),
        "status": status,
        "checks": checks,
    }
    raw = canonical_json(body)
    path = "/api/v1/internal/app-runtime/host-isolation-reports"
    headers = signed_headers(
        "POST", path, raw, key_id=os.environ["HOST_ISOLATION_KEY_ID"], secret=os.environ["HOST_ISOLATION_SECRET"]
    )
    headers["Content-Type"] = "application/json"
    with httpx.Client(
        base_url=config["platform_base_url"], trust_env=False, timeout=15, follow_redirects=False
    ) as client:
        response = client.post(path, content=raw, headers=headers)
        if response.status_code != 200:
            raise ValueError("host_isolation_report_refused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.settings).read_text())
    import docker

    api = docker.APIClient(base_url=os.environ.get("RTM_DOCKER_HOST") or None)
    if args.describe:
        descriptor = discover(api, config)
    else:
        descriptor = None
    if args.describe:
        print(
            json.dumps(
                {
                    "engine_id": descriptor["engine_id"],
                    "network_id": descriptor["networks"][0]["id"],
                    "config_digest": content_digest(descriptor),
                    "descriptor": descriptor,
                },
                sort_keys=True,
                indent=2,
            )
        )
        return
    if os.geteuid() != 0 or Path("/.dockerenv").exists():
        raise ValueError("run_on_docker_host_as_root")
    with open("/run/lock/bisheng-host-isolation.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            descriptor = discover(api, config)
        except Exception:
            for candidate in api.containers(all=True, filters={"label": "bisheng.managed"}):
                actual = api.inspect_container(candidate["Id"])
                labels = actual.get("Config", {}).get("Labels") or {}
                attached = actual.get("NetworkSettings", {}).get("Networks", {})
                owned = labels.get("bisheng.runtime.node") == config["node_id"] or (
                    labels.get("bisheng.managed") in {"true", "preview"}
                    and bool(set(attached) & set(config["network_names"]))
                )
                if owned and actual["State"]["Running"]:
                    api.stop(actual["Id"], timeout=10)
                    if api.inspect_container(actual["Id"])["State"]["Running"]:
                        raise ValueError("managed_execution_stop_unconfirmed")
            raise
        if args.remove:
            # Invalidate backend admission before removing the enforcement. A
            # failed API call leaves the rules installed, even after timer stop.
            publish_report(config, descriptor, status="failed", checks={}, rule_digest="0" * 64)
            stop_managed(api, descriptor)
            apply_rules(descriptor, config["firewall_backend"], remove=True)
            return
        checks = {}
        status = "failed"
        rule_digest = "0" * 64
        try:
            rule_digest = apply_rules(descriptor, config["firewall_backend"])
            reclaim_canaries(api, descriptor["node_id"])
            checks = canary(api, descriptor)
            status = "valid"
        except Exception:
            # Preserve failure as the primary diagnostic; a stop uncertainty
            # must remain failed and must not authorize storage cleanup.
            stop_managed(api, descriptor)
            raise
        finally:
            publish_report(config, descriptor, status=status, checks=checks, rule_digest=rule_digest)


if __name__ == "__main__":
    main()
