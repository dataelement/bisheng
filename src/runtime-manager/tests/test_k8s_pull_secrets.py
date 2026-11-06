"""Installer canaries reference the operator's Secret in their own namespace."""

import json

import pytest

from tests.test_k8s_installation import load_installer, registry_upstream_verifier, render
from tests.test_k8s_installation import values as values


def descriptor(documents):
    config = next(
        item
        for item in documents
        if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "runtime-deployment-descriptor"
    )
    return json.loads(config["data"]["descriptor.json"])


def assert_only_pull_reference(pod, expected):
    if expected:
        assert pod["spec"]["imagePullSecrets"] == [{"name": expected}]
    else:
        assert "imagePullSecrets" not in pod["spec"]
    # Kubelet uses the imagePullSecret; no credential is mounted into canaries.
    assert all("secret" not in volume and "projected" not in volume for volume in pod["spec"]["volumes"])
    assert not pod["spec"]["automountServiceAccountToken"]


@pytest.mark.parametrize(
    "execution_secret,control_secret",
    [("execution-registry", "control-registry"), ("execution-only", ""), ("", "control-only"), ("", "")],
)
def test_chart_descriptor_and_generated_pods_use_namespace_local_pull_references(
    values, tmp_path, monkeypatch, execution_secret, control_secret
):
    values["execution"]["namespace"] = "isolated-apps"
    values["services"]["namespace"] = "isolated-control"
    values["execution"]["pullSecret"] = execution_secret
    values["services"]["pullSecret"] = control_secret
    documents = render(values, tmp_path)
    document = descriptor(documents)
    assert document["pull_secret"] == execution_secret
    assert document["control_pull_secret"] == control_secret
    deployments = [item for item in documents if item["kind"] == "Deployment"]
    for deployment in deployments:
        spec = deployment["spec"]["template"]["spec"]
        if control_secret:
            assert spec["imagePullSecrets"] == [{"name": control_secret}]
        else:
            assert "imagePullSecrets" not in spec

    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier.document = document
    verifier.namespace = "isolated-apps"
    verifier.api.execution = "isolated-apps"
    verifier.api.control = "isolated-control"
    verifier._create = lambda pod: pod

    # All execution canary forms pass through _pod, including an alternate
    # profile image and storage checks with a private helper init container.
    for action, options in (
        ("idle", {}),
        ("network", {"targets": [{"name": "egress", "host": "192.0.2.10", "port": 3128, "expected": "allowed"}]}),
        ("storage", {"pvc": "preflight-volume"}),
        ("idle", {"image": "example/python@sha256:" + "b" * 64, "command": ("python", "--version")}),
    ):
        pod = verifier._pod(action, **options)
        assert pod["metadata"]["namespace"] == "isolated-apps"
        assert_only_pull_reference(pod, execution_secret)

    targets = [{"name": "upstream", "host": "192.0.2.20", "port": 443, "expected": "allowed"}]
    for role in ("egress-proxy", "preflight-untrusted"):
        control_pod = verifier._control_probe(role, targets)
        assert control_pod["metadata"]["namespace"] == "isolated-control"
        assert_only_pull_reference(control_pod, control_secret)
    assert not any(call[:2] == ("get", "secret") for call in verifier.api.calls)
    assert not any(item["kind"] == "Secret" for item in documents)


def test_legacy_descriptor_without_secret_keys_keeps_public_image_canaries_working(monkeypatch):
    tool = load_installer()
    verifier = registry_upstream_verifier(tool, monkeypatch)
    verifier._create = lambda pod: pod
    assert "pull_secret" not in verifier.document and "control_pull_secret" not in verifier.document
    assert_only_pull_reference(verifier._pod("idle"), "")
    targets = [{"name": "upstream", "host": "192.0.2.20", "port": 443, "expected": "allowed"}]
    assert_only_pull_reference(verifier._control_probe("egress-proxy", targets), "")
