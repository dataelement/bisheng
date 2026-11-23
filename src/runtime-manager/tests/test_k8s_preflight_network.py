"""Network denial needs a live, policy-authorized control before and after it."""

import copy
import json
from contextlib import nullcontext
from uuid import uuid4

import pytest

from runtime_manager import k8s_capabilities
from tests.test_k8s_installation import RegistryUpstreamApi, load_installer, render
from tests.test_k8s_installation import values as values


class PolicyControlApi(RegistryUpstreamApi):
    def __init__(self, tool, *, fail_at=0, result_shape="normal", replace_after_logs=False, publish_unready=False):
        super().__init__(tool, publish_unready=publish_unready)
        self.count = 0
        self.fail_at, self.result_shape, self.replace_after_logs = fail_at, result_shape, replace_after_logs
        self.control_pods = []
        self.logs_read = False

    def get(self, kind, name, **kwargs):
        if kind == "service":
            assert name == "runtime-manager" and kwargs["namespace"] == self.control
            return {"spec": {"publishNotReadyAddresses": self.publish_unready}}
        current = super().get(kind, name, **kwargs)
        if kind == "pod" and self.logs_read and self.replace_after_logs:
            current["metadata"]["uid"] = str(uuid4())
        return current

    def call(self, args, *, document=None):
        if args[0] == "create":
            self.count += 1
            self.logs_read = False
            self.tcp_ok = self.count != self.fail_at
            self.control_pods.append(copy.deepcopy(document))
        response = super().call(args, document=document)
        if args[0] == "logs":
            self.logs_read = True
            if self.result_shape != "normal":
                response.stdout = self.tool._RESULT + json.dumps(
                    {"checks": [] if self.result_shape == "empty" else [{"name": "wrong", "ok": True}]}
                )
        return response


def network_verifier(tool, monkeypatch, **api_options):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.api = PolicyControlApi(tool, **api_options)
    verifier.namespace, verifier.timeout = verifier.api.execution, 5
    verifier.options = {"installation_id": "test-runtime"}
    verifier.document = {
        "platform": "linux/amd64",
        "status_policy_revision": "v1",
        "helper_image": "example/helper@sha256:" + "a" * 64,
    }
    verifier.created, verifier.control_created = [], []

    def wait(callback):
        result = callback()
        if not result:
            raise tool.ProbeError("probe_deadline_exceeded")
        return result

    verifier._wait = wait
    rows = [
        {"name": name, "host": host, "port": port, "expected": "denied"}
        for name, host, port in (
            ("backend", "192.0.2.1", 7860),
            ("minio", "192.0.2.2", 9000),
            ("kubernetes-api", "192.0.2.3", 6443),
            ("other-app", "@preflight", 8080),
        )
    ]
    verifier.options["network_targets"] = {"network-direct-denied": rows}
    listener = {"metadata": {"uid": str(uuid4())}, "status": {"podIP": "192.0.2.44"}}
    verifier._listener = lambda: listener
    negatives, connections = [], []

    def negative(action, *, targets):
        assert action == "network"
        assert all(row.get("control_confirmed") is True for row in targets)
        assert verifier.api.count == 1
        assert next(row for row in targets if row["name"] == "other-app")["host"] == listener["status"]["podIP"]
        pod = {"metadata": {"uid": str(uuid4())}}
        negatives.append((pod, copy.deepcopy(targets)))
        return pod

    verifier._pod = negative
    verifier._result = lambda _: {"checks": [{"name": row["name"], "ok": True} for row in rows]}

    def connect(address, **kwargs):
        connections.append((address, kwargs))
        assert address != (listener["status"]["podIP"], 8080), "Installer identity cannot substitute for manager"
        return nullcontext()

    monkeypatch.setattr(tool.socket, "create_connection", connect)
    return verifier, negatives, connections


def test_other_app_uses_real_control_identity_before_and_after_negative_probe(values, tmp_path, monkeypatch):
    tool = load_installer()
    verifier, negatives, connections = network_verifier(tool, monkeypatch)
    result = verifier._network("network-direct-denied")
    assert result["ok"] and result["evidence"]["uid"] == negatives[0][0]["metadata"]["uid"]
    assert len(negatives) == 1 and len(connections) == 6
    assert verifier.options["network_targets"]["network-direct-denied"][-1]["host"] == "@preflight"
    assert verifier.api.count == 2 and len(verifier.control_created) == 2
    for pod in verifier.api.control_pods:
        assert pod["metadata"]["namespace"] == verifier.api.control
        assert pod["metadata"]["labels"]["app"] == "runtime-manager"
        assert pod["spec"]["readinessGates"] == [{"conditionType": "runtime.bisheng.io/preflight-not-serving"}]
        assert not pod["spec"]["automountServiceAccountToken"]
        assert not any("secret" in row or "projected" in row for row in pod["spec"]["volumes"])
        plan = json.loads(pod["spec"]["containers"][0]["env"][0]["value"])
        assert plan == {"targets": [{"name": "other-app", "host": "192.0.2.44", "port": 8080, "expected": "allowed"}]}
    values["services"]["namespace"] = verifier.api.control
    values["execution"]["namespace"] = verifier.api.execution
    documents = render(values, tmp_path)
    entry = next(
        row for row in documents if row["kind"] == "NetworkPolicy" and row["metadata"]["name"] == "runtime-entry"
    )
    manager_rule = next(
        row
        for row in entry["spec"]["ingress"]
        if row["from"][0]["podSelector"]["matchLabels"] == {"app": "runtime-manager"}
    )
    assert manager_rule["from"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": verifier.api.control
    }


@pytest.mark.parametrize("fail_at", [1, 2])
def test_control_failure_cannot_become_a_successful_denial(monkeypatch, fail_at):
    tool = load_installer()
    verifier, negatives, _ = network_verifier(tool, monkeypatch, fail_at=fail_at)
    with pytest.raises(tool.ProbeError, match="control_probe_failed"):
        verifier._network("network-direct-denied")
    assert len(negatives) == (0 if fail_at == 1 else 1)
    assert verifier.control_created


@pytest.mark.parametrize("shape", ["empty", "wrong-name"])
def test_empty_or_unrelated_control_result_never_confirms_target(monkeypatch, shape):
    tool = load_installer()
    verifier, negatives, _ = network_verifier(tool, monkeypatch, result_shape=shape)
    with pytest.raises(tool.ProbeError, match="control_probe_failed"):
        verifier._network("network-direct-denied")
    assert not negatives


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"replace_after_logs": True}, "control_probe_identity_changed"),
        ({"publish_unready": True}, "control_probe_service_not_isolated"),
    ],
)
def test_control_pod_identity_and_service_isolation_remain_required(monkeypatch, options, reason):
    tool = load_installer()
    verifier, negatives, _ = network_verifier(tool, monkeypatch, **options)
    with pytest.raises(tool.ProbeError, match=reason):
        verifier._network("network-direct-denied")
    assert not negatives


DNS = {"name": "cluster-dns", "host": "192.0.2.53", "port": 53, "expected": "denied", "protocol": "udp-dns"}


@pytest.mark.parametrize("attempts", [1, 2, 3])
def test_dns_positive_control_tolerates_a_bounded_number_of_transient_failures(monkeypatch, attempts):
    tool = load_installer()
    calls, sleeps = [], []

    def query(plan):
        calls.append(plan)
        assert plan["targets"][0]["expected"] == "allowed"
        return {"checks": [{"name": "cluster-dns", "ok": len(calls) == attempts}]}

    monkeypatch.setattr(k8s_capabilities, "network_checks", query)
    monkeypatch.setattr(tool.time, "sleep", sleeps.append)
    tool.InstallationVerifier._control_connect(DNS)
    assert len(calls) == attempts and sleeps == [0.2] * (attempts - 1)


@pytest.mark.parametrize(
    "rows",
    [[], [{"name": "wrong", "ok": True}], [{"name": "cluster-dns", "ok": False}], [{"name": "cluster-dns", "ok": 1}]],
)
def test_dns_positive_control_stays_failed_when_confirmation_never_arrives(monkeypatch, rows):
    tool = load_installer()
    calls, sleeps = [], []

    def query(_):
        calls.append(1)
        return {"checks": rows}

    monkeypatch.setattr(k8s_capabilities, "network_checks", query)
    monkeypatch.setattr(tool.time, "sleep", sleeps.append)
    with pytest.raises(tool.ProbeError, match="dns_control_unconfirmed"):
        tool.InstallationVerifier._control_connect(DNS)
    assert len(calls) == 3 and sleeps == [0.2, 0.2]


def test_dns_invalid_plan_is_not_retried_or_swallowed(monkeypatch):
    tool = load_installer()
    calls = []

    def invalid(_):
        calls.append(1)
        raise ValueError("probe_network_target_invalid")

    monkeypatch.setattr(k8s_capabilities, "network_checks", invalid)
    monkeypatch.setattr(tool.time, "sleep", lambda _: pytest.fail("Invalid plans are not transient DNS failures"))
    with pytest.raises(ValueError, match="probe_network_target_invalid"):
        tool.InstallationVerifier._control_connect(DNS)
    assert len(calls) == 1


def test_denied_dns_probe_fails_on_first_actual_response_without_retry(monkeypatch):
    sends = []

    class DnsSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def settimeout(self, value):
            assert value == 1

        def connect(self, address):
            assert address == (DNS["host"], DNS["port"])

        def send(self, query):
            sends.append(query)

        def recv(self, size):
            return sends[-1][:2] + b"\x81\x80" + b"\x00" * 8

    import socket

    monkeypatch.setattr(socket, "socket", lambda *_: DnsSocket())
    result = k8s_capabilities.network_checks({"targets": [DNS]})
    assert result == {"checks": [{"name": "cluster-dns", "ok": False, "reason": "dns_response"}]}
    assert len(sends) == 1
